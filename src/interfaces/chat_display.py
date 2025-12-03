from abc import ABC, abstractmethod
from chem_scout_ai.common import types


class ChatDisplay(ABC):
    """Abstract base class for displaying chat messages."""

    @abstractmethod
    def clear(self) -> None:
        """Clears the display."""
        raise NotImplementedError

    @abstractmethod
    def display_system(self, message: types.SystemMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    def display_user(self, message: types.UserMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    def display_assistant(self, message: types.AssistantMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    def display_tool_call(self, tool_call: types.ToolCall) -> None:
        raise NotImplementedError

    @abstractmethod
    def display_tool_call_output(self, message: types.ToolCallOutput) -> None:
        raise NotImplementedError

    def display(self, message: types.Message) -> None:
        role = getattr(message, "role", "assistant")

        if role == "system":
            self.display_system(message)
        elif role == "assistant":
            if message.content:
                self.display_assistant(message)
            for tc in getattr(message, "tool_calls", []) or []:
                self.display_tool_call(tc)
        elif role == "user":
            self.display_user(message)
        elif role == "tool":
            self.display_tool_call_output(message)
        else:
            raise ValueError(f"Unknown role: {role}")
