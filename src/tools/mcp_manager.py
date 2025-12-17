# src/tools/mcp_manager.py

from chem_scout_ai.common.tools import ToolManager
from src.config import MCP_SERVER_URL, ALLOWED_TOOLS_DATA, ALLOWED_TOOLS_ORDER

# Separate tool managers per agent role
data_tool_manager = ToolManager.from_url(
    MCP_SERVER_URL,
    allowed_tools=ALLOWED_TOOLS_DATA,
)

order_tool_manager = ToolManager.from_url(
    MCP_SERVER_URL,
    allowed_tools=ALLOWED_TOOLS_ORDER,
)
