"""Provides an abstraction for displaying chat messages."""

import abc
import typing

from chem_scout_ai.common import chat, types


class ChatDisplay(abc.ABC, chat.ChatObserver):
    """
    Abstract base class for displaying chat messages.

    Concrete implementations could be:
    - Terminal UI
    - Web UI
    - Jupyter display
    """

    @typing.override
    def update(self, message: types.Message) -> None:
        """Triggered whenever the chat receives a new message."""
        self.display(message)

    # ------------------------------------------------------------------
    @abc.abstractmethod
    def clear(self) -> None:
        """Clears the display."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    @staticmethod
    def content(message: types.Message) -> str:
        """
        Returns the textual content of a message,
        independent of whether it's stored as an object attribute or dict.
        """
        return (
            message.content
            if hasattr(message, "content")
            else message["content"]
        )

    # ------------------------------------------------------------------
    @staticmethod
    def role(message: types.Message) -> str | None:
        """
        Returns the message role:
        'system', 'user', 'assistant', or 'tool'
        """
        if hasattr(message, "role"):
            return message.role
        if "role" in message:
            return message["role"]
        return None

    # ------------------------------------------------------------------
    def display(self, message: types.Message) -> None:
        """
        Displays a message depending on its role.
        """
        role = self.role(message)

        match role:
            case "system":
                self.display_system(message)
            case "assistant":
                if message.content:
                    self.display_assistant(message)
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        self.display_tool_call(tool_call)
            case "user":
                self.display_user(message)
            case "tool":
                self.display_tool_call_output(message)
            case _:
                raise ValueError(f"Unknown message role: {role}")

    # ------------------------------------------------------------------
    @abc.abstractmethod
    def display_system(self, message: types.SystemMessage) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def display_user(self, message: types.UserMessage) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def display_assistant(self, message: types.AssistantMessage) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def display_tool_call(self, tool_call: types.ToolCall) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def display_tool_call_output(self, message: types.ToolCallOutput) -> None:
        raise NotImplementedError
