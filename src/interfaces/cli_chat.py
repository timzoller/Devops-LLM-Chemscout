import asyncio
from typing import Literal

from chem_scout_ai.common import agent as agent_lib
from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types

from src.interfaces.rich_chat_display import RichChatDisplay
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def run_cli_chat(
    which: Literal["data", "order"],
    agent: agent_lib.Agent,
    chat: chat_lib.Chat,
):
    """
    Improved CLI chat using Rich-based UI.
    """

    display = RichChatDisplay()
    display.clear()

    display.console.print(f"\n[bold magenta]=== ChemScout AI – {which.capitalize()} Agent ===[/]")
    display.console.print("Press ENTER on empty input to stop the chat.\n")

    while True:
        # ---------- User input ----------
        try:
            user_input = input("You: ").strip()
        except KeyboardInterrupt:
            display.console.print("\nChat terminated by user.")
            break

        if not user_input:
            display.console.print("\nChat ended.")
            break

        # Add user message to chat & show it
        user_message = types.UserMessage(role="user", content=user_input)
        chat.append(user_message)
        display.display_user(user_message)

        logger.info(f"[{which}] User input: {user_input}")

        # ---------- Call agent ----------
        try:
            responses = await agent(chat=chat)
        except Exception as e:
            display.console.print(f"[red]Error: {e}[/]")
            logger.exception("Agent error.")
            continue

        # ---------- Display messages ----------
        for msg in responses:
            display.display(msg)

        display.console.rule()
