import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src.config import DB_PATH


@contextmanager
def get_connection():
    """Contextmanager für eine SQLite-Verbindung."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def init_db() -> None:
    """Initialisiert die Datenbanktabellen, falls sie nicht existieren."""
    with get_connection() as conn:
        cur = conn.cursor()

        # -------------------------
        # PRODUCTS TABLE
        # -------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cas_number TEXT,
                supplier TEXT,
                purity TEXT,
                package_size TEXT,
                price REAL,
                currency TEXT DEFAULT 'CHF',
                delivery_time_days INTEGER,
                last_updated TEXT
            )
            """
        )

        # -------------------------
        # ORDERS TABLE (FIXED)
        # -------------------------
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                product_id INTEGER DEFAULT 0,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT 'g',
                status TEXT NOT NULL DEFAULT 'OPEN',
                customer_reference TEXT,

                -- Metadata for external orders:
                external_name TEXT,
                external_supplier TEXT,
                external_purity TEXT,
                external_package_size TEXT,
                external_price_range TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def add_product(
    name: str,
    cas_number: str | None = None,
    supplier: str | None = None,
    purity: str | None = None,
    package_size: str | None = None,
    price: float | None = None,
    currency: str = "CHF",
    delivery_time_days: int | None = None,
) -> int:
    """Fügt ein Produkt hinzu und gibt die ID zurück."""
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO products (
                name, cas_number, supplier, purity, package_size,
                price, currency, delivery_time_days, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                cas_number,
                supplier,
                purity,
                package_size,
                price,
                currency,
                delivery_time_days,
                now,
            ),
        )
        return cur.lastrowid


def update_product(
    product_id: int,
    name: str | None = None,
    cas_number: str | None = None,
    supplier: str | None = None,
    purity: str | None = None,
    package_size: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    delivery_time_days: int | None = None,
) -> bool:
    """Aktualisiert ein Produkt. Gibt True zurück, wenn ein Datensatz betroffen war."""
    fields = []
    values: list[object] = []

    mapping = {
        "name": name,
        "cas_number": cas_number,
        "supplier": supplier,
        "purity": purity,
        "package_size": package_size,
        "price": price,
        "currency": currency,
        "delivery_time_days": delivery_time_days,
    }
    for col, val in mapping.items():
        if val is not None:
            fields.append(f"{col} = ?")
            values.append(val)

    if not fields:
        return False

    fields.append("last_updated = ?")
    values.append(datetime.utcnow().isoformat())
    values.append(product_id)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE products SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        return cur.rowcount > 0


def delete_product(product_id: int) -> bool:
    """Löscht ein Produkt. Gibt True zurück, wenn etwas gelöscht wurde."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cur.rowcount > 0


def search_products(
    query: str | None = None,
    cas_number: str | None = None,
    supplier: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """Einfacher Produktsuch-Helper."""
    sql = "SELECT id, name, cas_number, supplier, purity, package_size, price, currency, delivery_time_days FROM products WHERE 1=1"
    params: list[object] = []

    if query:
        sql += " AND name LIKE ?"
        params.append(f"%{query}%")
    if cas_number:
        sql += " AND cas_number = ?"
        params.append(cas_number)
    if supplier:
        sql += " AND supplier = ?"
        params.append(supplier)
    if max_price is not None:
        sql += " AND price <= ?"
        params.append(max_price)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

    products: list[dict] = []
    for row in rows:
        (
            pid,
            name,
            cas,
            sup,
            purity,
            package_size,
            price,
            currency,
            delivery_time_days,
        ) = row
        products.append(
            {
                "id": pid,
                "name": name,
                "cas_number": cas,
                "supplier": sup,
                "purity": purity,
                "package_size": package_size,
                "price": price,
                "currency": currency,
                "delivery_time_days": delivery_time_days,
            }
        )
    return products


def create_order(
    product_id: int,
    quantity: float,
    unit: str,
    customer_reference: str | None = None,
    external_name: str | None = None,
    external_supplier: str | None = None,
    external_purity: str | None = None,
    external_package_size: str | None = None,
    external_price_range: str | None = None,
) -> dict:
    """Erstellt interne oder externe Orders."""
    from uuid import uuid4

    order_id = f"ORD-{uuid4().hex[:8].upper()}"
    now = datetime.utcnow().isoformat()
    status = "OPEN"

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                order_id, product_id, quantity, unit, status,
                customer_reference,
                external_name, external_supplier, external_purity,
                external_package_size, external_price_range,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                product_id,
                quantity,
                unit,
                status,
                customer_reference,
                external_name,
                external_supplier,
                external_purity,
                external_package_size,
                external_price_range,
                now,
            ),
        )

    return {
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit": unit,
        "status": status,
        "customer_reference": customer_reference,
        "external_name": external_name,
        "external_supplier": external_supplier,
        "external_purity": external_purity,
        "external_package_size": external_package_size,
        "external_price_range": external_price_range,
        "created_at": now,
    }


def get_order_status(order_id: str) -> dict | None:
    """Liest den Status einer Order."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT order_id, product_id, quantity, unit, status,
                   customer_reference,
                   external_name, external_supplier, external_purity,
                   external_package_size, external_price_range,
                   created_at
            FROM orders WHERE order_id = ?
            """,
            (order_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    (
        oid,
        product_id,
        quantity,
        unit,
        status,
        customer_reference,
        external_name,
        external_supplier,
        external_purity,
        external_package_size,
        external_price_range,
        created_at,
    ) = row

    return {
        "order_id": oid,
        "product_id": product_id,
        "quantity": quantity,
        "unit": unit,
        "status": status,
        "customer_reference": customer_reference,
        "external_name": external_name,
        "external_supplier": external_supplier,
        "external_purity": external_purity,
        "external_package_size": external_package_size,
        "external_price_range": external_price_range,
        "created_at": created_at,
    }


def list_open_orders() -> list[dict]:
    """Listet offene Orders."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT order_id, product_id, quantity, unit, status,
                   customer_reference,
                   external_name, external_supplier, external_purity,
                   external_package_size, external_price_range,
                   created_at
            FROM orders WHERE status = 'OPEN'
            """
        )
        rows = cur.fetchall()

    orders: list[dict] = []
    for row in rows:
        (
            oid,
            product_id,
            quantity,
            unit,
            status,
            customer_reference,
            external_name,
            external_supplier,
            external_purity,
            external_package_size,
            external_price_range,
            created_at,
        ) = row
        orders.append(
            {
                "order_id": oid,
                "product_id": product_id,
                "quantity": quantity,
                "unit": unit,
                "status": status,
                "customer_reference": customer_reference,
                "external_name": external_name,
                "external_supplier": external_supplier,
                "external_purity": external_purity,
                "external_package_size": external_package_size,
                "external_price_range": external_price_range,
                "created_at": created_at,
            }
        )
    return orders


def list_all_products():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, cas_number, supplier, purity, package_size, price, currency, delivery_time_days
        FROM products
    """)

    rows = cur.fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "name": r[1],
            "cas_number": r[2],
            "supplier": r[3],
            "purity": r[4],
            "package_size": r[5],
            "price": r[6],
            "currency": r[7],
            "delivery_time_days": r[8],
        })
    return results
