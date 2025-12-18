from pathlib import Path

# ---------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "chem_scout.db"

# ---------------------------------------------------------------------
# Rate-limit handling
# ---------------------------------------------------------------------
RATE_LIMIT_CHAT_DIR = DATA_DIR / "rate_limit_chats"
RATE_LIMIT_CHAT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------
# MCP Tool Server
# ---------------------------------------------------------------------
MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"

# Allowed tools per agent (database ops restricted to Data Agent)
ALLOWED_TOOLS_DATA = {
    "search_products_tool",
    "add_product_tool",
    "update_product_tool",
    "delete_product_tool",
    "get_order_status_tool",
    "list_open_orders_tool",
    "list_all_orders_tool",
    "monthly_spending_tool",
    "list_products_tool",
    "read_json_file_tool",
    "import_products_from_json_tool",
    "process_inventory_alert_tool",
    "get_audit_log_tool",
}

ALLOWED_TOOLS_ORDER = {
    "search_products_tool",
    "create_order_tool",
    "get_order_status_tool",
    "list_open_orders_tool",
    "notify_customer_tool",
    "request_inventory_revision_tool",
    "list_notifications_tool",
    "get_notification_tool",
    "get_audit_log_tool",
}

# ---------------------------------------------------------------------
# Notification & inventory handoff storage
# ---------------------------------------------------------------------
NOTIFICATIONS_DIR = DATA_DIR / "notifications"
NOTIFICATIONS_DIR.mkdir(exist_ok=True)

INVENTORY_ALERTS_DIR = DATA_DIR / "inventory_alerts"
INVENTORY_ALERTS_DIR.mkdir(exist_ok=True)
