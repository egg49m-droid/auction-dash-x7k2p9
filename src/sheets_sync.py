import time
from datetime import datetime
from pathlib import Path

import gspread
from gspread.exceptions import WorksheetNotFound
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from src.scraper import extract_staff_mark

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADER = [
    "出品日", "アカウント名", "記号", "オークションID", "URL", "商品名",
    "現在価格", "入札件数", "入札有無", "終了日時",
    "ステータス", "落札金額", "お届け先氏名", "お届け先住所", "配送方法", "追跡番号",
    "備考",
]

TRADE_LABELS = {
    "ADDRESS_INPUTING": "落札者からの連絡待ちです(入金待ち)",
    "MONEY_RECEIVED": "落札者からの入金待ちです(銀行振込等・要確認)",
    "PREPARATION_FOR_SHIPMENT": "発送をしてください(発送待ち・要対応)",
    "SHIPPING": "発送完了しました(受け取り待ち)",
    "COMPLETE": "受け取り連絡がされました(着金)",
}
TRADE_ERROR_LABEL = "取引状況を確認してください(要確認)"

TRADE_TRACKED_ACCOUNTS = {"surpass"}  # ログインで取引ナビ全件を把握できているアカウント


def _has_trade_coverage(row) -> bool:
    return row["account_name"] in TRADE_TRACKED_ACCOUNTS


def _has_real_trade_progress(row) -> bool:
    return bool(row["trade_progress"]) and row["trade_progress"] != "NO_WINNER"


def _is_won(row) -> bool:
    if row["status"] == "出品中":
        return False
    if _has_trade_coverage(row):
        return _has_real_trade_progress(row)
    return _has_real_trade_progress(row) or (row["bid_count"] or 0) > 0


def _is_mistake_listing(row) -> bool:
    """未落札のうち、出品日から1日以内に終了している商品は出品ミス(重複出品など)の疑いが強い。"""
    if row["status"] == "出品中" or _is_won(row):
        return False
    if not row["listed_date"] or not row["end_datetime"]:
        return False
    try:
        start = datetime.strptime(row["listed_date"], "%Y/%m/%d")
        end = datetime.strptime(row["end_datetime"][:10], "%Y/%m/%d")
    except ValueError:
        return False
    return (end - start).days <= 1


def _combined_status(row) -> str:
    if row["status"] == "出品中":
        return "出品中"
    if _is_mistake_listing(row):
        return "出品ミス(重複の疑い・要確認)"
    if row["trade_progress"] == "NO_WINNER":
        return "未落札"
    trade_progress = row["trade_progress"]
    if trade_progress:
        if trade_progress == "ADDRESS_INPUTING" and row["payment_overdue"]:
            return f"入金期限切れ(要対応・期日: {row['payment_deadline'] or '-'})"
        label = TRADE_LABELS.get(trade_progress, TRADE_ERROR_LABEL)
        if trade_progress == "ADDRESS_INPUTING" and row["payment_deadline"]:
            label += f"(期日: {row['payment_deadline']})"
        return label
    if _has_trade_coverage(row):
        return "未落札"  # 取引ナビに記録がない＝入札件数が残っていても実際は未落札
    if not (row["bid_count"] or 0) > 0:
        return "未落札"
    return "終了"


def _effective_bid_count(row):
    if row["status"] != "出品中" and _has_trade_coverage(row) and not _has_real_trade_progress(row):
        return 0
    return row["bid_count"]


def _row_to_values(row) -> list:
    bid_count = _effective_bid_count(row)
    has_bid = "あり" if (bid_count or 0) > 0 else "なし"
    return [
        row["listed_date"], row["account_name"], extract_staff_mark(row["title"]),
        row["auction_id"], row["url"], row["title"],
        row["current_price"], bid_count, has_bid,
        row["end_datetime"], _combined_status(row), row["final_price"],
        row["recipient_name"], row["recipient_address"], row["shipping_method"], row["tracking_number"],
        row["note"],
    ]


def _get_credentials(settings: dict, project_root: Path) -> Credentials:
    client_path = project_root / settings["oauth_client_path"]
    token_path = project_root / settings["oauth_token_path"]

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if not client_path.exists():
        raise FileNotFoundError(
            f"OAuthクライアントのJSONが見つかりません: {client_path}\n"
            "Google CloudでOAuthクライアントID（デスクトップアプリ）を作成し、JSONをこのパスに配置してください。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _get_or_create_worksheet(sh, title: str, cols: int):
    try:
        return sh.worksheet(title)
    except WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=1000, cols=cols)


def sync(rows, settings: dict, project_root: Path, max_retries: int = 2):
    values = [HEADER] + [_row_to_values(r) for r in rows]

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            creds = _get_credentials(settings, project_root)
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(settings["spreadsheet_id"])
            ws = _get_or_create_worksheet(sh, settings["sheet_name"], cols=len(HEADER))
            ws.clear()
            ws.update(values, value_input_option="USER_ENTERED")
            print(f"Google Sheetsへ{len(rows)}件を反映しました。")
            return
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 5 * (attempt + 1)
                print(f"[警告] Sheets同期に失敗({e})。{wait}秒後にリトライします({attempt + 1}/{max_retries})。")
                time.sleep(wait)
    raise last_error
