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
    calculate_monthly_spending,
    reduce_product_quantity,
    get_product,
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
) -> dict:
    """Fügt ein neues Produkt in die Datenbank ein."""
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
) -> dict:
    """Aktualisiert ein Produkt."""
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
    return {"status": "ok" if success else "not_found"}


@SERVER.tool()
def delete_product_tool(product_id: int) -> dict:
    """Löscht ein Produkt."""
    success = delete_product(product_id)
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
) -> dict:
    """
    Creates an order. Accepts product_id=0 for external items.
    """

    if product_id == 0:
        # EXTERNAL ORDER
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
        )
        order["external"] = True
        return order

    # INTERNAL ORDER
    order = create_order(
        product_id=product_id,
        quantity=quantity,
        unit=unit,
        customer_reference=customer_reference,
    )
    order["external"] = False
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

# -----------------------------
# Server Start
# -----------------------------
if __name__ == "__main__":
    print("[MCP] ChemScout tool server running on streamable-http at /mcp")
    asyncio.run(SERVER.run("streamable-http", "/mcp"))
