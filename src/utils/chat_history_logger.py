"""
Chat observers implementing ChatObserver protocol.
Includes: history logging, analytics, rate limiting, audit logging, tool use tracking.
"""

import json
import hashlib
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from chem_scout_ai.common import types
from chem_scout_ai.common.chat import ChatObserver
from src.config import (
    CHAT_HISTORY_DIR,
    ANALYTICS_DIR,
    AUDIT_LOG_DIR,
    RATE_LIMIT_MAX_MESSAGES_PER_SESSION,
    RATE_LIMIT_MAX_MESSAGES_PER_MINUTE,
    RATE_LIMIT_COOLDOWN_SECONDS,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ChatHistoryLogger(ChatObserver):
    """
    Implements ChatObserver to persist chat messages to disk.
    Each session creates a timestamped JSON file that is incrementally updated.
    """

    def __init__(self, session_name: str | None = None):
        """
        Initialize the chat history logger.

        Args:
            session_name: Optional prefix for the log file.
                         Defaults to 'chat' if not provided.
        """
        self._session_name = session_name or "chat"
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"{self._session_name}_{self._timestamp}.json"
        self._filepath = CHAT_HISTORY_DIR / self._filename
        self._messages: list[dict[str, Any]] = []

        # Initialize empty file
        self._save()
        logger.info(f"Chat history logger initialized: {self._filepath}")

    @property
    def filepath(self) -> Path:
        """Returns the path to the chat history file."""
        return self._filepath

    def update(self, message: types.Message) -> None:
        """
        Called when a new message is appended to the chat.
        Persists the message to the log file.
        """
        try:
            msg_dict = self._message_to_dict(message)
            msg_dict["timestamp"] = datetime.now().isoformat()
            self._messages.append(msg_dict)
            self._save()
        except Exception as e:
            logger.error(f"Failed to log chat message: {e}")

    def _message_to_dict(self, message: types.Message) -> dict[str, Any]:
        """Convert a message to a serializable dictionary."""
        if hasattr(message, "to_dict"):
            return message.to_dict()
        elif hasattr(message, "model_dump"):
            return message.model_dump()
        elif isinstance(message, dict):
            return dict(message)
        else:
            # Fallback: extract role and content
            return {
                "role": getattr(message, "role", "unknown"),
                "content": getattr(message, "content", str(message)),
            }

    def _save(self) -> None:
        """Save messages to the JSON file."""
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session": self._session_name,
                        "started": self._timestamp,
                        "messages": self._messages,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,  # Handle non-serializable objects
                )
        except Exception as e:
            logger.error(f"Failed to save chat history: {e}")

    def log_session_end(self) -> None:
        """Mark the session as ended and save final state."""
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session": self._session_name,
                        "started": self._timestamp,
                        "ended": datetime.now().isoformat(),
                        "messages": self._messages,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            logger.info(f"Chat session ended, saved to: {self._filepath}")
        except Exception as e:
            logger.error(f"Failed to save session end: {e}")


def create_session_logger(session_name: str = "chat") -> ChatHistoryLogger:
    """
    Factory function to create a chat history logger.

    Args:
        session_name: Prefix for the log file (e.g., 'main', 'streamlit')

    Returns:
        Configured ChatHistoryLogger instance
    """
    return ChatHistoryLogger(session_name=session_name)


# ============================================================================
# ANALYTICS OBSERVER
# ============================================================================

class ChatAnalyticsObserver(ChatObserver):
    """
    Tracks chat analytics and metrics:
    - Message counts by role
    - Response times
    - Token estimates
    - Tool usage statistics
    - Session duration
    """

    def __init__(self, session_name: str = "analytics"):
        self._session_name = session_name
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"{session_name}_{self._timestamp}.json"
        self._filepath = ANALYTICS_DIR / self._filename
        self._start_time = time.time()
        self._last_message_time: float | None = None
        
        # Metrics
        self._message_counts: dict[str, int] = {
            "user": 0,
            "assistant": 0,
            "system": 0,
            "tool": 0,
        }
        self._total_chars: dict[str, int] = {
            "user": 0,
            "assistant": 0,
            "system": 0,
            "tool": 0,
        }
        self._response_times: list[float] = []  # Time between user and assistant
        self._tool_calls: list[dict[str, Any]] = []
        self._pending_user_time: float | None = None
        
        self._save()
        logger.info(f"Analytics observer initialized: {self._filepath}")

    @property
    def filepath(self) -> Path:
        return self._filepath

    def update(self, message: types.Message) -> None:
        """Track analytics for each message."""
        try:
            current_time = time.time()
            role = getattr(message, "role", "unknown")
            content = getattr(message, "content", "") or ""
            
            # Update counts
            if role in self._message_counts:
                self._message_counts[role] += 1
                self._total_chars[role] += len(str(content))
            
            # Track response time (user -> assistant)
            if role == "user":
                self._pending_user_time = current_time
            elif role == "assistant" and self._pending_user_time:
                response_time = current_time - self._pending_user_time
                self._response_times.append(response_time)
                self._pending_user_time = None
            
            # Track tool calls
            if role == "tool":
                self._track_tool_call(message, current_time)
            
            # Check for tool_calls in assistant messages
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    self._tool_calls.append({
                        "timestamp": datetime.now().isoformat(),
                        "tool_id": getattr(tc, "id", "unknown"),
                        "function": getattr(getattr(tc, "function", None), "name", "unknown"),
                    })
            
            self._last_message_time = current_time
            self._save()
        except Exception as e:
            logger.error(f"Analytics tracking error: {e}")

    def _track_tool_call(self, message: types.Message, timestamp: float) -> None:
        """Extract and track tool call information."""
        tool_call_id = getattr(message, "tool_call_id", None)
        content = getattr(message, "content", "")
        
        self._tool_calls.append({
            "timestamp": datetime.now().isoformat(),
            "tool_call_id": tool_call_id,
            "output_length": len(str(content)) if content else 0,
        })

    def _calculate_metrics(self) -> dict[str, Any]:
        """Calculate summary metrics."""
        total_messages = sum(self._message_counts.values())
        session_duration = time.time() - self._start_time
        
        avg_response_time = (
            sum(self._response_times) / len(self._response_times)
            if self._response_times else 0
        )
        
        # Rough token estimate (1 token ≈ 4 chars for English)
        estimated_tokens = {
            role: chars // 4 for role, chars in self._total_chars.items()
        }
        
        return {
            "total_messages": total_messages,
            "message_counts": self._message_counts,
            "total_chars": self._total_chars,
            "estimated_tokens": estimated_tokens,
            "total_estimated_tokens": sum(estimated_tokens.values()),
            "response_times": {
                "count": len(self._response_times),
                "avg_seconds": round(avg_response_time, 3),
                "min_seconds": round(min(self._response_times), 3) if self._response_times else 0,
                "max_seconds": round(max(self._response_times), 3) if self._response_times else 0,
            },
            "tool_usage": {
                "total_calls": len(self._tool_calls),
                "calls": self._tool_calls[-10:],  # Last 10 calls
            },
            "session_duration_seconds": round(session_duration, 2),
        }

    def _save(self) -> None:
        """Save analytics to file."""
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session": self._session_name,
                        "started": self._timestamp,
                        "last_updated": datetime.now().isoformat(),
                        "metrics": self._calculate_metrics(),
                    },
                    f,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            logger.error(f"Failed to save analytics: {e}")

    def get_summary(self) -> dict[str, Any]:
        """Get current analytics summary."""
        return self._calculate_metrics()


# ============================================================================
# RATE LIMIT OBSERVER
# ============================================================================

class RateLimitObserver(ChatObserver):
    """
    Monitors message rates to prevent abuse:
    - Tracks messages per minute (burst protection)
    - Tracks total session messages
    - Triggers callbacks when limits are approached/exceeded
    """

    def __init__(
        self,
        session_name: str = "rate_limit",
        max_per_session: int = RATE_LIMIT_MAX_MESSAGES_PER_SESSION,
        max_per_minute: int = RATE_LIMIT_MAX_MESSAGES_PER_MINUTE,
        cooldown_seconds: int = RATE_LIMIT_COOLDOWN_SECONDS,
        on_limit_warning: Callable[[str], None] | None = None,
        on_limit_exceeded: Callable[[str], None] | None = None,
    ):
        self._session_name = session_name
        self._max_per_session = max_per_session
        self._max_per_minute = max_per_minute
        self._cooldown_seconds = cooldown_seconds
        
        # Callbacks
        self._on_warning = on_limit_warning or (lambda msg: logger.warning(msg))
        self._on_exceeded = on_limit_exceeded or (lambda msg: logger.error(msg))
        
        # Tracking
        self._total_user_messages = 0
        self._message_timestamps: deque[float] = deque()  # Rolling window
        self._cooldown_until: float | None = None
        self._warnings_issued: set[str] = set()
        
        logger.info(f"Rate limit observer initialized: max {max_per_minute}/min, {max_per_session}/session")

    @property
    def is_rate_limited(self) -> bool:
        """Check if currently rate limited."""
        if self._cooldown_until and time.time() < self._cooldown_until:
            return True
        return False

    @property
    def remaining_messages(self) -> int:
        """Messages remaining before session limit."""
        return max(0, self._max_per_session - self._total_user_messages)

    @property
    def messages_this_minute(self) -> int:
        """Count messages in the last 60 seconds."""
        self._cleanup_old_timestamps()
        return len(self._message_timestamps)

    def update(self, message: types.Message) -> None:
        """Track message rates and check limits."""
        role = getattr(message, "role", "")
        
        # Only track user messages for rate limiting
        if role != "user":
            return
        
        current_time = time.time()
        
        # Check if in cooldown
        if self._cooldown_until and current_time < self._cooldown_until:
            remaining = int(self._cooldown_until - current_time)
            self._on_exceeded(
                f"⏳ Rate limited. Please wait {remaining} seconds before sending more messages."
            )
            return
        
        self._cooldown_until = None  # Clear expired cooldown
        
        # Track this message
        self._total_user_messages += 1
        self._message_timestamps.append(current_time)
        self._cleanup_old_timestamps()
        
        # Check per-minute limit
        if len(self._message_timestamps) >= self._max_per_minute:
            self._cooldown_until = current_time + self._cooldown_seconds
            self._on_exceeded(
                f"🚫 Rate limit exceeded ({self._max_per_minute} messages/minute). "
                f"Cooldown for {self._cooldown_seconds} seconds."
            )
            return
        
        # Check session limit warnings
        remaining = self.remaining_messages
        
        if remaining <= 0 and "session_exceeded" not in self._warnings_issued:
            self._warnings_issued.add("session_exceeded")
            self._on_exceeded(
                f"🚫 Session limit reached ({self._max_per_session} messages). "
                "Please start a new session."
            )
        elif remaining <= 10 and "session_warning_10" not in self._warnings_issued:
            self._warnings_issued.add("session_warning_10")
            self._on_warning(f"⚠️ Approaching session limit: {remaining} messages remaining.")
        elif remaining <= 25 and "session_warning_25" not in self._warnings_issued:
            self._warnings_issued.add("session_warning_25")
            self._on_warning(f"📊 Session message count: {self._total_user_messages}/{self._max_per_session}")

    def _cleanup_old_timestamps(self) -> None:
        """Remove timestamps older than 60 seconds."""
        cutoff = time.time() - 60
        while self._message_timestamps and self._message_timestamps[0] < cutoff:
            self._message_timestamps.popleft()

    def get_status(self) -> dict[str, Any]:
        """Get current rate limit status."""
        return {
            "is_rate_limited": self.is_rate_limited,
            "total_messages": self._total_user_messages,
            "remaining_messages": self.remaining_messages,
            "messages_this_minute": self.messages_this_minute,
            "max_per_minute": self._max_per_minute,
            "max_per_session": self._max_per_session,
            "cooldown_remaining": (
                max(0, int(self._cooldown_until - time.time()))
                if self._cooldown_until else 0
            ),
        }


# ============================================================================
# AUDIT LOG OBSERVER
# ============================================================================

class AuditLogObserver(ChatObserver):
    """
    Compliance-focused audit logging:
    - Immutable, append-only log entries
    - Tracks all actions with timestamps
    - Includes session/user identifiers
    - Logs tool executions with inputs/outputs
    - Generates checksums for integrity verification
    """

    def __init__(
        self,
        session_name: str = "audit",
        user_id: str | None = None,
        session_id: str | None = None,
    ):
        self._session_name = session_name
        self._user_id = user_id or "anonymous"
        self._session_id = session_id or self._generate_session_id()
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"audit_{self._session_id}_{self._timestamp}.jsonl"
        self._filepath = AUDIT_LOG_DIR / self._filename
        self._entry_count = 0
        self._previous_hash: str | None = None
        
        # Write session start entry
        self._write_entry({
            "event_type": "SESSION_START",
            "user_id": self._user_id,
            "session_id": self._session_id,
        })
        
        logger.info(f"Audit log observer initialized: {self._filepath}")

    @property
    def filepath(self) -> Path:
        return self._filepath

    @property
    def session_id(self) -> str:
        return self._session_id

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        import uuid
        return str(uuid.uuid4())[:8].upper()

    def update(self, message: types.Message) -> None:
        """Log message as audit entry."""
        try:
            role = getattr(message, "role", "unknown")
            content = getattr(message, "content", "")
            
            event_type = self._get_event_type(role, message)
            
            entry = {
                "event_type": event_type,
                "role": role,
                "content_length": len(str(content)) if content else 0,
                "content_preview": self._safe_preview(content),
            }
            
            # Add tool-specific info
            if role == "tool":
                entry["tool_call_id"] = getattr(message, "tool_call_id", None)
            
            # Check for tool calls in assistant messages
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": getattr(tc, "id", "unknown"),
                        "function": getattr(getattr(tc, "function", None), "name", "unknown"),
                        "arguments_preview": self._safe_preview(
                            getattr(getattr(tc, "function", None), "arguments", "")
                        ),
                    }
                    for tc in tool_calls
                ]
            
            self._write_entry(entry)
        except Exception as e:
            logger.error(f"Audit log error: {e}")

    def _get_event_type(self, role: str, message: types.Message) -> str:
        """Determine the event type based on message role and content."""
        if role == "user":
            return "USER_INPUT"
        elif role == "assistant":
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                return "ASSISTANT_TOOL_REQUEST"
            return "ASSISTANT_RESPONSE"
        elif role == "tool":
            return "TOOL_EXECUTION"
        elif role == "system":
            return "SYSTEM_MESSAGE"
        return "UNKNOWN"

    def _safe_preview(self, content: Any, max_length: int = 200) -> str:
        """Create a safe preview of content for logging."""
        if content is None:
            return ""
        content_str = str(content)
        if len(content_str) <= max_length:
            return content_str
        return content_str[:max_length] + "..."

    def _calculate_hash(self, entry: dict[str, Any]) -> str:
        """Calculate hash for integrity verification (chain with previous)."""
        data = json.dumps(entry, sort_keys=True, default=str)
        if self._previous_hash:
            data = self._previous_hash + data
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _write_entry(self, entry: dict[str, Any]) -> None:
        """Write an audit entry (append-only)."""
        self._entry_count += 1
        
        full_entry = {
            "entry_id": self._entry_count,
            "timestamp": datetime.now().isoformat(),
            "session_id": self._session_id,
            "user_id": self._user_id,
            **entry,
        }
        
        # Add integrity hash
        full_entry["hash"] = self._calculate_hash(full_entry)
        self._previous_hash = full_entry["hash"]
        
        try:
            with open(self._filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(full_entry, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")

    def log_session_end(self, reason: str = "normal") -> None:
        """Log session end event."""
        self._write_entry({
            "event_type": "SESSION_END",
            "reason": reason,
            "total_entries": self._entry_count,
        })
        logger.info(f"Audit session ended: {self._filepath}")

    def log_custom_event(self, event_type: str, details: dict[str, Any]) -> None:
        """Log a custom audit event."""
        self._write_entry({
            "event_type": event_type,
            **details,
        })


# ============================================================================
# TOOL USE LOGGER
# ============================================================================

class ToolUseLogger(ChatObserver):
    """
    Specifically tracks tool usage:
    - Which tools are called
    - Input arguments
    - Output results
    - Execution patterns
    """

    def __init__(self, session_name: str = "tools"):
        self._session_name = session_name
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._filename = f"tools_{session_name}_{self._timestamp}.json"
        self._filepath = ANALYTICS_DIR / self._filename
        
        self._tool_calls: list[dict[str, Any]] = []
        self._tool_results: dict[str, dict[str, Any]] = {}  # tool_call_id -> result
        self._pending_calls: dict[str, dict[str, Any]] = {}  # tool_call_id -> call info
        
        self._save()
        logger.info(f"Tool use logger initialized: {self._filepath}")

    @property
    def filepath(self) -> Path:
        return self._filepath

    def update(self, message: types.Message) -> None:
        """Track tool calls and results."""
        try:
            role = getattr(message, "role", "")
            
            # Track tool calls from assistant messages
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    call_id = getattr(tc, "id", "unknown")
                    function = getattr(tc, "function", None)
                    
                    call_info = {
                        "call_id": call_id,
                        "function_name": getattr(function, "name", "unknown") if function else "unknown",
                        "arguments": self._parse_arguments(getattr(function, "arguments", "{}") if function else "{}"),
                        "called_at": datetime.now().isoformat(),
                        "result": None,
                        "completed_at": None,
                        "duration_ms": None,
                    }
                    
                    self._pending_calls[call_id] = call_info
                    self._tool_calls.append(call_info)
            
            # Track tool results
            if role == "tool":
                call_id = getattr(message, "tool_call_id", None)
                content = getattr(message, "content", "")
                
                if call_id and call_id in self._pending_calls:
                    call_info = self._pending_calls[call_id]
                    call_info["result"] = self._parse_result(content)
                    call_info["completed_at"] = datetime.now().isoformat()
                    
                    # Calculate duration if we have both timestamps
                    if call_info["called_at"]:
                        called = datetime.fromisoformat(call_info["called_at"])
                        completed = datetime.fromisoformat(call_info["completed_at"])
                        call_info["duration_ms"] = int((completed - called).total_seconds() * 1000)
                    
                    del self._pending_calls[call_id]
            
            self._save()
        except Exception as e:
            logger.error(f"Tool use logging error: {e}")

    def _parse_arguments(self, args_str: str) -> dict[str, Any]:
        """Parse tool arguments from JSON string."""
        try:
            return json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            return {"raw": args_str}

    def _parse_result(self, content: Any) -> dict[str, Any]:
        """Parse tool result content."""
        if not content:
            return {"empty": True}
        
        content_str = str(content)
        
        try:
            parsed = json.loads(content_str)
            return {"parsed": parsed, "length": len(content_str)}
        except json.JSONDecodeError:
            return {"raw_preview": content_str[:500], "length": len(content_str)}

    def _calculate_stats(self) -> dict[str, Any]:
        """Calculate tool usage statistics."""
        if not self._tool_calls:
            return {"total_calls": 0}
        
        # Count by function
        function_counts: dict[str, int] = {}
        durations: list[int] = []
        
        for call in self._tool_calls:
            name = call.get("function_name", "unknown")
            function_counts[name] = function_counts.get(name, 0) + 1
            if call.get("duration_ms"):
                durations.append(call["duration_ms"])
        
        return {
            "total_calls": len(self._tool_calls),
            "by_function": function_counts,
            "pending_calls": len(self._pending_calls),
            "avg_duration_ms": sum(durations) // len(durations) if durations else None,
            "min_duration_ms": min(durations) if durations else None,
            "max_duration_ms": max(durations) if durations else None,
        }

    def _save(self) -> None:
        """Save tool usage log."""
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session": self._session_name,
                        "started": self._timestamp,
                        "last_updated": datetime.now().isoformat(),
                        "stats": self._calculate_stats(),
                        "calls": self._tool_calls,
                    },
                    f,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            logger.error(f"Failed to save tool use log: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get current tool usage statistics."""
        return self._calculate_stats()


# ============================================================================
# COMPOSITE OBSERVER (COMBINES ALL)
# ============================================================================

class CompositeChatObserver(ChatObserver):
    """
    Combines multiple observers into one for easy attachment.
    Delegates to all child observers.
    """

    def __init__(self, *observers: ChatObserver):
        self._observers = list(observers)

    def add_observer(self, observer: ChatObserver) -> None:
        """Add an observer to the composite."""
        self._observers.append(observer)

    def update(self, message: types.Message) -> None:
        """Delegate to all child observers."""
        for observer in self._observers:
            try:
                observer.update(message)
            except Exception as e:
                logger.error(f"Observer {type(observer).__name__} error: {e}")


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

def create_full_observer_suite(
    session_name: str = "chat",
    user_id: str | None = None,
    rate_limit_warning_callback: Callable[[str], None] | None = None,
    rate_limit_exceeded_callback: Callable[[str], None] | None = None,
) -> tuple[CompositeChatObserver, dict[str, ChatObserver]]:
    """
    Create a complete suite of observers for a session.
    
    Returns:
        Tuple of (composite_observer, individual_observers_dict)
    """
    history = ChatHistoryLogger(session_name=session_name)
    analytics = ChatAnalyticsObserver(session_name=session_name)
    rate_limit = RateLimitObserver(
        session_name=session_name,
        on_limit_warning=rate_limit_warning_callback,
        on_limit_exceeded=rate_limit_exceeded_callback,
    )
    audit = AuditLogObserver(session_name=session_name, user_id=user_id)
    tools = ToolUseLogger(session_name=session_name)
    
    composite = CompositeChatObserver(history, analytics, rate_limit, audit, tools)
    
    observers = {
        "history": history,
        "analytics": analytics,
        "rate_limit": rate_limit,
        "audit": audit,
        "tools": tools,
    }
    
    logger.info(f"Full observer suite created for session: {session_name}")
    
    return composite, observers

