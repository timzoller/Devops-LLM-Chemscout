"""MCP Tool Server for ChemScout AI (compatible with FastMCP and MCP 1.22.0)."""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.config import (
    INVENTORY_ALERTS_DIR,
    NOTIFICATIONS_DIR,
    BASE_DIR,
    DATA_DIR,
)
from src.database.db import (
    init_db,
    add_product,
    update_product,
    delete_product,
    search_products,
    create_order,
    get_order_status,
    list_open_orders,
    list_all_orders,
    calculate_monthly_spending,
    reduce_product_quantity,
    get_product,
    log_audit,
    set_agent_context,
    is_inventory_alert_processed,
    mark_inventory_alert_processed,
    get_audit_log,
)

# -----------------------------
# FastMCP server instance
# -----------------------------
SERVER = FastMCP()   # HTTP-basiert, kein WebSocket!


# -----------------------------
# Database Init
# -----------------------------
@SERVER.tool()
def init_database() -> str:
    """Initialisiert die ChemScout-Datenbank."""
    init_db()
    return "Database initialized."


# -----------------------------
# Product Tools
# -----------------------------
@SERVER.tool()
def add_product_tool(
    name: str,
    cas_number: str | None = None,
    supplier: str | None = None,
    purity: str | None = None,
    package_size: str | None = None,
    price: float | None = None,
    currency: str = "CHF",
    delivery_time_days: int | None = None,
    available_quantity: float | None = None,
    available_unit: str = "g",
    agent_name: str = "data_agent",
) -> dict:
    """Fügt ein neues Produkt in die Datenbank ein."""
    set_agent_context(agent_name)
    
    product_id = add_product(
        name=name,
        cas_number=cas_number,
        supplier=supplier,
        purity=purity,
        package_size=package_size,
        price=price,
        currency=currency,
        delivery_time_days=delivery_time_days,
        available_quantity=available_quantity,
        available_unit=available_unit,
    )
    
    # Log the action
    log_audit(
        action="INSERT",
        table_name="products",
        record_id=product_id,
        new_values={
            "name": name,
            "cas_number": cas_number,
            "supplier": supplier,
            "purity": purity,
            "package_size": package_size,
            "price": price,
            "currency": currency,
            "delivery_time_days": delivery_time_days,
            "available_quantity": available_quantity,
            "available_unit": available_unit,
        },
        agent_name=agent_name,
    )
    
    return {"status": "ok", "product_id": product_id}


@SERVER.tool()
def update_product_tool(
    product_id: int,
    name: str | None = None,
    cas_number: str | None = None,
    supplier: str | None = None,
    purity: str | None = None,
    package_size: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    delivery_time_days: int | None = None,
    available_quantity: float | None = None,
    available_unit: str | None = None,
    agent_name: str = "data_agent",
) -> dict:
    """Aktualisiert ein Produkt."""
    set_agent_context(agent_name)
    
    # Get old values before update
    old_product = get_product(product_id)
    
    success = update_product(
        product_id=product_id,
        name=name,
        cas_number=cas_number,
        supplier=supplier,
        purity=purity,
        package_size=package_size,
        price=price,
        currency=currency,
        delivery_time_days=delivery_time_days,
        available_quantity=available_quantity,
        available_unit=available_unit,
    )
    
    if success:
        # Build new_values dict with only changed fields
        new_values = {}
        if name is not None:
            new_values["name"] = name
        if cas_number is not None:
            new_values["cas_number"] = cas_number
        if supplier is not None:
            new_values["supplier"] = supplier
        if purity is not None:
            new_values["purity"] = purity
        if package_size is not None:
            new_values["package_size"] = package_size
        if price is not None:
            new_values["price"] = price
        if currency is not None:
            new_values["currency"] = currency
        if delivery_time_days is not None:
            new_values["delivery_time_days"] = delivery_time_days
        if available_quantity is not None:
            new_values["available_quantity"] = available_quantity
        if available_unit is not None:
            new_values["available_unit"] = available_unit
        
        log_audit(
            action="UPDATE",
            table_name="products",
            record_id=product_id,
            old_values=old_product,
            new_values=new_values,
            agent_name=agent_name,
        )
    
    return {"status": "ok" if success else "not_found"}


@SERVER.tool()
def delete_product_tool(product_id: int, agent_name: str = "data_agent") -> dict:
    """Löscht ein Produkt."""
    set_agent_context(agent_name)
    
    # Get product info before deletion for audit
    old_product = get_product(product_id)
    
    success = delete_product(product_id)
    
    if success:
        log_audit(
            action="DELETE",
            table_name="products",
            record_id=product_id,
            old_values=old_product,
            agent_name=agent_name,
        )
    
    return {"status": "ok" if success else "not_found"}


@SERVER.tool()
def search_products_tool(
    query: str | None = None,
    cas_number: str | None = None,
    supplier: str | None = None,
    max_price: float | None = None,
) -> dict:
    """
    Durchsucht die Produktdatenbank.

    Gibt IMMER ein Objekt mit 'results' zurück.
    """
    results = search_products(
        query=query,
        cas_number=cas_number,
        supplier=supplier,
        max_price=max_price,
    )
    return {"results": results}


@SERVER.tool()
def list_products_tool() -> list[dict]:
    """Listet alle Produkte in der Datenbank."""
    from src.database.db import list_all_products
    return list_all_products()


# -----------------------------
# JSON → Product import helpers
# -----------------------------

JSON_SEARCH_ROOTS: list[Path] = [
    DATA_DIR,
    BASE_DIR / "src" / "database",
]


def _resolve_json_path(relative_or_absolute_path: str) -> Path:
    """
    Resolves a JSON path for the import tools.

    - If an absolute path is given and exists, we use it.
    - Otherwise we search relative to known roots (data/, src/database/).
    """
    p = Path(relative_or_absolute_path)
    if p.is_absolute():
        if not p.exists():
            raise FileNotFoundError(f"JSON file not found at {p}")
        return p

    # Try roots in order
    for root in JSON_SEARCH_ROOTS:
        candidate = root / p
        if candidate.exists():
            return candidate

    # Fallback to path relative to BASE_DIR
    candidate = BASE_DIR / relative_or_absolute_path
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"JSON file '{relative_or_absolute_path}' not found in any search root."
    )


def _normalise_price(value: Any) -> float | None:
    """
    Convert various price formats into a single float if possible.
    Examples:
      - 45.2
      - "12$/100g"
      - "CHF 20 - 55"
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    # Extract the first number or range "x-y"
    cleaned = re.sub(r"[^\d\.\-]", "", value)
    if "-" in cleaned:
        parts = [p for p in cleaned.split("-") if p]
        if len(parts) == 2:
            try:
                low, high = map(float, parts)
                return (low + high) / 2.0
            except Exception:
                return None

    match = re.search(r"\d+(\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _maybe_str_list_to_str(value: Any) -> str | None:
    """Turn a list of strings into a comma-separated string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(v) for v in value if isinstance(v, (str, int, float))]
        return ", ".join(parts) if parts else None
    return str(value)


def _extract_products_from_json(obj: Any) -> list[dict]:
    """
    Recursively walk an arbitrary JSON structure and extract
    product-like entries (name/compound + CAS and optional fields).
    """
    products: list[dict] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            # Heuristic: candidates that look like product entries
            keys = {k.lower() for k in node.keys()}
            has_name_like = any(k in keys for k in ("name", "compound"))
            has_cas_like = any(
                k in keys for k in ("cas", "cas_number", "cas-number", "cas number")
            )

            if has_name_like or has_cas_like:
                name = node.get("name") or node.get("compound")
                cas = (
                    node.get("CAS")
                    or node.get("cas")
                    or node.get("CAS-Number")
                    or node.get("cas_number")
                    or node.get("CAS number")
                )
                supplier = node.get("supplier")
                supplier = _maybe_str_list_to_str(supplier)

                # Price variants
                price_raw = (
                    node.get("price")
                    or node.get("price_usd")
                    or node.get("price_per_kg")
                    or node.get("price_estimate")
                )
                price = _normalise_price(price_raw)

                product = {
                    "name": str(name) if name is not None else None,
                    "cas_number": str(cas) if cas is not None else None,
                    "supplier": supplier,
                    "purity": node.get("purity"),
                    "package_size": node.get("package_size"),
                    "price": price,
                    "currency": "CHF",  # normalise to single currency for now
                }

                # only keep entries that at least have a name or CAS
                if product["name"] or product["cas_number"]:
                    products.append(product)

            # Recurse into children
            for v in node.values():
                visit(v)

        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    return products


@SERVER.tool()
def read_json_file_tool(path: str) -> dict:
    """
    Reads a JSON file from disk and returns its parsed content.

    The path can be absolute or relative to:
      - data/
      - src/database/
      - the project root.
    """
    resolved = _resolve_json_path(path)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "path": str(resolved),
        "content": data,
    }


@SERVER.tool()
def import_products_from_json_tool(path: str) -> dict:
    """
    Parses a (possibly messy) JSON file and inserts detected products
    into the `products` table.

    Heuristics:
      - Detects product-like objects containing fields such as
        name / compound, CAS / cas / CAS-Number, supplier, price.
      - Normalises diverse price formats into a single float.
    """
    resolved = _resolve_json_path(path)
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    products = _extract_products_from_json(raw)

    inserted_ids: list[int] = []
    for p in products:
        if not p.get("name") and not p.get("cas_number"):
            continue

        product_id = add_product(
            name=p.get("name") or (p.get("cas_number") or "Unnamed product"),
            cas_number=p.get("cas_number"),
            supplier=p.get("supplier"),
            purity=p.get("purity"),
            package_size=p.get("package_size"),
            price=p.get("price"),
            currency=p.get("currency") or "CHF",
            delivery_time_days=None,
        )
        inserted_ids.append(product_id)

    return {
        "status": "ok",
        "path": str(resolved),
        "detected_products": len(products),
        "inserted_products": len(inserted_ids),
        "product_ids": inserted_ids,
    }


# -----------------------------
# Order Tools
# -----------------------------
@SERVER.tool()
def create_order_tool(
    product_id: int,
    quantity: float,
    unit: str = "g",
    customer_reference: str | None = None,
    name: str | None = None,
    supplier: str | None = None,
    purity: str | None = None,
    package_size: str | None = None,
    price_range: str | None = None,
    agent_name: str = "order_agent",
) -> dict:
    """
    Creates an order. Accepts product_id=0 for external items.
    
    IMPORTANT: This tool does NOT modify inventory directly.
    After creating an order, the Order Agent MUST call request_inventory_revision_tool
    to notify the Data Agent, who will then process the inventory update via
    process_inventory_alert_tool.
    
    Workflow:
    1. Order Agent calls create_order_tool (creates order, NO inventory change)
    2. Order Agent calls request_inventory_revision_tool (creates alert file)
    3. Data Agent calls process_inventory_alert_tool (updates inventory)
    """
    set_agent_context(agent_name)

    if product_id == 0:
        # EXTERNAL ORDER - no inventory to track
        order = create_order(
            product_id=0,
            quantity=quantity,
            unit=unit,
            customer_reference=customer_reference,
            external_name=name,
            external_supplier=supplier,
            external_purity=purity,
            external_package_size=package_size,
            external_price_range=price_range,
            auto_reduce_inventory=False,  # Never auto-reduce for external
        )
        order["external"] = True
        
        # Log external order
        log_audit(
            action="INSERT",
            table_name="orders",
            record_id=order["order_id"],
            new_values={
                "product_id": 0,
                "quantity": quantity,
                "unit": unit,
                "customer_reference": customer_reference,
                "external_name": name,
                "external_supplier": supplier,
                "external_purity": purity,
                "external_package_size": package_size,
                "external_price_range": price_range,
            },
            details="External order (product not in database)",
            agent_name=agent_name,
        )
        return order

    # INTERNAL ORDER - inventory handled by Data Agent via inventory alert
    order = create_order(
        product_id=product_id,
        quantity=quantity,
        unit=unit,
        customer_reference=customer_reference,
        auto_reduce_inventory=False,  # DO NOT auto-reduce - Data Agent handles this
    )
    order["external"] = False
    order["inventory_note"] = "IMPORTANT: Call request_inventory_revision_tool to notify Data Agent for inventory update"
    
    # Log internal order (inventory NOT modified here)
    log_audit(
        action="INSERT",
        table_name="orders",
        record_id=order["order_id"],
        new_values={
            "product_id": product_id,
            "quantity": quantity,
            "unit": unit,
            "customer_reference": customer_reference,
        },
        details="Internal order created (inventory pending - Data Agent will process via inventory alert)",
        agent_name=agent_name,
    )
    
    return order

@SERVER.tool()
def get_order_status_tool(order_id: str) -> dict:
    """Gibt den Status einer Bestellung zurück."""
    order = get_order_status(order_id)
    if order is None:
        return {"status": "not_found"}
    return {"status": "ok", "order": order}


@SERVER.tool()
def list_open_orders_tool() -> list[dict]:
    """Listet alle offenen Bestellungen."""
    return list_open_orders()


@SERVER.tool()
def list_all_orders_tool(
    status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "DESC",
    limit: int | None = None,
) -> list[dict]:
    """
    Lists all orders with optional filtering and sorting.
    
    Use this tool to display orders to the user, especially when they want to see:
    - All orders (not just open ones)
    - Latest/newest orders (sort_order='DESC')
    - Oldest orders first (sort_order='ASC')
    - A specific number of recent orders (use limit parameter)
    
    Args:
        status: Filter by status ('OPEN', 'COMPLETED', 'CANCELLED'). None for all statuses.
        sort_by: Column to sort by. Options: 'created_at' (default), 'order_id', 'quantity', 'status'.
        sort_order: 'DESC' for newest first (default), 'ASC' for oldest first.
        limit: Maximum number of orders to return. None for all orders.
    
    Returns:
        List of order dictionaries with all order details.
    
    Examples:
        - Show latest 5 orders: list_all_orders_tool(limit=5)
        - Show all completed orders: list_all_orders_tool(status='COMPLETED')
        - Show oldest orders first: list_all_orders_tool(sort_order='ASC')
    """
    return list_all_orders(
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )


@SERVER.tool()
def monthly_spending_tool(year: int, month: int) -> dict:
    """
    Returns aggregated chemical spending for a given month.
    """
    return calculate_monthly_spending(year, month)


# -----------------------------
# Customer notification helpers
# -----------------------------
def _write_text_file(path, lines: list[str]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@SERVER.tool()
def notify_customer_tool(
    order_id: str,
    message: str,
    customer_email: str | None = None,
    customer_name: str | None = None,
) -> dict:
    """
    Sends a fake confirmation email if an address is provided,
    otherwise writes a confirmation text file for traceability.
    """
    timestamp = datetime.utcnow().isoformat()
    mode = "email" if customer_email else "file"

    filename = f"{mode}_{order_id}.txt"
    target = NOTIFICATIONS_DIR / filename

    lines = [
        f"timestamp: {timestamp}",
        f"order_id: {order_id}",
        f"mode: {mode}",
        f"customer_email: {customer_email or 'not provided'}",
        f"customer_name: {customer_name or 'not provided'}",
        "",
        "message:",
        message or "Your order has been recorded. Thank you.",
    ]

    path = _write_text_file(target, lines)
    return {
        "status": "ok",
        "method": mode,
        "path": path,
    }


# -----------------------------
# Inventory handoff for Data Agent
# -----------------------------
@SERVER.tool()
def request_inventory_revision_tool(
    order_id: str,
    product_id: int | None = None,
    ordered_quantity: float | None = None,
    unit: str = "g",
    note: str | None = None,
) -> dict:
    """
    Logs a request for the Data Agent to revise remaining inventory after a reorder.
    Note: For internal orders (product_id > 0), inventory is automatically reduced when the order is created.
    This tool is mainly for tracking and external orders.
    """
    timestamp = datetime.utcnow().isoformat()
    filename = f"inventory_{order_id}.txt"
    target = INVENTORY_ALERTS_DIR / filename

    lines = [
        f"timestamp: {timestamp}",
        f"order_id: {order_id}",
        f"product_id: {product_id if product_id is not None else 'unknown'}",
        f"ordered_quantity: {ordered_quantity if ordered_quantity is not None else 'unspecified'} {unit}",
        f"note: {note or 'please revise remaining quantity in the database'}",
    ]

    path = _write_text_file(target, lines)
    return {
        "status": "ok",
        "path": path,
    }


@SERVER.tool()
def process_inventory_alert_tool(order_id: str, agent_name: str = "data_agent") -> dict:
    """
    Processes an inventory alert file and automatically reduces available quantity for internal orders.
    This tool reads the inventory alert file created by request_inventory_revision_tool and
    updates the product's available_quantity if it's an internal order (product_id > 0).
    
    IMPORTANT: This tool tracks processed alerts to prevent duplicate processing.
    If an alert has already been processed, it will return status "already_processed".
    
    Returns status and details about what was processed.
    """
    set_agent_context(agent_name)
    
    # Check if this alert was already processed
    if is_inventory_alert_processed(order_id):
        return {
            "status": "already_processed",
            "message": f"Inventory alert for order {order_id} has already been processed. No action taken to prevent duplicate inventory reduction.",
            "order_id": order_id,
        }
    
    filename = f"inventory_{order_id}.txt"
    alert_file = INVENTORY_ALERTS_DIR / filename
    
    if not alert_file.exists():
        return {
            "status": "not_found",
            "message": f"Inventory alert file not found for order {order_id}",
        }
    
    # Parse the alert file
    lines = alert_file.read_text(encoding="utf-8").strip().split("\n")
    alert_data = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            alert_data[key.strip()] = value.strip()
    
    product_id_str = alert_data.get("product_id", "unknown")
    if product_id_str == "unknown" or not product_id_str.isdigit():
        # Mark as processed with skip status
        mark_inventory_alert_processed(
            order_id=order_id,
            result="skipped",
            details="Invalid or missing product_id",
            processed_by=agent_name,
        )
        return {
            "status": "skipped",
            "message": f"Invalid or missing product_id in alert file for order {order_id}",
        }
    
    product_id = int(product_id_str)
    
    # Only process internal orders (product_id > 0)
    if product_id == 0:
        mark_inventory_alert_processed(
            order_id=order_id,
            result="skipped",
            details="External order (product_id=0)",
            processed_by=agent_name,
        )
        return {
            "status": "skipped",
            "message": f"Order {order_id} is an external order (product_id=0), no inventory to update",
        }
    
    # Get ordered quantity
    ordered_qty_str = alert_data.get("ordered_quantity", "")
    if not ordered_qty_str or ordered_qty_str == "unspecified":
        mark_inventory_alert_processed(
            order_id=order_id,
            result="error",
            details="Ordered quantity not specified",
            processed_by=agent_name,
        )
        return {
            "status": "error",
            "message": f"Ordered quantity not specified in alert file for order {order_id}",
        }
    
    # Parse quantity and unit from string like "2.0 g" or "100.5 kg"
    parts = ordered_qty_str.split()
    if len(parts) < 2:
        mark_inventory_alert_processed(
            order_id=order_id,
            result="error",
            details=f"Could not parse quantity from '{ordered_qty_str}'",
            processed_by=agent_name,
        )
        return {
            "status": "error",
            "message": f"Could not parse quantity and unit from '{ordered_qty_str}'",
        }
    
    try:
        quantity = float(parts[0])
        unit = " ".join(parts[1:])
    except ValueError:
        mark_inventory_alert_processed(
            order_id=order_id,
            result="error",
            details=f"Could not parse quantity '{parts[0]}' as number",
            processed_by=agent_name,
        )
        return {
            "status": "error",
            "message": f"Could not parse quantity '{parts[0]}' as a number",
        }
    
    # Get current product info
    product = get_product(product_id)
    if product is None:
        mark_inventory_alert_processed(
            order_id=order_id,
            result="error",
            details=f"Product {product_id} not found",
            processed_by=agent_name,
        )
        return {
            "status": "error",
            "message": f"Product {product_id} not found in database",
        }
    
    # Reduce quantity
    success = reduce_product_quantity(product_id, quantity, unit)
    
    if success:
        # Get updated product info
        updated_product = get_product(product_id)
        
        # Log the inventory change
        log_audit(
            action="UPDATE",
            table_name="products",
            record_id=product_id,
            old_values={"available_quantity": product.get("available_quantity")},
            new_values={"available_quantity": updated_product.get("available_quantity") if updated_product else None},
            details=f"Inventory reduced via alert for order {order_id}",
            agent_name=agent_name,
        )
        
        # Mark as processed
        mark_inventory_alert_processed(
            order_id=order_id,
            result="ok",
            details=f"Reduced product {product_id} by {quantity} {unit}",
            processed_by=agent_name,
        )
        
        return {
            "status": "ok",
            "message": f"Successfully reduced available quantity for product {product_id}",
            "product_id": product_id,
            "reduced_quantity": quantity,
            "unit": unit,
            "previous_quantity": product.get("available_quantity"),
            "new_quantity": updated_product.get("available_quantity") if updated_product else None,
        }
    else:
        mark_inventory_alert_processed(
            order_id=order_id,
            result="warning",
            details=f"Could not reduce quantity (units mismatch or NULL)",
            processed_by=agent_name,
        )
        return {
            "status": "warning",
            "message": f"Could not reduce quantity (possibly units don't match or quantity was NULL)",
            "product_id": product_id,
            "current_quantity": product.get("available_quantity"),
            "current_unit": product.get("available_unit"),
            "requested_quantity": quantity,
            "requested_unit": unit,
        }

# -----------------------------
# Notification Display Tools
# -----------------------------
@SERVER.tool()
def list_notifications_tool(
    limit: int = 20,
    order_id: str | None = None,
) -> dict:
    """
    Lists all customer notifications that have been sent.
    
    Args:
        limit: Maximum number of notifications to return (default 20)
        order_id: Filter by specific order ID (optional)
    
    Returns:
        List of notification summaries with timestamps and order IDs.
    """
    notifications = []
    
    if not NOTIFICATIONS_DIR.exists():
        return {"status": "ok", "notifications": [], "total": 0}
    
    # Get all notification files
    files = list(NOTIFICATIONS_DIR.glob("*.txt"))
    
    # Sort by modification time (newest first)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    for file_path in files[:limit * 2]:  # Read more to filter if needed
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            
            # Parse notification data
            notification_data = {"filename": file_path.name}
            message_lines = []
            in_message = False
            
            for line in lines:
                if in_message:
                    message_lines.append(line)
                elif line.startswith("message:"):
                    in_message = True
                elif ":" in line:
                    key, value = line.split(":", 1)
                    notification_data[key.strip()] = value.strip()
            
            notification_data["message"] = "\n".join(message_lines).strip()
            
            # Filter by order_id if specified
            if order_id and notification_data.get("order_id") != order_id:
                continue
            
            notifications.append(notification_data)
            
            if len(notifications) >= limit:
                break
                
        except Exception as e:
            continue  # Skip files that can't be parsed
    
    return {
        "status": "ok",
        "notifications": notifications,
        "total": len(notifications),
    }


@SERVER.tool()
def get_notification_tool(order_id: str) -> dict:
    """
    Gets the full notification details for a specific order.
    
    Args:
        order_id: The order ID to look up notifications for
    
    Returns:
        Full notification content including message body.
    """
    # Check for email notification first, then file notification
    for prefix in ["email", "file"]:
        filename = f"{prefix}_{order_id}.txt"
        file_path = NOTIFICATIONS_DIR / filename
        
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.strip().split("\n")
                
                # Parse notification data
                notification_data = {
                    "filename": filename,
                    "notification_type": prefix,
                }
                message_lines = []
                in_message = False
                
                for line in lines:
                    if in_message:
                        message_lines.append(line)
                    elif line.startswith("message:"):
                        in_message = True
                    elif ":" in line:
                        key, value = line.split(":", 1)
                        notification_data[key.strip()] = value.strip()
                
                notification_data["message"] = "\n".join(message_lines).strip()
                
                return {
                    "status": "ok",
                    "notification": notification_data,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Error reading notification file: {str(e)}",
                }
    
    return {
        "status": "not_found",
        "message": f"No notification found for order {order_id}",
    }


# -----------------------------
# Audit Log Tools
# -----------------------------
@SERVER.tool()
def get_audit_log_tool(
    limit: int = 50,
    table_name: str | None = None,
    agent_name: str | None = None,
    action: str | None = None,
) -> dict:
    """
    Retrieves the database audit log showing all changes made by agents.
    
    Args:
        limit: Maximum number of entries to return (default 50)
        table_name: Filter by table name ('products', 'orders')
        agent_name: Filter by agent name ('data_agent', 'order_agent', 'user')
        action: Filter by action type ('INSERT', 'UPDATE', 'DELETE')
    
    Returns:
        List of audit log entries showing who changed what and when.
    """
    entries = get_audit_log(
        limit=limit,
        table_name=table_name,
        agent_name=agent_name,
        action=action,
    )
    
    return {
        "status": "ok",
        "entries": entries,
        "total": len(entries),
    }


# -----------------------------
# Server Start
# -----------------------------
if __name__ == "__main__":
    print("[MCP] ChemScout tool server running on streamable-http at /mcp")
    asyncio.run(SERVER.run("streamable-http", "/mcp"))
