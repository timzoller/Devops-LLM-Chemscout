from pathlib import Path

# ---------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "chem_scout.db"

# ---------------------------------------------------------------------
# MCP Tool Server
# ---------------------------------------------------------------------
MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"

# Unified list of allowed MCP tools for both agents
ALL_ALLOWED_TOOLS = [
    "search_products_tool",
    "add_product_tool",
    "update_product_tool",
    "delete_product_tool",
    "create_order_tool",
    "get_order_status_tool",
    "list_open_orders_tool",
]
