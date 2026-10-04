"""SQLite persistence for the paper-trading account."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    cash REAL NOT NULL,
    starting_cash REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_positions (
    symbol TEXT PRIMARY KEY,
    qty INTEGER NOT NULL,
    avg_cost REAL NOT NULL
);
-- qty > 0 is long, qty < 0 is short (written). avg_price is per-share premium.
CREATE TABLE IF NOT EXISTS option_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    option_type TEXT NOT NULL CHECK (option_type IN ('call', 'put')),
    strike REAL NOT NULL,
    expiration TEXT NOT NULL,
    qty INTEGER NOT NULL,
    avg_price REAL NOT NULL,
    opened_at TEXT NOT NULL,
    UNIQUE (symbol, option_type, strike, expiration)
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    option_type TEXT,
    strike REAL,
    expiration TEXT,
    fees REAL NOT NULL DEFAULT 0,
    cash_delta REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    strategy TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trade_id INTEGER REFERENCES trades (id),
    symbol TEXT,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    order_json TEXT NOT NULL,
    rationale TEXT
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    date TEXT PRIMARY KEY,
    equity REAL NOT NULL,
    cash REAL NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str, starting_cash: float) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    if conn.execute("SELECT 1 FROM account").fetchone() is None:
        conn.execute(
            "INSERT INTO account (id, cash, starting_cash, created_at) VALUES (1, ?, ?, ?)",
            (starting_cash, starting_cash, now_iso()),
        )
    return conn


def reset(conn: sqlite3.Connection, starting_cash: float) -> None:
    conn.execute("BEGIN")
    for table in ("journal", "trades", "stock_positions", "option_positions",
                  "pending_orders", "equity_snapshots", "account"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute(
        "INSERT INTO account (id, cash, starting_cash, created_at) VALUES (1, ?, ?, ?)",
        (starting_cash, starting_cash, now_iso()),
    )
    conn.execute("COMMIT")
