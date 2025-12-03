from chem_scout_ai.common import agent as agent_lib
from chem_scout_ai.common import backend as backend_lib
from chem_scout_ai.common import chat as chat_lib
from chem_scout_ai.common import tools as tools_lib
from chem_scout_ai.common import types

from src.config import MCP_SERVER_URL, DATA_GATHERING_ALLOWED_TOOLS


def create_data_gathering_agent(
    backend: backend_lib.AsyncLLMBackend,
) -> tuple[agent_lib.Agent, chat_lib.Chat]:
    """
    Constructs the ChemScout Data-Gathering Agent.
    """

    tool_manager = tools_lib.ToolManager.from_url(
        MCP_SERVER_URL,
        allowed_tools=DATA_GATHERING_ALLOWED_TOOLS,
    )

    system_prompt = (
        """You are the ChemScout Data-Gathering Agent.

Your responsibilities:

1. Understand the user's request and determine whether it is:
   a) a database operation (search, add, update, delete), or
   b) a market information request (prices, suppliers, availability).

2. For market-information requests:
   - Do NOT call any database tools.
   - Use internal knowledge about typical prices and suppliers.
   - Provide:
       • common suppliers
       • typical price ranges (realistic ranges)
       • typical purity and package sizes
       • typical delivery times
   - You MAY compare, rank, or identify the cheapest / most expensive supplier
     based on these typical price ranges.
   - Never claim to have real-time data; phrase it as “typical market ranges”.

3. If the user wants to add or update a product in the database:
      → Extract structured fields:
           - product name
           - CAS number
           - purity
           - package size
           - supplier
           - price + currency
           - delivery time (days)

      → FIRST call search_products_tool to check whether a matching product exists.

      If a match exists:
           → call update_product_tool using only changed fields.

      If no match exists:
           → call add_product_tool with all extracted fields.

4. If essential database fields (e.g., CAS number) are missing:
      → Ask the user only when needed for a DB operation.

5. After tool calls, summarise results clearly for the user.

6. Never respond “None”. Always return helpful, structured text."""
    )

    chat = chat_lib.Chat(
        messages=[types.SystemMessage(role="system", content=system_prompt)],
    )

    agent = agent_lib.Agent(backend=backend, tool_manager=tool_manager)
    return agent, chat
