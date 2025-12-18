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
                available_quantity REAL,
                available_unit TEXT DEFAULT 'g',
                last_updated TEXT
            )
            """
        )
        
        # Migration: Add available_quantity and available_unit columns if they don't exist
        try:
            cur.execute("ALTER TABLE products ADD COLUMN available_quantity REAL")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        try:
            cur.execute("ALTER TABLE products ADD COLUMN available_unit TEXT DEFAULT 'g'")
        except sqlite3.OperationalError:
            pass  # Column already exists

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
    available_quantity: float | None = None,
    available_unit: str = "g",
) -> int:
    """Fügt ein Produkt hinzu und gibt die ID zurück."""
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO products (
                name, cas_number, supplier, purity, package_size,
                price, currency, delivery_time_days, available_quantity, available_unit, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                available_quantity,
                available_unit,
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
    available_quantity: float | None = None,
    available_unit: str | None = None,
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
        "available_quantity": available_quantity,
        "available_unit": available_unit,
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
    sql = "SELECT id, name, cas_number, supplier, purity, package_size, price, currency, delivery_time_days, available_quantity, available_unit FROM products WHERE 1=1"
    params: list[object] = []

    if query:
        sql += " AND name LIKE ?"
        params.append(f"%{query}%")
    if cas_number:
        sql += " AND cas_number = ?"
        params.append(cas_number)
    if supplier:
        sql += " AND supplier LIKE ?"
        params.append(f"%{supplier}%")
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
            available_quantity,
            available_unit,
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
                "available_quantity": available_quantity,
                "available_unit": available_unit,
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
    auto_reduce_inventory: bool = True,
) -> dict:
    """Erstellt interne oder externe Orders. Automatisch reduziert verfügbare Menge bei internen Orders."""
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
        
        # Automatically reduce available quantity for internal orders (product_id > 0)
        if auto_reduce_inventory and product_id > 0:
            # Use the same connection to avoid locking issues
            _reduce_product_quantity_with_cursor(cur, product_id, quantity, unit, now)

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
        SELECT id, name, cas_number, supplier, purity, package_size, price, currency, delivery_time_days, available_quantity, available_unit
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
            "available_quantity": r[9] if len(r) > 9 else None,
            "available_unit": r[10] if len(r) > 10 else None,
        })
    return results


def _reduce_product_quantity_with_cursor(cur, product_id: int, quantity: float, unit: str, timestamp: str) -> bool:
    """
    Internal helper to reduce product quantity using an existing cursor.
    Used within create_order to avoid connection locking.
    """
    # Get current available_quantity
    cur.execute(
        "SELECT available_quantity, available_unit FROM products WHERE id = ?",
        (product_id,)
    )
    row = cur.fetchone()
    
    if row is None:
        return False
    
    current_quantity, current_unit = row
    
    # If no quantity was set, skip reduction (cannot reduce from NULL)
    if current_quantity is None:
        return False
    
    # For now, we only reduce if units match (can be enhanced later with unit conversion)
    if current_unit and current_unit != unit:
        # Units don't match - skip automatic reduction but don't fail
        return False
    
    # Calculate new quantity
    new_quantity = max(0.0, current_quantity - quantity)
    
    # Update the product
    cur.execute(
        "UPDATE products SET available_quantity = ?, last_updated = ? WHERE id = ?",
        (new_quantity, timestamp, product_id)
    )
    
    return cur.rowcount > 0


def reduce_product_quantity(product_id: int, quantity: float, unit: str) -> bool:
    """
    Reduziert die verfügbare Menge eines Produkts basierend auf einer Bestellung.
    Gibt True zurück, wenn die Aktualisierung erfolgreich war.
    
    Note: Diese Funktion führt keine Unit-Konvertierung durch.
    Es wird erwartet, dass quantity und unit mit der vorhandenen available_unit übereinstimmen.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        timestamp = datetime.utcnow().isoformat()
        return _reduce_product_quantity_with_cursor(cur, product_id, quantity, unit, timestamp)


def get_product(product_id: int) -> dict | None:
    """Retrieves a single product by ID."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, cas_number, supplier, purity, package_size, price, currency, 
                   delivery_time_days, available_quantity, available_unit
            FROM products WHERE id = ?
            """,
            (product_id,)
        )
        row = cur.fetchone()
        
    if row is None:
        return None
    
    return {
        "id": row[0],
        "name": row[1],
        "cas_number": row[2],
        "supplier": row[3],
        "purity": row[4],
        "package_size": row[5],
        "price": row[6],
        "currency": row[7],
        "delivery_time_days": row[8],
        "available_quantity": row[9],
        "available_unit": row[10],
    }


def list_all_orders(
    status: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "DESC",
    limit: int | None = None,
) -> list[dict]:
    """
    Lists all orders with optional filtering and sorting.
    
    Args:
        status: Filter by status (e.g., 'OPEN', 'COMPLETED', 'CANCELLED'). None for all.
        sort_by: Column to sort by ('created_at', 'order_id', 'quantity', 'status').
        sort_order: 'ASC' or 'DESC' (default DESC for newest first).
        limit: Maximum number of orders to return. None for all.
    
    Returns:
        List of order dictionaries.
    """
    # Validate sort_by to prevent SQL injection
    valid_columns = {"created_at", "order_id", "quantity", "status", "product_id"}
    if sort_by not in valid_columns:
        sort_by = "created_at"
    
    # Validate sort_order
    sort_order = "DESC" if sort_order.upper() not in ("ASC", "DESC") else sort_order.upper()
    
    sql = """
        SELECT order_id, product_id, quantity, unit, status,
               customer_reference,
               external_name, external_supplier, external_purity,
               external_package_size, external_price_range,
               created_at
        FROM orders
    """
    params: list[object] = []
    
    if status:
        sql += " WHERE status = ?"
        params.append(status.upper())
    
    sql += f" ORDER BY {sort_by} {sort_order}"
    
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
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


def calculate_monthly_spending(year: int, month: int) -> dict:
    """
    Aggregiert alle Ausgaben für einen gegebenen Monat.
    Verarbeitet robuste Preisformate wie:
      - 'CHF 20 - 55'
      - '20-55'
      - '20 - 55'
      - 'CHF 30'
      - '30'
    """

    import re

    def parse_price_range(pr):
        if not pr:
            return 0.0

        # Entferne CHF, Leerzeichen, "bis", etc.
        cleaned = re.sub(r"[^\d\-\.]", "", pr)

        # Fälle:
        #  1) "20-50"
        #  2) "20"
        if "-" in cleaned:
            low, high = cleaned.split("-")
            try:
                return (float(low) + float(high)) / 2
            except:
                return 0.0
        else:
            # Einzelpreis
            try:
                return float(cleaned)
            except:
                return 0.0

    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                o.order_id, o.product_id, o.quantity, o.unit,
                o.created_at,
                p.price,
                o.external_price_range,
                o.external_name,
                o.external_supplier
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.id
            WHERE strftime('%Y', o.created_at) = ?
              AND strftime('%m', o.created_at) = ?
            """,
            (str(year), f"{month:02d}")
        )

        rows = cur.fetchall()

    total = 0.0
    orders_list = []

    for row in rows:
        (
            order_id, pid, quantity, unit,
            created_at, price, ext_range, ext_name, ext_supplier
        ) = row

        # INTERNER PREIS
        if pid != 0 and price is not None:
            estimated_cost = float(price)

        # EXTERNER PREIS
        else:
            estimated_cost = parse_price_range(ext_range)

        total += estimated_cost

        orders_list.append({
            "order_id": order_id,
            "product_id": pid,
            "estimated_cost": estimated_cost,
            "quantity": quantity,
            "unit": unit,
            "created_at": created_at,
            "external_name": ext_name,
            "external_supplier": ext_supplier
        })

    return {
        "year": year,
        "month": month,
        "total_spending": round(total, 2),
        "orders": orders_list
    }


