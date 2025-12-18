from rich.console import Console
from rich.panel import Panel

class RichChatDisplay:
    def __init__(self):
        self.console = Console()

    # -------------------------
    # Safe extractors
    # -------------------------
    @staticmethod
    def get_role(message):
        if hasattr(message, "role"):
            return message.role
        if isinstance(message, dict):
            return message.get("role", "assistant")
        return "assistant"

    @staticmethod
    def get_content(message):
        if hasattr(message, "content"):
            return message.content
        if isinstance(message, dict):
            return message.get("content", "")
        return ""

    def clear(self):
        self.console.clear()

    # -------------------------
    # Central Display Router
    # -------------------------
    def display(self, message):
        role = self.get_role(message)

        if role == "assistant":
            self.display_assistant(message)
        elif role == "user":
            self.display_user(message)
        elif role == "system":
            self.display_system(message)
        elif role == "tool":
            self.display_tool_call_output(message)
        else:
            self.console.print(f"[red]Unknown message role: {role}[/]")

    # -------------------------
    # Display Methods
    # -------------------------
    def _render_safe(self, content):
        """Ensure rich always receives a valid string."""
        if content is None:
            return ""
        if isinstance(content, (str, int, float)):
            return str(content)
        return str(content)

    def display_user(self, message):
        content = self._render_safe(self.get_content(message))
        self.console.print(
            Panel(content, title="YOU", style="bold blue")
        )

    def display_assistant(self, message):
        content = self._render_safe(self.get_content(message))
        self.console.print(
            Panel(content, title="ASSISTANT", style="bold green")
        )

    def display_system(self, message):
        content = self._render_safe(self.get_content(message))
        self.console.print(
            Panel(content, title="SYSTEM", style="bold yellow")
        )

    def display_tool_call_output(self, message):
        content = self._render_safe(self.get_content(message))
        self.console.print(
            Panel(content, title="TOOL OUTPUT", style="bold magenta")
        )
