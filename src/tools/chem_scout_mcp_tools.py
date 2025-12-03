"""MCP Tool Server for ChemScout AI (compatible with FastMCP and MCP 1.22.0)."""

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.database.db import (
    init_db,
    add_product,
    update_product,
    delete_product,
    search_products,
    create_order,
    get_order_status,
    list_open_orders,
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

# -----------------------------
# Server Start
# -----------------------------
if __name__ == "__main__":
    print("[MCP] ChemScout tool server running on streamable-http at /mcp")
    asyncio.run(SERVER.run("streamable-http", "/mcp"))
