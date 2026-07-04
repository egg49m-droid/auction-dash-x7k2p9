import sys
from datetime import datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import db
from src.dateutil_local import normalize_date


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")
    return str(value)


def import_xlsx(xlsx_path: str):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["出品管理"]
    rows = list(ws.iter_rows(values_only=True))
    header, data_rows = rows[0], rows[1:]

    conn = db.connect()
    count = 0
    for r in data_rows:
        if not r or not r[2]:
            continue
        (listed_date, account_name, auction_id, url, title, start_price, current_price,
         bid_count, has_bid, end_datetime, status, final_price, last_checked_at, note) = r[:14]
        db.upsert_listing(conn, {
            "auction_id": str(auction_id),
            "url": url,
            "account_name": account_name,
            "seller_id": None,
            "title": title,
            "start_price": start_price,
            "current_price": current_price,
            "bid_count": bid_count,
            "has_bid": has_bid,
            "end_datetime": _fmt_dt(end_datetime),
            "status": status,
            "final_price": final_price,
            "listed_date": normalize_date(_fmt_dt(listed_date)),
            "last_checked_at": last_checked_at,
            "note": note,
            "source": "manual",
        })
        count += 1
    conn.commit()
    conn.close()
    print(f"{count}件を取り込みました: {xlsx_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("使い方: python3 -m src.importer <xlsxファイルパス>")
        sys.exit(1)
    import_xlsx(sys.argv[1])
