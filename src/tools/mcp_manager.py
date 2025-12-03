# src/tools/mcp_manager.py

from chem_scout_ai.common.tools import ToolManager
from src.config import MCP_SERVER_URL, ALL_ALLOWED_TOOLS

tool_manager = ToolManager.from_url(
    MCP_SERVER_URL,
    allowed_tools=ALL_ALLOWED_TOOLS,
)
