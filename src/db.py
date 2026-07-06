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
    contact_url     TEXT,
    recipient_name    TEXT,
    recipient_address TEXT,
    shipping_method   TEXT,
    tracking_number   TEXT,
    status_since      TEXT
);
"""

TRADE_COLUMNS = ["trade_progress", "trade_message", "buyer_id", "contact_url"]
SHIPPING_COLUMNS = ["recipient_name", "recipient_address", "shipping_method", "tracking_number"]
STATUS_TRACKING_COLUMNS = ["status_since"]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
    if "source" not in existing_columns:
        conn.execute("ALTER TABLE listings ADD COLUMN source TEXT DEFAULT 'manual'")
    for col in TRADE_COLUMNS + SHIPPING_COLUMNS + STATUS_TRACKING_COLUMNS:
        if col not in existing_columns:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} TEXT")
    return conn


def get_trade_tracked_rows(conn, account_name: str):
    """取引ステータス安定度の判定に必要な最小限のカラムだけを取得する(効率化計算用)。"""
    return conn.execute(
        "SELECT auction_id, end_datetime, trade_progress, status_since FROM listings "
        "WHERE account_name = ? AND end_datetime IS NOT NULL",
        (account_name,),
    ).fetchall()


def get_trade_progress_map(conn, account_name: str) -> dict:
    """auction_id -> {trade_progress, status_since}。取引状況が変化したかどうかの判定に使う。"""
    rows = conn.execute(
        "SELECT auction_id, trade_progress, status_since FROM listings WHERE account_name = ?",
        (account_name,),
    ).fetchall()
    return {r["auction_id"]: {"trade_progress": r["trade_progress"], "status_since": r["status_since"]} for r in rows}


def get_stale_shipping_rows(conn, cutoff: str):
    """発送済み(SHIPPING)のまま status_since が cutoff より前の行(＝14日ルールで自動着金される想定)。"""
    return conn.execute(
        "SELECT * FROM listings WHERE trade_progress = 'SHIPPING' AND status_since IS NOT NULL AND status_since <= ?",
        (cutoff,),
    ).fetchall()


def auto_complete_stale_shipping(conn, auction_id: str, now: str):
    conn.execute(
        "UPDATE listings SET trade_progress = 'COMPLETE', trade_message = ?, status_since = ? WHERE auction_id = ?",
        ("自動着金(発送後14日経過・受け取り連絡なし)", now, auction_id),
    )
    clear_recipient_info(conn, auction_id)


def clear_recipient_info(conn, auction_id: str):
    """着金確定後は不要になったお届け先氏名・住所を消去する(追跡番号・配送方法は記録として残す)。"""
    conn.execute(
        "UPDATE listings SET recipient_name = NULL, recipient_address = NULL WHERE auction_id = ?",
        (auction_id,),
    )


def update_shipping_info(conn, auction_id: str, info: dict):
    conn.execute(
        "UPDATE listings SET recipient_name=?, recipient_address=?, shipping_method=?, tracking_number=? WHERE auction_id=?",
        (info.get("recipient_name"), info.get("recipient_address"), info.get("shipping_method"),
         info.get("tracking_number"), auction_id),
    )


def get_rows_needing_shipping_info(conn):
    """発送完了/要確認ステータスで、まだお届け先情報が未取得の行。"""
    return conn.execute(
        """SELECT * FROM listings
           WHERE contact_url IS NOT NULL
             AND tracking_number IS NULL
             AND (trade_progress = 'SHIPPING' OR (trade_progress IS NOT NULL AND trade_progress NOT IN
                 ('ADDRESS_INPUTING', 'PREPARATION_FOR_SHIPMENT', 'SHIPPING', 'COMPLETE')))"""
    ).fetchall()


def upsert_trade_status(conn, row: dict):
    columns = [
        "auction_id", "url", "account_name", "seller_id", "title",
        "final_price", "end_datetime", "status", "source",
        "trade_progress", "trade_message", "buyer_id", "contact_url",
        "last_checked_at", "status_since",
    ]
    update_columns = [
        "url", "title", "final_price", "end_datetime", "status",
        "trade_progress", "trade_message", "buyer_id", "contact_url", "last_checked_at",
        "status_since",
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


def get_ended_missing_price_or_bid_or_date(conn):
    """終了済みで、現在価格・入札件数・出品日のいずれかが未取得の行(取引ナビ経由で登録された落札/落札者なし商品など)。"""
    return conn.execute(
        """SELECT * FROM listings WHERE status = '終了'
           AND (current_price IS NULL OR bid_count IS NULL OR listed_date IS NULL OR listed_date = '')"""
    ).fetchall()


def update_price_bid_date(conn, auction_id: str, current_price, bid_count, has_bid, listed_date):
    conn.execute(
        "UPDATE listings SET current_price = ?, bid_count = ?, has_bid = ?, listed_date = ? WHERE auction_id = ?",
        (current_price, bid_count, has_bid, listed_date, auction_id),
    )


def get_active(conn):
    return conn.execute("SELECT * FROM listings WHERE status = '出品中'").fetchall()


def exists(conn, auction_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE auction_id = ?", (auction_id,)).fetchone()
    return row is not None
