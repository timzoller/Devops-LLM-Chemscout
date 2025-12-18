import threading
import time
import asyncio

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.utils.logger import get_logger
from src.tools.chem_scout_mcp_tools import SERVER
from src.database.db import init_db
from src.utils.chat_history_logger import create_full_observer_suite

import openai

from chem_scout_ai.common.backend import Gemini2p5Flash
from src.agents.router import classify_intent
from src.agents.factory import build_agents
from chem_scout_ai.common import types

logger = get_logger(__name__)


# ================================================================
# Persistent event loop in a dedicated thread
# This keeps MCP connections alive across calls
# ================================================================
def _windows_exception_handler(loop, context):
    """
    Custom exception handler for the asyncio event loop.
    Suppresses benign Windows socket cleanup errors (WinError 10054).
    """
    exception = context.get('exception')
    message = context.get('message', '')
    
    # Suppress ConnectionResetError during socket cleanup on Windows
    # This happens when the remote end closes the connection before we do
    if isinstance(exception, ConnectionResetError):
        # Check if it's the specific Windows error 10054
        if hasattr(exception, 'winerror') and exception.winerror == 10054:
            # Silently ignore - this is benign during connection cleanup
            return
        # Also check the errno for cross-platform compatibility
        if hasattr(exception, 'errno') and exception.errno == 10054:
            return
    
    # For OSError with specific Windows error codes, also suppress
    if isinstance(exception, OSError):
        if hasattr(exception, 'winerror') and exception.winerror in (10054, 10053):
            return
    
    # Log other exceptions normally
    if exception:
        logger.warning(f"Asyncio exception: {message} - {exception}")
    else:
        logger.warning(f"Asyncio exception: {message}")


class AsyncLoopThread:
    """
    Manages a persistent asyncio event loop in a background thread.
    This prevents connection resets by keeping the loop (and its connections) alive.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._loop = None
        self._thread = None
        self._initialized = True
    
    def _run_loop(self):
        """Run the event loop forever in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # Set custom exception handler to suppress Windows socket cleanup errors
        self._loop.set_exception_handler(_windows_exception_handler)
        self._loop.run_forever()
    
    def start(self):
        """Start the background event loop thread if not already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        # Wait for loop to be ready
        while self._loop is None:
            time.sleep(0.01)
    
    def run_coroutine(self, coro):
        """
        Submit a coroutine to the persistent event loop and wait for result.
        Thread-safe: can be called from any thread.
        """
        self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()


# Global instance
_async_loop = AsyncLoopThread()


def run_async(coro):
    """
    Run an async coroutine from Streamlit's sync context.
    Uses a persistent event loop to keep MCP connections alive.
    """
    return _async_loop.run_coroutine(coro)


# ================================================================
# Start MCP server in the background (same idea as main.py)
# ================================================================
def _run_mcp():
    import uvicorn

    uvicorn.run(
        SERVER.streamable_http_app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


def start_mcp_background():
    """
    Start the MCP server only once per Streamlit session.
    """
    if "mcp_thread" in st.session_state:
        return

    thread = threading.Thread(target=_run_mcp, daemon=True)
    thread.start()
    st.session_state["mcp_thread"] = thread
    logger.info("MCP server started in background on http://127.0.0.1:8000/mcp")
    
    # Give the server time to start up before accepting requests
    time.sleep(2)


# ================================================================
# One-time app initialization (DB, backend, agents)
# ================================================================
def init_app():
    if st.session_state.get("initialized"):
        return

    # 1) DB
    init_db()
    logger.info("Database initialized (Streamlit).")

    # 2) MCP server
    start_mcp_background()

    # 3) LLM backend (Gemini 2.5 Flash via Google)
    backend_cfg = Gemini2p5Flash()
    backend = backend_cfg.get_async_backend()
    logger.info(f"Backend initialized ({backend_cfg.name}).")

    # 4) Build agents (data + order)
    agents = build_agents(backend)
    # agents = { "data": (agent, chat), "order": (agent, chat) }

    # 5) Set up full observer suite (history, analytics, rate limiting, audit, tools)
    composite_observer, observers = create_full_observer_suite(
        session_name="streamlit",
        rate_limit_warning_callback=lambda msg: st.toast(msg, icon="⚠️"),
        rate_limit_exceeded_callback=lambda msg: st.toast(msg, icon="🚫"),
    )
    for agent_name, (agent, chat) in agents.items():
        chat.add_observer(composite_observer)
    logger.info(f"Observer suite enabled - History: {observers['history'].filepath}")

    st.session_state["backend"] = backend
    st.session_state["agents"] = agents
    st.session_state["observers"] = observers
    st.session_state["initialized"] = True
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("processing", False)  # Track if a request is in progress
    
    # Initialize result storage for each tab
    st.session_state.setdefault("search_result", "")
    st.session_state.setdefault("add_product_result", "")
    st.session_state.setdefault("orders_result", "")
    st.session_state.setdefault("create_order_result", "")
    st.session_state.setdefault("spending_result", "")


# ================================================================
# Cross-agent handoff detection (similar to main.py)
# ================================================================
HANDOFF_PREFIX = "HANDOFF:"


async def process_handoff(message, user_text: str, agents, chat_updates: list) -> list:
    """
    Detects HANDOFF:<target>:<reason> messages and routes the request to
    the target agent. Returns list of responses from the target agent,
    or empty list if no handoff occurred.
    
    chat_updates: list to append chat history updates (thread-safe accumulator)
    """
    if getattr(message, "role", None) != "assistant":
        return []

    content = getattr(message, "content", None)
    if not (isinstance(content, str) and content.startswith(HANDOFF_PREFIX)):
        return []

    try:
        _, target_raw, reason = content.split(":", 2)
    except ValueError:
        return []

    target = target_raw.strip().lower()
    if target not in agents:
        return []

    reason = reason.strip() or "no reason provided"
    target_agent, target_chat = agents[target]

    # Forward the user's latest message and a short system note
    target_chat.append(types.UserMessage(role="user", content=user_text))
    target_chat.append(
        types.SystemMessage(
            role="system",
            content=f"Handoff from the other agent. Reason: {reason}",
        )
    )

    # Add handoff notification to chat updates
    chat_updates.append({
        "role": "assistant",
        "content": f"🔄 *Handing off to **{target}** agent: {reason}*"
    })

    # Invoke the target agent with retry logic for transient errors
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            handoff_responses = await target_agent(chat=target_chat)
            return handoff_responses
        except (openai.InternalServerError, openai.APIStatusError) as e:
            # Handle 503 (overloaded) and other transient API errors
            status_code = getattr(e, 'status_code', None)
            if status_code in (503, 429, 500, 502, 504) and attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                logger.warning(f"Handoff API error {status_code} (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            logger.exception("Handoff agent error after retries")
            return [types.AssistantMessage(role="assistant", content=f"⚠️ Handoff failed (API error {status_code}): `{e}`\n\nThe model may be overloaded. Please try again in a moment.")]
        except Exception as e:
            logger.exception("Handoff agent error")
            return [types.AssistantMessage(role="assistant", content=f"⚠️ Handoff error: `{e}`")]
    
    return [types.AssistantMessage(role="assistant", content="⚠️ Handoff failed after multiple retries. Please try again.")]


# ================================================================
# Helper: send one message through router + proper agent
# ================================================================
async def handle_user_message(user_text: str, backend, agents) -> dict:
    """
    1) Use router to choose data / order agent
    2) Call that agent
    3) Collect messages for chat_history (returned, not stored directly)
    4) Handle cross-agent handoffs
    
    Args:
        user_text: The user's input message
        backend: The LLM backend (passed from main thread)
        agents: The agents dict (passed from main thread)
    
    Returns a dict with:
        - success: bool
        - error: str or None
        - retried: bool
        - chat_updates: list of messages to add to chat history
    """
    result = {"success": False, "error": None, "retried": False, "chat_updates": []}
    chat_updates = result["chat_updates"]

    # 1) Decide which agent to use (with retry for transient errors)
    intent = None
    for attempt in range(3):
        try:
            intent = await classify_intent(user_text, backend)
            logger.info(f"Router selected agent: {intent}")
            break
        except (openai.InternalServerError, openai.APIStatusError) as e:
            status_code = getattr(e, 'status_code', None)
            if status_code in (503, 429, 500, 502, 504) and attempt < 2:
                wait_time = (attempt + 1) * 2
                logger.warning(f"Router API error {status_code} (attempt {attempt + 1}/3), retrying in {wait_time}s...")
                result["retried"] = True
                await asyncio.sleep(wait_time)
                continue
            logger.exception("Router classification error after retries")
            result["error"] = f"Classification error: {e}"
            chat_updates.append({
                "role": "assistant",
                "content": f"⚠️ Could not classify intent (API error {status_code}): `{e}`\n\nThe model may be overloaded. Please try again."
            })
            return result
        except Exception as e:
            logger.exception("Router classification error")
            result["error"] = f"Classification error: {e}"
            chat_updates.append({
                "role": "assistant",
                "content": f"⚠️ Could not classify intent: `{e}`\n\nPlease try again."
            })
            return result
    
    if intent is None:
        result["error"] = "Failed to classify intent after retries"
        chat_updates.append({
            "role": "assistant",
            "content": "⚠️ Could not classify intent after multiple retries. Please try again."
        })
        return result

    agent, chat = agents[intent]

    # 2) Add user message to this agent's chat
    user_msg = types.UserMessage(role="user", content=user_text)
    chat.append(user_msg)

    # Also store in UI chat history updates
    chat_updates.append({"role": "user", "content": user_text})

    # 3) Call the agent with retry logic
    max_retries = 3
    responses = None
    
    for attempt in range(max_retries + 1):
        try:
            responses = await agent(chat=chat)
            break  # Success, exit retry loop
        except (openai.InternalServerError, openai.APIStatusError) as e:
            # Handle 503 (overloaded), 429 (rate limit), and other transient API errors
            status_code = getattr(e, 'status_code', None)
            if status_code in (503, 429, 500, 502, 504) and attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                logger.warning(f"API error {status_code} (attempt {attempt + 1}/{max_retries + 1}), retrying in {wait_time}s...")
                result["retried"] = True
                await asyncio.sleep(wait_time)
                continue
            logger.exception("Agent API error after retries")
            result["error"] = str(e)
            chat_updates.append({
                "role": "assistant",
                "content": f"⚠️ API error after {max_retries + 1} attempts (code {status_code}): `{e}`\n\n"
                           f"The model may be overloaded. Please wait a moment and try again."
            })
            return result
        except ConnectionError as e:
            logger.warning(f"Connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                result["retried"] = True
                await asyncio.sleep(2)  # Wait before retry
                continue
            logger.exception("Agent connection error after retries")
            result["error"] = str(e)
            chat_updates.append({
                "role": "assistant",
                "content": f"⚠️ Connection error after {max_retries + 1} attempts: `{e}`\n\n"
                           f"The MCP server may not be responding. Please wait a moment and try again."
            })
            return result
        except Exception as e:
            logger.exception("Agent error")
            result["error"] = str(e)
            chat_updates.append({
                "role": "assistant",
                "content": f"⚠️ Agent error: `{e}`"
            })
            return result

    if responses is None:
        result["error"] = "No response from agent"
        return result

    # 4) Process responses for display, with handoff detection
    logger.info(f"Processing {len(responses)} responses from agent")
    
    for msg in responses:
        # Check for cross-agent handoff
        handoff_responses = await process_handoff(msg, user_text, agents, chat_updates)
        if handoff_responses:
            # Process responses from the handoff target agent
            logger.info(f"Processing {len(handoff_responses)} handoff responses")
            for hmsg in handoff_responses:
                role = getattr(hmsg, "role", None)
                content = getattr(hmsg, "content", "")
                
                # Log for debugging
                logger.debug(f"Handoff message - role: {role}, content length: {len(content) if content else 0}")
                
                if not content:
                    continue
                    
                if role == "assistant":
                    chat_updates.append({
                        "role": "assistant",
                        "content": str(content)
                    })
                elif role == "tool":
                    # Also show tool outputs from handoff agent for transparency
                    # But only if they contain meaningful data (not just status messages)
                    try:
                        import json
                        tool_data = json.loads(content) if isinstance(content, str) else content
                        # Check if it's an order creation result (has order_id)
                        if isinstance(tool_data, dict) and "order_id" in tool_data:
                            chat_updates.append({
                                "role": "assistant",
                                "content": f"✅ **Order Created:**\n```json\n{json.dumps(tool_data, indent=2)}\n```"
                            })
                        # Check for notification result
                        elif isinstance(tool_data, dict) and tool_data.get("status") == "ok" and "method" in tool_data:
                            method = tool_data.get("method", "file")
                            chat_updates.append({
                                "role": "assistant",
                                "content": f"📧 **Notification sent** ({method})"
                            })
                    except (json.JSONDecodeError, TypeError):
                        # Not JSON, skip or show raw if it's meaningful
                        if len(content) > 10 and len(content) < 500:
                            logger.debug(f"Non-JSON tool output: {content[:100]}")
            continue  # Skip original handoff message
        
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", "")
        
        # Try alternative content attributes if content is empty
        if not content:
            content = getattr(msg, "text", "") or getattr(msg, "message", "")
        
        # Log what we're seeing for debugging
        logger.debug(f"Message - role: {role}, content length: {len(content) if content else 0}, type: {type(msg)}")

        if not content:
            continue

        if role == "assistant":
            chat_updates.append({"role": "assistant", "content": str(content)})
        elif role == "tool":
            # Show tool output as JSON block
            chat_updates.append({
                "role": "assistant",
                "content": f"🛠️ Tool output:\n```json\n{content}\n```"
            })
        else:
            # Capture any other role with content (might be useful)
            logger.info(f"Unknown role '{role}' with content: {content[:100]}...")
            if content:
                chat_updates.append({
                    "role": "assistant", 
                    "content": str(content)
                })
    
    # If we processed responses but didn't add any assistant content, add a fallback
    has_assistant_content = any(
        msg.get("role") == "assistant" and msg.get("content") 
        for msg in chat_updates 
        if msg.get("role") != "user"
    )
    
    if not has_assistant_content and responses:
        # Extract the last assistant message with content
        for msg in reversed(responses):
            content = getattr(msg, "content", None)
            if content:
                chat_updates.append({
                    "role": "assistant",
                    "content": content
                })
                break
        else:
            # No content found - show a generic message
            chat_updates.append({
                "role": "assistant",
                "content": "⚠️ The agent completed processing but didn't provide a text response."
            })

    result["success"] = True
    return result


# ================================================================
# Helper: Extract assistant response from chat updates
# ================================================================
def _extract_assistant_response(chat_updates: list) -> str:
    """
    Extracts and combines all assistant responses from chat updates.
    Filters out user messages and tool outputs, keeping only meaningful responses.
    """
    responses = []
    for msg in chat_updates:
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            # Skip handoff messages and empty content
            if content and not content.startswith("🔄 *Handing off"):
                responses.append(content)
    
    return "\n\n".join(responses) if responses else ""


# ================================================================
# Streamlit UI definition
# ================================================================
def main():
    st.set_page_config(page_title="ChemScout AI", page_icon="🧪")
    st.title("🧪 ChemScout AI – Web Prototype")
    st.caption("LLM-driven multi-agent system for chemical procurement")

    # Initialize once per session
    init_app()

    # Sidebar
    with st.sidebar:
        st.header("Session info")
        st.write("Agents: **data** & **order**")
        st.write("Orchestration: MCP tools + async agents")
        st.markdown("---")
        
        # Analytics display
        if "observers" in st.session_state:
            observers = st.session_state["observers"]
            
            # Rate limit status
            rate_status = observers["rate_limit"].get_status()
            st.markdown("### 📊 Session Stats")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Messages", rate_status["total_messages"])
            with col2:
                st.metric("Remaining", rate_status["remaining_messages"])
            
            # Tool usage
            tool_stats = observers["tools"].get_stats()
            st.write(f"🛠️ Tool calls: **{tool_stats.get('total_calls', 0)}**")
            
            if rate_status["is_rate_limited"]:
                st.warning(f"⏳ Rate limited ({rate_status['cooldown_remaining']}s)")
        
        st.markdown("---")
        st.write(
            "⚠️ LLM calls use free-tier APIs.\n"
            "If you see 429 / quota errors, it just means the daily limit is reached."
        )

        if st.button("Clear chat"):
            st.session_state["chat_history"] = []
            st.success("Chat history cleared.")
        
        if st.button("Clear tab results"):
            st.session_state["search_result"] = ""
            st.session_state["add_product_result"] = ""
            st.session_state["orders_result"] = ""
            st.session_state["create_order_result"] = ""
            st.session_state["spending_result"] = ""
            st.success("Tab results cleared.")
            st.rerun()

    # Tabs
    tab_chat, tab_search, tab_add, tab_orders = st.tabs(
        ["💬 Chat", "🔎 Quick Search", "➕ Add Product", "📦 Orders & Spending"]
    )

    # ===================== TAB 1: CHAT =====================
    with tab_chat:
        st.subheader("Chat with ChemScout")

        # Show history
        for msg in st.session_state["chat_history"]:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                with st.chat_message("user"):
                    st.markdown(content)
            else:
                with st.chat_message("assistant"):
                    st.markdown(content)

        # Chat input (disabled while processing to prevent double-submission)
        is_processing = st.session_state.get("processing", False)
        
        user_input = st.chat_input(
            "⏳ Processing... please wait" if is_processing else "Ask about chemicals, suppliers, orders…",
            disabled=is_processing
        )
        
        if user_input:
            # Mark as processing immediately
            st.session_state["processing"] = True
            
            # Get backend and agents from session state (in main thread)
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            
            # Show the user message right away
            with st.chat_message("user"):
                st.markdown(user_input)
            
            # Process with visible spinner
            with st.chat_message("assistant"):
                with st.spinner("🧪 ChemScout is thinking..."):
                    result = run_async(handle_user_message(user_input, backend, agents))
            
            # Apply chat updates to session state (in main thread)
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            # Show retry notification if applicable
            if result.get("retried"):
                st.toast("Connection was unstable but request succeeded after retry", icon="🔄")
            
            # Rerun to display the complete chat history properly
            st.rerun()

    # ===================== TAB 2: QUICK SEARCH =====================
    with tab_search:
        st.subheader("Quick Search in Product Database")

        with st.form("search_form"):
            name = st.text_input("Chemical name", placeholder="e.g. Acetone")
            cas = st.text_input("CAS number", placeholder="e.g. 67-64-1")
            supplier = st.text_input("Supplier (optional)", placeholder="e.g. Sigma")
            max_price = st.text_input("Max price (optional, e.g. 50 CHF)")
            submitted = st.form_submit_button(
                "Search",
                disabled=st.session_state.get("processing", False)
            )

        if submitted and not st.session_state.get("processing"):
            query = (
                "Search the product database for matching chemicals and show "
                "a compact table of results.\n\n"
                f"Name: {name or 'any'}\n"
                f"CAS: {cas or 'any'}\n"
                f"Supplier: {supplier or 'any'}\n"
                f"Max price: {max_price or 'no limit'}"
            )
            st.session_state["processing"] = True
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            with st.spinner("🔍 Searching..."):
                result = run_async(handle_user_message(query, backend, agents))
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            if result.get("success"):
                # Store the last assistant response for display
                extracted = _extract_assistant_response(result.get("chat_updates", []))
                if extracted:
                    st.session_state["search_result"] = extracted
                else:
                    # Fallback: show all non-user content
                    all_content = "\n\n".join([
                        msg.get("content", "") 
                        for msg in result.get("chat_updates", []) 
                        if msg.get("role") != "user"
                    ])
                    st.session_state["search_result"] = all_content or "⚠️ Search completed but no results returned."
            else:
                st.session_state["search_result"] = f"❌ Search failed: {result.get('error', 'Unknown error')}"
            st.rerun()
        
        # Display search results directly in this tab
        if "search_result" in st.session_state and st.session_state["search_result"]:
            st.markdown("---")
            st.markdown("### 🔍 Search Results")
            st.markdown(st.session_state["search_result"])

    # ===================== TAB 3: ADD PRODUCT =====================
    with tab_add:
        st.subheader("Add a New Product")

        with st.form("add_product_form"):
            name = st.text_input("Name", placeholder="Acetone")
            cas = st.text_input("CAS number", placeholder="67-64-1")
            supplier = st.text_input("Supplier", placeholder="Sigma-Aldrich")
            price = st.text_input("Price (numeric)", placeholder="45")
            currency = st.text_input("Currency", value="CHF")
            package = st.text_input("Package size", placeholder="1L")
            purity = st.text_input("Purity", placeholder="99.8%")
            delivery = st.text_input("Delivery time (days)", placeholder="3")
            submitted_add = st.form_submit_button(
                "Add product",
                disabled=st.session_state.get("processing", False)
            )

        if submitted_add and not st.session_state.get("processing"):
            prompt = (
                "Add a new product to the database using add_product_tool with these values:\n"
                f"- name: {name}\n"
                f"- cas_number: {cas}\n"
                f"- supplier: {supplier}\n"
                f"- price: {price}\n"
                f"- currency: {currency}\n"
                f"- package_size: {package}\n"
                f"- purity: {purity}\n"
                f"- delivery_time_days: {delivery}\n\n"
                "Call the tool, then confirm the insertion with the returned product_id."
            )
            st.session_state["processing"] = True
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            with st.spinner("➕ Adding product..."):
                result = run_async(handle_user_message(prompt, backend, agents))
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            if result.get("success"):
                extracted = _extract_assistant_response(result.get("chat_updates", []))
                if extracted:
                    st.session_state["add_product_result"] = extracted
                else:
                    all_content = "\n\n".join([
                        msg.get("content", "") 
                        for msg in result.get("chat_updates", []) 
                        if msg.get("role") != "user"
                    ])
                    st.session_state["add_product_result"] = all_content or "⚠️ Product operation completed but no details returned."
            else:
                st.session_state["add_product_result"] = f"❌ Failed to add product: {result.get('error', 'Unknown error')}"
            st.rerun()
        
        # Display add product results directly in this tab
        if "add_product_result" in st.session_state and st.session_state["add_product_result"]:
            st.markdown("---")
            st.markdown("### ✅ Result")
            st.markdown(st.session_state["add_product_result"])

    # ===================== TAB 4: ORDERS & SPENDING =====================
    with tab_orders:
        st.subheader("Orders & Monthly Spending")

        st.markdown("### Open Orders")
        is_processing = st.session_state.get("processing", False)
        
        if st.button("List open orders", disabled=is_processing):
            prompt = (
                "List all currently open chemical orders from the database. "
                "Show them in a table with product, supplier, quantity, price, and status."
            )
            st.session_state["processing"] = True
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            with st.spinner("📦 Fetching orders..."):
                result = run_async(handle_user_message(prompt, backend, agents))
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            if result.get("success"):
                extracted = _extract_assistant_response(result.get("chat_updates", []))
                if extracted:
                    st.session_state["orders_result"] = extracted
                else:
                    all_content = "\n\n".join([
                        msg.get("content", "") 
                        for msg in result.get("chat_updates", []) 
                        if msg.get("role") != "user"
                    ])
                    st.session_state["orders_result"] = all_content or "⚠️ Orders fetched but no details returned."
            else:
                st.session_state["orders_result"] = f"❌ Failed to fetch orders: {result.get('error', 'Unknown error')}"
            st.rerun()
        
        # Display orders results
        if "orders_result" in st.session_state and st.session_state["orders_result"]:
            st.markdown(st.session_state["orders_result"])

        st.markdown("---")
        st.markdown("### Create a Simple Order")

        with st.form("create_order_form"):
            prod_name = st.text_input("Product name", placeholder="e.g. Aspirin, Metformin, Caffeine")
            quantity = st.text_input("Quantity (with unit)", placeholder="e.g. 500 g, 1 L, 100 mL")
            pref_supplier = st.text_input("Preferred supplier (optional)", placeholder="e.g. Sigma-Aldrich, TCI")
            submitted_order = st.form_submit_button(
                "Create order",
                disabled=is_processing
            )

        if submitted_order and not is_processing:
            # Parse quantity and unit
            qty_parts = quantity.strip().split()
            qty_value = qty_parts[0] if qty_parts else quantity
            qty_unit = qty_parts[1] if len(qty_parts) > 1 else "g"
            
            # Build clear supplier instructions
            supplier_instruction = ""
            if pref_supplier and pref_supplier.lower() not in ("any", ""):
                supplier_instruction = f"Preferred supplier: {pref_supplier} (if not available, use any available supplier or create external order)"
            else:
                supplier_instruction = "No supplier preference - use best available option"
            
            # Use the FULL product name for search, not just first word
            search_query = prod_name.strip() if prod_name else "chemical"
            
            prompt = (
                "AUTOMATED ORDER REQUEST - Execute immediately without asking for confirmation.\n\n"
                f"Chemical: {prod_name}\n"
                f"Quantity: {qty_value} {qty_unit}\n"
                f"{supplier_instruction}\n\n"
                "REQUIRED ACTIONS (execute all in sequence):\n"
                f"1. Search: search_products_tool(query=\"{search_query}\")\n"
                "2. Create order: Use found product_id, OR product_id=0 for external\n"
                "3. Notify: Call notify_customer_tool with the order_id\n"
                "4. Inventory: Call request_inventory_revision_tool\n\n"
                "FINAL RESPONSE MUST INCLUDE:\n"
                "- Order ID (e.g., ORD-XXXXXXXX)\n"
                "- Product details and supplier\n"
                "- Confirmation that notification was sent"
            )
            st.session_state["processing"] = True
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            with st.spinner("📝 Creating order..."):
                result = run_async(handle_user_message(prompt, backend, agents))
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            if result.get("success"):
                extracted = _extract_assistant_response(result.get("chat_updates", []))
                if extracted:
                    st.session_state["create_order_result"] = extracted
                else:
                    # Fallback: show all chat updates if extraction is empty
                    all_content = "\n\n".join([
                        msg.get("content", "") 
                        for msg in result.get("chat_updates", []) 
                        if msg.get("role") != "user"
                    ])
                    st.session_state["create_order_result"] = all_content or "⚠️ Order processed but no details returned. Check the Chat tab."
            else:
                st.session_state["create_order_result"] = f"❌ Failed to create order: {result.get('error', 'Unknown error')}"
            st.rerun()
        
        # Display create order results
        if "create_order_result" in st.session_state and st.session_state["create_order_result"]:
            st.markdown("#### 📋 Order Result")
            st.markdown(st.session_state["create_order_result"])

        st.markdown("---")
        st.markdown("### Monthly Spending Overview")

        with st.form("spending_form"):
            month = st.text_input("Month (1-12)", placeholder="2")
            year = st.text_input("Year", placeholder="2025")
            submitted_spend = st.form_submit_button(
                "Show spending",
                disabled=is_processing
            )

        if submitted_spend and not is_processing:
            prompt = (
                "Calculate monthly chemical spending.\n"
                f"Month: {month}\n"
                f"Year: {year}\n"
                "Show the total amount spent and a breakdown per supplier."
            )
            st.session_state["processing"] = True
            backend = st.session_state["backend"]
            agents = st.session_state["agents"]
            with st.spinner("💰 Calculating spending..."):
                result = run_async(handle_user_message(prompt, backend, agents))
            st.session_state["chat_history"].extend(result.get("chat_updates", []))
            st.session_state["processing"] = False
            
            if result.get("success"):
                extracted = _extract_assistant_response(result.get("chat_updates", []))
                if extracted:
                    st.session_state["spending_result"] = extracted
                else:
                    all_content = "\n\n".join([
                        msg.get("content", "") 
                        for msg in result.get("chat_updates", []) 
                        if msg.get("role") != "user"
                    ])
                    st.session_state["spending_result"] = all_content or "⚠️ Spending calculated but no details returned."
            else:
                st.session_state["spending_result"] = f"❌ Failed to calculate spending: {result.get('error', 'Unknown error')}"
            st.rerun()
        
        # Display spending results
        if "spending_result" in st.session_state and st.session_state["spending_result"]:
            st.markdown("#### 💰 Spending Report")
            st.markdown(st.session_state["spending_result"])


if __name__ == "__main__":
    main()