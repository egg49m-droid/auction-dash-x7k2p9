import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "auctions.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    auction_id      TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    account_name    TEXT NOT NULL,
    seller_id       TEXT,
    title           TEXT,
    start_price     INTEGER,
    current_price   INTEGER,
    bid_count       INTEGER,
    has_bid         TEXT,
    end_datetime    TEXT,
    status          TEXT,
    final_price     INTEGER,
    listed_date     TEXT,
    last_checked_at TEXT,
    note            TEXT,
    source          TEXT DEFAULT 'manual'
);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
    if "source" not in existing_columns:
        conn.execute("ALTER TABLE listings ADD COLUMN source TEXT DEFAULT 'manual'")
    return conn


def get_sources(conn) -> dict:
    """auction_id -> source, for deciding whether discover should preserve a 'manual' tag."""
    return {row["auction_id"]: row["source"] for row in conn.execute("SELECT auction_id, source FROM listings")}


def upsert_listing(conn, row: dict):
    columns = [
        "auction_id", "url", "account_name", "seller_id", "title",
        "start_price", "current_price", "bid_count", "has_bid",
        "end_datetime", "status", "final_price", "listed_date",
        "last_checked_at", "note", "source",
    ]
    placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in columns if c != "auction_id")
    sql = f"""
        INSERT INTO listings ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(auction_id) DO UPDATE SET {update_clause}
    """
    conn.execute(sql, [row.get(c) for c in columns])


def get_all(conn):
    return conn.execute("SELECT * FROM listings ORDER BY listed_date, account_name").fetchall()


def get_active(conn):
    return conn.execute("SELECT * FROM listings WHERE status = '出品中'").fetchall()


def exists(conn, auction_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE auction_id = ?", (auction_id,)).fetchone()
    return row is not None
