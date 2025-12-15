# src/agents/factory.py

from chem_scout_ai.common import agent as agent_lib
from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import types

from src.agents.prompts_order import ORDER_SYSTEM_PROMPT
from src.agents.prompts_data import DATA_SYSTEM_PROMPT

# Distinct tool managers per agent
from src.tools.mcp_manager import data_tool_manager, order_tool_manager


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
        tool_manager=data_tool_manager,
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
        tool_manager=order_tool_manager,
    )

    return {
        "data": (data_agent, data_chat),
        "order": (order_agent, order_chat),
    }
