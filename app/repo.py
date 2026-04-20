"""Thin DB-access helpers (CRUD)."""
from __future__ import annotations
import sqlite3
import datetime as dt
from decimal import Decimal
from typing import Iterable, List, Optional
from .pricing import LineItem


# ---------- Customers ----------

def upsert_customer(conn, data: dict) -> int:
    fields = ["first_name","last_name","phone","email","address1","address2","city","state","zip","notes"]
    vals = [data.get(f, "") for f in fields]
    if data.get("id"):
        conn.execute(
            f"UPDATE customers SET {', '.join(f'{f}=?' for f in fields)}, "
            f"updated_at=datetime('now') WHERE id=?",
            (*vals, data["id"]),
        )
        conn.commit()
        return int(data["id"])
    cur = conn.execute(
        f"INSERT INTO customers ({', '.join(fields)}) VALUES ({', '.join('?'*len(fields))})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def list_customers(conn, q: str = "") -> List[sqlite3.Row]:
    if q:
        like = f"%{q}%"
        return conn.execute(
            "SELECT * FROM customers WHERE first_name LIKE ? OR last_name LIKE ? OR phone LIKE ? OR email LIKE ? "
            "ORDER BY last_name, first_name",
            (like, like, like, like),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM customers ORDER BY last_name, first_name"
    ).fetchall()


def get_customer(conn, cid: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()


# ---------- Vehicles ----------

def upsert_vehicle(conn, data: dict) -> int:
    fields = ["customer_id","year","make","model","trim","vin","plate","color","mileage","inspection_exp","notes"]
    vals = [data.get(f) for f in fields]
    if data.get("id"):
        conn.execute(
            f"UPDATE vehicles SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
            (*vals, data["id"]),
        )
        conn.commit()
        return int(data["id"])
    cur = conn.execute(
        f"INSERT INTO vehicles ({', '.join(fields)}) VALUES ({', '.join('?'*len(fields))})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def vehicles_for_customer(conn, cid: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM vehicles WHERE customer_id=? ORDER BY year DESC, make, model",
        (cid,),
    ).fetchall()


# ---------- Vendors / Inventory ----------

def upsert_vendor(conn, data: dict) -> int:
    fields = ["name","phone","website","notes"]
    vals = [data.get(f,"") for f in fields]
    if data.get("id"):
        conn.execute(
            f"UPDATE vendors SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
            (*vals, data["id"]),
        )
        conn.commit()
        return int(data["id"])
    cur = conn.execute(
        f"INSERT INTO vendors ({', '.join(fields)}) VALUES ({', '.join('?'*len(fields))})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def list_vendors(conn) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM vendors ORDER BY name").fetchall()


def upsert_part(conn, data: dict) -> int:
    fields = ["sku","description","vendor_id","unit_cost","on_hand","reorder_point","location","last_received"]
    vals = [data.get(f) for f in fields]
    if data.get("id"):
        conn.execute(
            f"UPDATE inventory SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
            (*vals, data["id"]),
        )
        conn.commit()
        return int(data["id"])
    cur = conn.execute(
        f"INSERT INTO inventory ({', '.join(fields)}) VALUES ({', '.join('?'*len(fields))})",
        vals,
    )
    conn.commit()
    return int(cur.lastrowid)


def list_inventory(conn, q: str = "") -> List[sqlite3.Row]:
    if q:
        like = f"%{q}%"
        return conn.execute(
            "SELECT inventory.*, vendors.name AS vendor_name FROM inventory "
            "LEFT JOIN vendors ON vendors.id = inventory.vendor_id "
            "WHERE inventory.description LIKE ? OR inventory.sku LIKE ? "
            "ORDER BY inventory.description",
            (like, like),
        ).fetchall()
    return conn.execute(
        "SELECT inventory.*, vendors.name AS vendor_name FROM inventory "
        "LEFT JOIN vendors ON vendors.id = inventory.vendor_id "
        "ORDER BY inventory.description"
    ).fetchall()


def decrement_inventory(conn, part_id: int, qty: float) -> None:
    conn.execute(
        "UPDATE inventory SET on_hand = MAX(on_hand - ?, 0) WHERE id = ?",
        (int(qty), part_id),
    )
    conn.commit()


# ---------- Jobs + line items ----------

def create_job(conn, customer_id: int, vehicle_id: Optional[int], tax_rate: float) -> int:
    from .db import next_job_number
    number = next_job_number(conn, "E")
    cur = conn.execute(
        "INSERT INTO jobs (number, customer_id, vehicle_id, status, tax_rate) "
        "VALUES (?, ?, ?, 'estimate', ?)",
        (number, customer_id, vehicle_id, tax_rate),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_job(conn, job_id: int, **kwargs) -> None:
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(f"UPDATE jobs SET {fields} WHERE id=?", (*kwargs.values(), job_id))
    conn.commit()


def get_job(conn, jid: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()


def list_jobs(conn, statuses: Iterable[str] = ("estimate","invoice")) -> List[sqlite3.Row]:
    ph = ",".join("?" * len(list(statuses)))
    rows = conn.execute(
        f"SELECT j.*, c.first_name, c.last_name, v.year, v.make, v.model, v.plate "
        f"FROM jobs j "
        f"JOIN customers c ON c.id = j.customer_id "
        f"LEFT JOIN vehicles v ON v.id = j.vehicle_id "
        f"WHERE j.status IN ({ph}) "
        f"ORDER BY j.opened_at DESC",
        tuple(statuses),
    ).fetchall()
    return rows


def delete_job(conn, jid: int) -> None:
    """Hard delete. Cascades to line_items via FK."""
    conn.execute("DELETE FROM jobs WHERE id=?", (jid,))
    conn.commit()


def delete_job_with_reason(conn, jid: int, reason: str,
                           restock: bool = True) -> dict:
    """Manually delete any job — estimate, invoice, or previously-paid
    invoice (for returns / refunds / corrections).

    If the job was already marked paid and inventory was decremented, setting
    restock=True will put the parts back on the shelf. Each deletion is
    logged to the `deletion_log` table so there's an audit trail.

    Returns a small report dict with what was removed and what was restocked.
    """
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if row is None:
        raise ValueError(f"job {jid} not found")

    was_paid = row["status"] in ("paid", "archived")
    restocked: list[tuple[int, int]] = []  # (part_id, qty)

    try:
        conn.execute("BEGIN")
        if was_paid and restock:
            # Put parts back on the shelf for refund scenarios.
            lines = conn.execute(
                "SELECT part_id, quantity FROM line_items "
                "WHERE job_id=? AND part_id IS NOT NULL AND kind='part'",
                (jid,),
            ).fetchall()
            for l in lines:
                pid = l["part_id"]
                qty = int(float(l["quantity"]))
                if qty <= 0 or pid is None:
                    continue
                conn.execute(
                    "UPDATE inventory SET on_hand = on_hand + ? WHERE id = ?",
                    (qty, pid),
                )
                restocked.append((pid, qty))

        # Audit log. The table is created lazily if it doesn't yet exist so
        # this works on older DBs too.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deletion_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id     INTEGER NOT NULL,
                job_number TEXT,
                status_at_delete TEXT,
                reason     TEXT NOT NULL,
                restocked_json TEXT,
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        import json
        conn.execute(
            "INSERT INTO deletion_log (job_id, job_number, status_at_delete, "
            "reason, restocked_json) VALUES (?,?,?,?,?)",
            (jid, row["number"], row["status"], reason,
             json.dumps(restocked)),
        )

        conn.execute("DELETE FROM jobs WHERE id=?", (jid,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {
        "job_id": jid,
        "number": row["number"],
        "was_paid": was_paid,
        "restocked": restocked,
        "reason": reason,
    }


def load_lines(conn, job_id: int) -> List[LineItem]:
    rows = conn.execute(
        "SELECT * FROM line_items WHERE job_id=? ORDER BY sort_order, id",
        (job_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(LineItem(
            id=r["id"],
            kind=r["kind"],
            description=r["description"],
            quantity=Decimal(str(r["quantity"])),
            unit_cost=Decimal(str(r["unit_cost"])),
            unit_price=Decimal(str(r["unit_price"])),
            taxable=bool(r["taxable"]),
            part_id=r["part_id"],
        ))
    return out


def save_lines(conn, job_id: int, lines: List[LineItem]) -> None:
    conn.execute("DELETE FROM line_items WHERE job_id=?", (job_id,))
    for i, l in enumerate(lines):
        conn.execute(
            "INSERT INTO line_items (job_id, sort_order, kind, description, quantity, "
            "unit_cost, unit_price, taxable, part_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                job_id, i, l.kind, l.description,
                float(l.quantity), float(l.unit_cost), float(l.unit_price),
                1 if l.taxable else 0,
                l.part_id,
            ),
        )
    conn.commit()


# ---------- Time clock ----------

def clock_in(conn, tech: str, hourly_rate: float, job_id: Optional[int] = None) -> int:
    cur = conn.execute(
        "INSERT INTO time_entries (tech, clock_in, hourly_rate, job_id) "
        "VALUES (?, datetime('now'), ?, ?)",
        (tech, hourly_rate, job_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def clock_out(conn, entry_id: int) -> None:
    conn.execute(
        "UPDATE time_entries SET clock_out = datetime('now') WHERE id=? AND clock_out IS NULL",
        (entry_id,),
    )
    conn.commit()


def open_time_entry(conn, tech: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM time_entries WHERE tech=? AND clock_out IS NULL "
        "ORDER BY clock_in DESC LIMIT 1",
        (tech,),
    ).fetchone()


# ---------- Reminders ----------

def add_reminder(conn, customer_id: int, vehicle_id: Optional[int], kind: str,
                 due_date: str, description: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO reminders (customer_id, vehicle_id, kind, due_date, description) "
        "VALUES (?,?,?,?,?)",
        (customer_id, vehicle_id, kind, due_date, description),
    )
    conn.commit()
    return int(cur.lastrowid)


def upcoming_reminders(conn, within_days: int = 30) -> List[sqlite3.Row]:
    today = dt.date.today().isoformat()
    until = (dt.date.today() + dt.timedelta(days=within_days)).isoformat()
    return conn.execute(
        "SELECT r.*, c.first_name, c.last_name, c.phone, v.year, v.make, v.model "
        "FROM reminders r "
        "JOIN customers c ON c.id = r.customer_id "
        "LEFT JOIN vehicles v ON v.id = r.vehicle_id "
        "WHERE r.done = 0 AND r.due_date BETWEEN ? AND ? "
        "ORDER BY r.due_date",
        (today, until),
    ).fetchall()
