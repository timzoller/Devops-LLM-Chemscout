"""
ChemScout AI – Unified Main Entry (Automatic Agent Routing)
"""

import asyncio
import threading
from dotenv import load_dotenv
load_dotenv()

import uvicorn

from src.utils.logger import get_logger
from src.tools.chem_scout_mcp_tools import SERVER
from chem_scout_ai.common.backend import Gemini2p5Flash, Gemini2p5FlashLite
from chem_scout_ai.common import types
from src.agents.router import classify_intent
from src.agents.factory import build_agents
from src.interfaces.rich_chat_display import RichChatDisplay

from src.database.db import init_db
from src.config import RATE_LIMIT_CHAT_DIR

logger = get_logger(__name__)


# ================================================================
# Start MCP server in background
# ================================================================
def _run_mcp():
    uvicorn.run(
        SERVER.streamable_http_app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )


def start_mcp_background():
    thread = threading.Thread(target=_run_mcp, daemon=True)
    thread.start()
    logger.info("MCP server started in background on http://127.0.0.1:8000/mcp")
    return thread


# ================================================================
# Cross-agent handoff helper
# ================================================================
HANDOFF_PREFIX = "HANDOFF:"


async def process_handoff(message, user_text: str, agents, display) -> bool:
    """
    Detects HANDOFF:<target>:<reason> messages and routes the request to
    the target agent. Returns True if a handoff was processed.
    """
    # Only assistant messages with string content can trigger a handoff
    if getattr(message, "role", None) != "assistant":
        return False

    content = getattr(message, "content", None)
    if not (isinstance(content, str) and content.startswith(HANDOFF_PREFIX)):
        return False

    try:
        _, target_raw, reason = content.split(":", 2)
    except ValueError:
        return False

    target = target_raw.strip().lower()
    if target not in agents:
        return False

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

    # Notify user in the display
    display.display_system(
        types.SystemMessage(
            role="system",
            content=f"Handing off to {target} agent: {reason}",
        )
    )

    # Invoke the target agent and display its outputs
    handoff_responses = await target_agent(chat=target_chat)
    for hmsg in handoff_responses:
        display.display(hmsg)

    return True


# ================================================================
# Main Chat Loop (Automatic Agent Routing)
# ================================================================
async def main():
    print("\n=== ChemScout AI – Unified Agent System ===\n")

    # Initialize DB
    init_db()
    logger.info("Database initialized.")
    # 1. Start MCP server
    start_mcp_background()
    await asyncio.sleep(1.2)

    # 2. Init backend
    backend = Gemini2p5Flash().get_async_backend(
        fallback_configs=[Gemini2p5FlashLite()],
        chat_store_dir=RATE_LIMIT_CHAT_DIR,
    )
    logger.info("Backend initialized.")

    # 3. Build both agents + query their system prompts
    agents = build_agents(backend)
    # agents = { "data": (agent, chat), "order": (agent, chat) }

    display = RichChatDisplay()

    print("ChemScout is ready. Type anything.\n")

    # ============================================================
    # MAIN INPUT LOOP
    # ============================================================
    while True:
        user_text = input("You: ").strip()
        if not user_text:
            print("Session ended.")
            break

        # 1) First classify intent using LLM
        intent = await classify_intent(user_text, backend)
        logger.info(f"Router selected agent: {intent}")

        agent, chat = agents[intent]

        # Append user message to this agent's chat only
        chat.append(types.UserMessage(role="user", content=user_text))

        # Show user message
        display.display_user(types.UserMessage(role="user", content=user_text))

        # 2) Call appropriate agent
        try:
            responses = await agent(chat=chat)
        except Exception as e:
            logger.exception("Agent error")
            print(f"[ERROR] Agent failed: {e}")
            continue

        # 3) Display all messages from the agent, with handoff detection
        for msg in responses:
            handed_off = await process_handoff(msg, user_text, agents, display)
            if handed_off:
                continue
            display.display(msg)


# ================================================================
# ENTRY POINT
# ================================================================
if __name__ == "__main__":
    asyncio.run(main())
