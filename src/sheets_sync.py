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
    "PREPARATION_FOR_SHIPMENT": "発送をしてください(発送待ち・要対応)",
    "SHIPPING": "発送完了しました(受け取り待ち)",
    "COMPLETE": "受け取り連絡がされました(着金)",
}
TRADE_ERROR_LABEL = "取引状況を確認してください(要確認)"


def _combined_status(row) -> str:
    if row["status"] == "出品中":
        return "出品中"
    trade_progress = row["trade_progress"]
    if trade_progress:
        return TRADE_LABELS.get(trade_progress, TRADE_ERROR_LABEL)
    if not (row["bid_count"] or 0) > 0:
        return "未落札"
    return "終了"


def _row_to_values(row) -> list:
    return [
        row["listed_date"], row["account_name"], extract_staff_mark(row["title"]),
        row["auction_id"], row["url"], row["title"],
        row["current_price"], row["bid_count"], row["has_bid"],
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


def sync(rows, settings: dict, project_root: Path):
    creds = _get_credentials(settings, project_root)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(settings["spreadsheet_id"])
    ws = _get_or_create_worksheet(sh, settings["sheet_name"], cols=len(HEADER))

    values = [HEADER] + [_row_to_values(r) for r in rows]
    ws.clear()
    ws.update(values, value_input_option="USER_ENTERED")
    print(f"Google Sheetsへ{len(rows)}件を反映しました。")
