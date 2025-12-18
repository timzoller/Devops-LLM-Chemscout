from src.database.db import (
    # Connection management
    get_connection,
    init_db,
    
    # Agent context for audit logging
    set_agent_context,
    get_agent_context,
    
    # Product operations
    add_product,
    update_product,
    delete_product,
    search_products,
    list_all_products,
    get_product,
    reduce_product_quantity,
    
    # Order operations
    create_order,
    get_order_status,
    list_open_orders,
    list_all_orders,
    calculate_monthly_spending,
    
    # Audit logging
    log_audit,
    get_audit_log,
    
    # Inventory alert tracking
    is_inventory_alert_processed,
    mark_inventory_alert_processed,
    get_processed_inventory_alerts,
)

__all__ = [
    "get_connection",
    "init_db",
    "set_agent_context",
    "get_agent_context",
    "add_product",
    "update_product",
    "delete_product",
    "search_products",
    "list_all_products",
    "get_product",
    "reduce_product_quantity",
    "create_order",
    "get_order_status",
    "list_open_orders",
    "list_all_orders",
    "calculate_monthly_spending",
    "log_audit",
    "get_audit_log",
    "is_inventory_alert_processed",
    "mark_inventory_alert_processed",
    "get_processed_inventory_alerts",
]

