"""SQLite schema + connection helpers for Up Front Auto Repair Shop."""
from __future__ import annotations
import os
import sqlite3
import datetime as dt
from pathlib import Path

SCHEMA = r"""
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    address1    TEXT,
    address2    TEXT,
    city        TEXT,
    state       TEXT,
    zip         TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_customers_last ON customers(last_name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

CREATE TABLE IF NOT EXISTS vehicles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    year        INTEGER,
    make        TEXT,
    model       TEXT,
    trim        TEXT,
    vin         TEXT,
    plate       TEXT,
    color       TEXT,
    mileage     INTEGER,
    inspection_exp TEXT,          -- YYYY-MM for sticker expiration
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vehicles_customer ON vehicles(customer_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_plate ON vehicles(plate);

CREATE TABLE IF NOT EXISTS vendors (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL UNIQUE,
    phone   TEXT,
    website TEXT,
    notes   TEXT
);

CREATE TABLE IF NOT EXISTS inventory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT,
    description   TEXT NOT NULL,
    vendor_id     INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    unit_cost     REAL NOT NULL,
    on_hand       INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER NOT NULL DEFAULT 0,
    location      TEXT,
    last_received TEXT
);
CREATE INDEX IF NOT EXISTS idx_inventory_desc ON inventory(description);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku);

CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    number         TEXT UNIQUE,                 -- e.g. E-000123 / I-000123
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    vehicle_id    INTEGER REFERENCES vehicles(id),
    status         TEXT NOT NULL DEFAULT 'estimate',  -- estimate|invoice|paid|archived|voided
    payment_method TEXT,                        -- card|cash|check|unpaid
    tax_rate       REAL NOT NULL DEFAULT 0.055,
    notes          TEXT,
    tech           TEXT,
    odometer_in    INTEGER,
    odometer_out   INTEGER,
    opened_at      TEXT NOT NULL DEFAULT (datetime('now')),
    invoiced_at    TEXT,
    paid_at        TEXT,
    paid_total     REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_customer ON jobs(customer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS line_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL CHECK (kind IN ('part','labor')),
    description TEXT NOT NULL,
    quantity    REAL NOT NULL DEFAULT 1,
    unit_cost   REAL NOT NULL DEFAULT 0,
    unit_price  REAL NOT NULL DEFAULT 0,
    taxable     INTEGER NOT NULL DEFAULT 1,
    part_id     INTEGER REFERENCES inventory(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_line_job ON line_items(job_id);

CREATE TABLE IF NOT EXISTS time_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tech        TEXT NOT NULL,
    clock_in    TEXT NOT NULL,
    clock_out   TEXT,
    job_id      INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    hourly_rate REAL NOT NULL DEFAULT 0,
    notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_time_tech ON time_entries(tech);
CREATE INDEX IF NOT EXISTS idx_time_clockin ON time_entries(clock_in);

CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    vehicle_id   INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,    -- inspection | oil | other
    due_date     TEXT NOT NULL,
    description  TEXT,
    done         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS markup_tiers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order   INTEGER NOT NULL,
    upper_bound  REAL,            -- NULL = 'and up'
    multiplier   REAL NOT NULL
);
"""


DEFAULT_SETTINGS = {
    "shop_name": "Up Front Auto Repair",
    "shop_address1": "129 Ossipee Trail W",
    "shop_address2": "",
    "shop_city": "Standish",
    "shop_state": "ME",
    "shop_zip": "04084",
    "shop_phone": "(207) 648-4747",
    "shop_email": "info@upfrontautorepair207.com",
    "shop_website": "upfrontautorepair207.com",
    "tax_rate": "0.055",
    # Every invoice carries a 3.5% non-cash adjustment by default.
    "non_cash_adjustment_rate": "0.035",
    # Cash or check payment earns a matching 3.5% discount.
    "cash_check_discount_rate": "0.035",
    # legacy keys kept so older install databases still load cleanly
    "card_surcharge_rate": "0.035",
    "cash_discount_rate": "0.035",
    "default_labor_rate": "125.00",
    "inspection_fee": "18.50",
    "printer_name": "",           # blank = system default
    "invoice_footer": "All prices include a 3.5% non-cash adjustment. Invoices paid in cash or check receive a 3.5% discount.",
    "next_job_number": "1",
    "logo_path": "",              # absolute path to shop logo image (PNG/JPG). Blank = text-only header.
    "review_url": "https://upfrontautorepair207.com",    # QR code target on invoices
    "review_cta": "Scan to leave us a review",
}


DEFAULT_MARKUP = [
    (1, 2.50,  4.00),
    (2, 5.00,  3.75),
    (3, 10.00, 3.00),
    (4, 50.00, 2.75),
    (5, 100.00,2.50),
    (6, 150.00,2.20),
    (7, 200.00,2.00),
    (8, 500.00,1.85),
    (9, None,  1.70),
]


def default_db_path() -> Path:
    """Where the SQLite DB lives. On Windows: %APPDATA%\\UpFrontShop\\shop.db.
    On other platforms: ~/.upfront-shop/shop.db for local dev/testing."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "UpFrontShop"
    else:
        base = Path.home() / ".upfront-shop"
    base.mkdir(parents=True, exist_ok=True)
    return base / "shop.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else default_db_path()
    conn = sqlite3.connect(str(p), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # seed settings
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (k, v),
        )
    # seed markup tiers if empty
    n = conn.execute("SELECT COUNT(*) AS c FROM markup_tiers").fetchone()["c"]
    if n == 0:
        conn.executemany(
            "INSERT INTO markup_tiers(sort_order, upper_bound, multiplier) VALUES (?,?,?)",
            DEFAULT_MARKUP,
        )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def load_markup_tiers(conn: sqlite3.Connection):
    from decimal import Decimal
    rows = conn.execute(
        "SELECT upper_bound, multiplier FROM markup_tiers ORDER BY sort_order"
    ).fetchall()
    return [
        (Decimal(str(r["upper_bound"])) if r["upper_bound"] is not None else None,
         Decimal(str(r["multiplier"])))
        for r in rows
    ]


def next_job_number(conn: sqlite3.Connection, prefix: str = "E") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key='next_job_number'").fetchone()
    n = int(r["value"]) if r else 1
    number = f"{prefix}-{n:06d}"
    conn.execute(
        "UPDATE settings SET value = ? WHERE key='next_job_number'",
        (str(n + 1),),
    )
    return number
