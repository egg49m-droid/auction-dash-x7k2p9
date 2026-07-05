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
    source          TEXT DEFAULT 'manual',
    trade_progress  TEXT,
    trade_message   TEXT,
    buyer_id        TEXT,
    contact_url     TEXT
);
"""

TRADE_COLUMNS = ["trade_progress", "trade_message", "buyer_id", "contact_url"]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
    if "source" not in existing_columns:
        conn.execute("ALTER TABLE listings ADD COLUMN source TEXT DEFAULT 'manual'")
    for col in TRADE_COLUMNS:
        if col not in existing_columns:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} TEXT")
    return conn


def upsert_trade_status(conn, row: dict):
    columns = [
        "auction_id", "url", "account_name", "seller_id", "title",
        "final_price", "end_datetime", "status", "source",
        "trade_progress", "trade_message", "buyer_id", "contact_url",
        "last_checked_at",
    ]
    update_columns = [
        "url", "title", "final_price", "end_datetime", "status",
        "trade_progress", "trade_message", "buyer_id", "contact_url", "last_checked_at",
    ]
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_columns)
    sql = f"""
        INSERT INTO listings ({", ".join(columns)})
        VALUES ({", ".join("?" for _ in columns)})
        ON CONFLICT(auction_id) DO UPDATE SET {update_clause}
    """
    conn.execute(sql, [row.get(c) for c in columns])


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


SNAPSHOT_COLUMNS = [
    "auction_id", "url", "account_name", "title",
    "start_price", "current_price", "bid_count", "has_bid",
    "end_datetime", "status", "final_price", "listed_date",
    "source", "trade_progress", "trade_message",
]


def to_snapshot_dict(row) -> dict:
    """ローカルDBの行から、公開リポジトリに同期しても問題ない項目だけを抜き出す(買い手ID等は含めない)。"""
    return {c: row[c] for c in SNAPSHOT_COLUMNS}


def upsert_snapshot(conn, row: dict):
    """他環境(クラウド)から取り込んだsnapshotをマージする。account_name以外はexcludedで上書きする。"""
    columns = SNAPSHOT_COLUMNS
    update_columns = [c for c in columns if c not in ("auction_id", "account_name")]
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_columns)
    sql = f"""
        INSERT INTO listings ({", ".join(columns)})
        VALUES ({", ".join("?" for _ in columns)})
        ON CONFLICT(auction_id) DO UPDATE SET {update_clause}
    """
    conn.execute(sql, [row.get(c) for c in columns])


def get_missing_listed_date(conn):
    return conn.execute("SELECT * FROM listings WHERE listed_date IS NULL OR listed_date = ''").fetchall()


def update_listed_date(conn, auction_id: str, listed_date: str):
    conn.execute("UPDATE listings SET listed_date = ? WHERE auction_id = ?", (listed_date, auction_id))


def get_active(conn):
    return conn.execute("SELECT * FROM listings WHERE status = '出品中'").fetchall()


def exists(conn, auction_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE auction_id = ?", (auction_id,)).fetchone()
    return row is not None
