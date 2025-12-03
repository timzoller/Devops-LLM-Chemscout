# src/agents/factory.py

from chem_scout_ai.common import agent as agent_lib
from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types

from src.agents.prompts_order import ORDER_SYSTEM_PROMPT
from src.agents.prompts_data import DATA_SYSTEM_PROMPT

# CORRECT: use the tool manager instance
from src.tools.mcp_manager import tool_manager


def build_agents(backend):

    # -----------------------
    # Data Agent
    # -----------------------
    data_chat = chat_lib.Chat(
        messages=[
            types.SystemMessage(
                role="system",
                content=DATA_SYSTEM_PROMPT
            )
        ]
    )

    data_agent = agent_lib.Agent(
        backend=backend,
        tool_manager=tool_manager,    # <<---- INSTANCE ✔
    )

    # -----------------------
    # Order Agent
    # -----------------------
    order_chat = chat_lib.Chat(
        messages=[
            types.SystemMessage(
                role="system",
                content=ORDER_SYSTEM_PROMPT
            )
        ]
    )

    order_agent = agent_lib.Agent(
        backend=backend,
        tool_manager=tool_manager,    # <<---- INSTANCE ✔
    )

    return {
        "data": (data_agent, data_chat),
        "order": (order_agent, order_chat),
    }
