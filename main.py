import asyncio
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src import db, dashboard, scraper, sheets_sync
from src.dateutil_local import normalize_date

DATE_LINE_RE = re.compile(r"^#\s*(\d{4}/\d{1,2}/\d{1,2})")
URL_RE = re.compile(r"https://auctions\.yahoo\.co\.jp/\S+")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_input_file(path: Path) -> list[tuple[str, str]]:
    """Returns list of (listed_date, url). '# YYYY/M/D' lines set the date for following URLs."""
    current_date = datetime.now().strftime("%Y/%m/%d")
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            date_match = DATE_LINE_RE.match(line)
            if date_match:
                current_date = normalize_date(date_match.group(1))
            continue
        url_match = URL_RE.search(line)
        if url_match:
            result.append((current_date, url_match.group(0)))
    return result


def cmd_add(args):
    """自分が出品したと明示している出品を手動貼り付けのURLから登録する (source='manual')。"""
    input_path = ROOT / "input" / "new_urls.txt"
    if not input_path.exists() or not input_path.read_text(encoding="utf-8").strip():
        print(f"{input_path} が空です。出品日とURLを貼り付けてから実行してください。")
        return

    entries = parse_input_file(input_path)
    if not entries:
        print("URLが見つかりませんでした。")
        return

    settings = load_json(ROOT / "config" / "settings.json")
    accounts = load_json(ROOT / "config" / "accounts.json")

    urls = [url for _, url in entries]
    results = asyncio.run(scraper.fetch_many(urls, settings))
    results_by_url = {r["url"]: r for r in results}

    conn = db.connect()
    added, errors, needs_review = 0, 0, []
    for listed_date, url in entries:
        r = results_by_url[url]
        if r.get("error"):
            errors += 1
            print(f"  ! 取得失敗: {url} -> {r['error']}")
            continue
        account_name = scraper.resolve_account_name(r["seller_id"], accounts)
        if account_name == "要確認":
            needs_review.append((r["auction_id"], r["seller_id"]))
        db.upsert_listing(conn, {
            "auction_id": r["auction_id"],
            "url": url,
            "account_name": account_name,
            "seller_id": r["seller_id"],
            "title": r["title"],
            "start_price": r["start_price"],
            "current_price": r["current_price"],
            "bid_count": r["bid_count"],
            "has_bid": r["has_bid"],
            "end_datetime": r["end_datetime"],
            "status": r["status"],
            "final_price": r["final_price"],
            "listed_date": listed_date,
            "last_checked_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
            "note": None,
            "source": "manual",
        })
        added += 1
    conn.commit()
    conn.close()

    processed_dir = ROOT / "input" / "processed"
    processed_dir.mkdir(exist_ok=True)
    archive_name = f"new_urls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    shutil.move(str(input_path), str(processed_dir / archive_name))
    input_path.write_text("", encoding="utf-8")

    print(f"\n追加: {added}件 ／ 取得失敗: {errors}件")
    if needs_review:
        print("要確認（未登録の出品者ID）:")
        for auction_id, seller_id in needs_review:
            print(f"  - {auction_id}: seller_id={seller_id}")

    _print_summary()


def _discover(settings: dict, accounts: dict) -> set:
    """3アカウントの出品者ページを全件クロールし、新規出品をDBへ自動登録する。
    手動登録済み(source='manual')のものは上書きしない。戻り値は「今回アクティブと確認できたID集合」。
    """
    since_str = settings.get("discover_since")
    since = date.fromisoformat(since_str) if since_str else None

    seller_ids = list(accounts.keys())
    listings_by_seller = asyncio.run(scraper.fetch_all_seller_listings(seller_ids, settings))

    conn = db.connect()
    existing_sources = db.get_sources(conn)

    confirmed_active_ids = set()
    added, updated, skipped_old = 0, 0, 0
    for seller_id, rows in listings_by_seller.items():
        account_name = accounts.get(seller_id, "要確認")
        for row in rows:
            start_dt = row.pop("start_datetime", None)
            if since and start_dt and start_dt.date() < since:
                skipped_old += 1
                continue
            confirmed_active_ids.add(row["auction_id"])
            existing_source = existing_sources.get(row["auction_id"])
            source = existing_source if existing_source == "manual" else "auto"
            is_new = row["auction_id"] not in existing_sources
            db.upsert_listing(conn, {
                **row,
                "account_name": account_name,
                "last_checked_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
                "note": None,
                "source": source,
            })
            if is_new:
                added += 1
            else:
                updated += 1
    conn.commit()
    conn.close()
    print(f"アカウント全体クロール: 新規{added}件 ／ 更新{updated}件 ／ {since_str}より前のため除外{skipped_old}件")
    return confirmed_active_ids


def cmd_discover(args):
    settings = load_json(ROOT / "config" / "settings.json")
    accounts = load_json(ROOT / "config" / "accounts.json")
    _discover(settings, accounts)
    _print_summary()


def _recheck(settings: dict, accounts: dict, skip_ids: set = frozenset()):
    """出品中の行を再取得する。skip_idsに含まれるIDは、直前のdiscoverでアクティブと確認済みのためスキップ(個別ページ取得を節約)。"""
    conn = db.connect()
    active_rows = [r for r in db.get_active(conn) if r["auction_id"] not in skip_ids]
    if not active_rows:
        print("再チェック対象が0件のためスキップします。")
        conn.close()
        return

    urls = [row["url"] for row in active_rows]
    results = asyncio.run(scraper.fetch_many(urls, settings))
    results_by_url = {r["url"]: r for r in results}

    updated, ended, errors = 0, 0, 0
    for row in active_rows:
        r = results_by_url[row["url"]]
        if r.get("error"):
            errors += 1
            continue
        account_name = row["account_name"]
        if account_name == "要確認" and r.get("seller_id"):
            account_name = scraper.resolve_account_name(r["seller_id"], accounts)
        db.upsert_listing(conn, {
            "auction_id": row["auction_id"],
            "url": row["url"],
            "account_name": account_name,
            "seller_id": r["seller_id"] or row["seller_id"],
            "title": r["title"] or row["title"],
            "start_price": row["start_price"],
            "current_price": r["current_price"],
            "bid_count": r["bid_count"],
            "has_bid": r["has_bid"],
            "end_datetime": r["end_datetime"] or row["end_datetime"],
            "status": r["status"],
            "final_price": r["final_price"],
            "listed_date": row["listed_date"],
            "last_checked_at": datetime.now().strftime("%Y/%m/%d %H:%M"),
            "note": row["note"],
            "source": row["source"],
        })
        updated += 1
        if r["status"] == "終了":
            ended += 1
    conn.commit()
    conn.close()
    print(f"個別再チェック完了({len(active_rows)}件対象): 更新{updated}件 ／ 新規終了{ended}件 ／ 取得失敗{errors}件")


def cmd_recheck(args):
    settings = load_json(ROOT / "config" / "settings.json")
    accounts = load_json(ROOT / "config" / "accounts.json")
    _recheck(settings, accounts)


def cmd_sync(args):
    settings = load_json(ROOT / "config" / "settings.json")
    conn = db.connect()
    rows = db.get_all(conn)
    conn.close()
    sheets_sync.sync(rows, settings, ROOT)


def cmd_trade(args):
    """ログイン中の出品者(取引ナビ)から、落札後の入金/発送/受け取り状況を取得する。cookies.txtが必要。"""
    settings = load_json(ROOT / "config" / "settings.json")
    accounts = load_json(ROOT / "config" / "accounts.json")
    cookies_path = settings.get("yahoo_cookies_path")
    if not cookies_path or not Path(cookies_path).exists():
        print(f"cookieファイルが見つかりません: {cookies_path}\nsettings.jsonのyahoo_cookies_pathを確認してください。")
        return

    since_str = settings.get("trade_since", "2026-06-01")
    since = date.fromisoformat(since_str)

    rows = asyncio.run(scraper.fetch_won_items(cookies_path, settings, since))
    if not rows:
        print("取引データが取得できませんでした(cookieの期限切れの可能性があります)。")
        return

    surpass_seller_id = "8vYc4d8q5Sa3THmNAC8FZhbU4P8jW"
    account_name = accounts.get(surpass_seller_id, "surpass")

    conn = db.connect()
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    progress_counts = {}
    for r in rows:
        db.upsert_trade_status(conn, {
            "auction_id": r["auction_id"],
            "url": r["url"],
            "account_name": account_name,
            "seller_id": surpass_seller_id,
            "title": r["title"],
            "final_price": r["final_price"],
            "end_datetime": r["end_datetime"],
            "status": "終了",
            "source": "auto",
            "trade_progress": r["trade_progress"],
            "trade_message": r["trade_message"],
            "buyer_id": r["buyer_id"],
            "contact_url": r["contact_url"],
            "last_checked_at": now,
        })
        progress_counts[r["trade_progress"]] = progress_counts.get(r["trade_progress"], 0) + 1
    conn.commit()
    conn.close()

    print(f"取引ステータスを{len(rows)}件更新しました({since_str}以降)")
    for progress, count in progress_counts.items():
        print(f"  - {progress}: {count}件")


def cmd_dashboard(args):
    conn = db.connect()
    rows = db.get_all(conn)
    conn.close()
    dashboard.render(rows, ROOT / "output" / "dashboard.html")


def _print_summary():
    conn = db.connect()
    rows = db.get_all(conn)
    conn.close()
    by_day = {}
    for r in rows:
        by_day.setdefault(r["listed_date"], []).append(r)
    print("\n--- 日別サマリー ---")
    for day in sorted(d for d in by_day if d):
        day_rows = by_day[day]
        total = len(day_rows)
        with_bid = sum(1 for r in day_rows if (r["bid_count"] or 0) > 0)
        rate = (with_bid / total * 100) if total else 0
        print(f"{day}: 出品{total}件 ／ 入札あり{with_bid}件 ／ 入札率{rate:.1f}%")


def cmd_all(args):
    """毎日の自動実行本体: アカウント全体クロール→(未確認分のみ)個別再チェック→Sheets同期→ダッシュボード再生成"""
    settings = load_json(ROOT / "config" / "settings.json")
    accounts = load_json(ROOT / "config" / "accounts.json")
    confirmed_active_ids = _discover(settings, accounts)
    _recheck(settings, accounts, skip_ids=confirmed_active_ids)
    try:
        cmd_trade(args)
    except Exception as e:
        print(f"[警告] 取引ステータス取得をスキップしました: {e}")
    try:
        cmd_sync(args)
    except Exception as e:
        print(f"[警告] Sheets同期をスキップしました: {e}")
    cmd_dashboard(args)
    _print_summary()


COMMANDS = {
    "add": cmd_add,
    "discover": cmd_discover,
    "recheck": cmd_recheck,
    "trade": cmd_trade,
    "sync": cmd_sync,
    "dashboard": cmd_dashboard,
    "all": cmd_all,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"使い方: python3 main.py [{'|'.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
