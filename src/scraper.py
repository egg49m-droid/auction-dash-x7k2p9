import asyncio
import http.cookiejar
import json
import re
from datetime import datetime, timezone, timedelta

import httpx
from bs4 import BeautifulSoup

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

JST = timezone(timedelta(hours=9))


def extract_auction_id(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def parse_auction_html(html: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ not found (page structure changed or item removed)")
    data = json.loads(m.group(1))
    detail = data["props"]["pageProps"]["initialState"]["item"]["detail"]["item"]
    seller = detail.get("seller", {})

    end_time_raw = detail.get("endTime")
    end_dt = None
    if end_time_raw:
        end_dt = datetime.fromisoformat(end_time_raw).astimezone(JST)

    start_time_raw = detail.get("startTime")
    start_dt = None
    if start_time_raw:
        start_dt = datetime.fromisoformat(start_time_raw).astimezone(JST)

    status_raw = detail.get("status")
    status = "出品中" if status_raw == "open" else "終了"

    bid_count = detail.get("bids") or 0

    return {
        "auction_id": detail.get("auctionId"),
        "title": detail.get("title"),
        "start_price": detail.get("initPrice"),
        "current_price": detail.get("price"),
        "bid_count": bid_count,
        "has_bid": "あり" if bid_count > 0 else "なし",
        "end_datetime": end_dt.strftime("%Y/%m/%d %H:%M") if end_dt else None,
        "listed_date": start_dt.strftime("%Y/%m/%d") if start_dt else None,
        "status": status,
        "final_price": detail.get("winPrice"),
        "seller_id": seller.get("aucUserId"),
        "seller_display_name": seller.get("displayName"),
    }


async def fetch_one(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> dict:
    auction_id = extract_auction_id(url)
    async with semaphore:
        try:
            resp = await client.get(url)
            # Yahoo returns 404 for some ended (no-bid) auctions while still rendering the full item JSON,
            # so parse first and only treat it as a hard failure if parsing also fails.
            if resp.status_code >= 400:
                try:
                    parsed = parse_auction_html(resp.text)
                except ValueError:
                    resp.raise_for_status()
                    raise
            else:
                parsed = parse_auction_html(resp.text)
            parsed["url"] = url
            parsed["error"] = None
            return parsed
        except Exception as e:
            return {"auction_id": auction_id, "url": url, "error": str(e)}


async def fetch_many(urls: list[str], settings: dict) -> list[dict]:
    semaphore = asyncio.Semaphore(settings.get("request_concurrency", 5))
    timeout = settings.get("request_timeout_seconds", 15)
    headers = {"User-Agent": settings.get("user_agent", "yahoo-auction-tracker/1.0")}
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        tasks = [fetch_one(client, url, semaphore) for url in urls]
        return await asyncio.gather(*tasks)


def resolve_account_name(seller_id: str, accounts: dict) -> str:
    return accounts.get(seller_id, "要確認")


def extract_staff_mark(title: str):
    """商品名の先頭1文字（■♪▲◇◎など）を現場担当者の識別記号として抽出する。"""
    title = (title or "").strip()
    return title[0] if title else None


def _parse_seller_page(html: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ not found on seller page")
    data = json.loads(m.group(1))
    return data["props"]["pageProps"]["initialState"]["search"]["items"]["listing"]


def _listing_item_to_row(item: dict) -> dict:
    start_dt = datetime.fromisoformat(item["startTime"]).astimezone(JST) if item.get("startTime") else None
    end_dt = datetime.fromisoformat(item["endTime"]).astimezone(JST) if item.get("endTime") else None
    bid_count = item.get("bidCount") or 0
    return {
        "auction_id": item["auctionId"],
        "url": f"https://auctions.yahoo.co.jp/jp/auction/{item['auctionId']}",
        "seller_id": item.get("seller", {}).get("userId"),
        "title": item.get("title"),
        "start_price": item.get("initPriceNoTax"),
        "current_price": item.get("price"),
        "bid_count": bid_count,
        "has_bid": "あり" if bid_count > 0 else "なし",
        "end_datetime": end_dt.strftime("%Y/%m/%d %H:%M") if end_dt else None,
        "status": "出品中",
        "final_price": None,
        "listed_date": start_dt.strftime("%Y/%m/%d") if start_dt else None,
        "start_datetime": start_dt,
    }


async def fetch_seller_listings(client: httpx.AsyncClient, seller_id: str, semaphore: asyncio.Semaphore) -> list[dict]:
    """Fetches every active listing for a seller (paginated, 50/page)."""
    results = []
    offset = 1
    page_size = 50
    while True:
        url = f"https://auctions.yahoo.co.jp/seller/{seller_id}?select=1&b={offset}"
        async with semaphore:
            resp = await client.get(url)
            resp.raise_for_status()
        listing = _parse_seller_page(resp.text)
        items = listing.get("items", [])
        results.extend(_listing_item_to_row(it) for it in items)
        total = listing.get("totalResultsAvailable", len(results))
        if offset + page_size > total or not items:
            break
        offset += page_size
    return results


async def fetch_all_seller_listings(seller_ids: list[str], settings: dict) -> dict:
    """Returns {seller_id: [row, ...]}."""
    semaphore = asyncio.Semaphore(settings.get("request_concurrency", 5))
    timeout = settings.get("request_timeout_seconds", 15)
    headers = {"User-Agent": settings.get("user_agent", "yahoo-auction-tracker/1.0")}
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True) as client:
        tasks = {sid: fetch_seller_listings(client, sid, semaphore) for sid in seller_ids}
        values = await asyncio.gather(*tasks.values())
        return dict(zip(tasks.keys(), values))


def load_yahoo_cookies(cookies_path: str) -> httpx.Cookies:
    cj = http.cookiejar.MozillaCookieJar(cookies_path)
    cj.load(ignore_discard=True, ignore_expires=True)
    cookies = httpx.Cookies()
    for c in cj:
        cookies.set(c.name, c.value, domain=c.domain, path=c.path)
    return cookies


def _trade_item_to_row(item: dict) -> dict:
    end_dt = datetime.fromisoformat(item["endTime"]).astimezone(JST) if item.get("endTime") else None
    sold = item.get("soldInfo", {})
    trade = sold.get("trade", {})
    winner = sold.get("winner", {})
    return {
        "auction_id": item["auctionId"],
        "url": item.get("itemUrl"),
        "title": item.get("title"),
        "final_price": item.get("price"),
        "end_datetime": end_dt.strftime("%Y/%m/%d %H:%M") if end_dt else None,
        "end_date": end_dt.date() if end_dt else None,
        "trade_progress": trade.get("progress"),
        "trade_message": trade.get("message"),
        "buyer_id": winner.get("aucUserId"),
        "contact_url": winner.get("contactUrl"),
    }


def _unsold_item_to_row(item: dict) -> dict:
    end_dt = datetime.fromisoformat(item["endTime"]).astimezone(JST) if item.get("endTime") else None
    return {
        "auction_id": item["auctionId"],
        "url": item.get("itemUrl"),
        "title": item.get("title"),
        "final_price": None,
        "end_datetime": end_dt.strftime("%Y/%m/%d %H:%M") if end_dt else None,
        "end_date": end_dt.date() if end_dt else None,
        "trade_progress": "NO_WINNER",
        "trade_message": None,
        "buyer_id": None,
        "contact_url": None,
    }


async def _fetch_closed_items(cookies_path: str, settings: dict, since, sold: bool, item_mapper) -> list[dict]:
    """Fetches the logged-in seller's closed items (paginated), stopping once endTime < since."""
    cookies = load_yahoo_cookies(cookies_path)
    headers = {"User-Agent": settings.get("user_agent", "yahoo-auction-tracker/1.0")}
    timeout = settings.get("request_timeout_seconds", 15)
    sold_param = "true" if sold else "false"
    results = []
    offset = 0
    page_size = 50
    async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=timeout, follow_redirects=True) as client:
        while True:
            url = f"https://auctions.yahoo.co.jp/api/myauction/v1/myauction/items/closed?limit={page_size}&offset={offset}&sold={sold_param}"
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            reached_cutoff = False
            for item in items:
                row = item_mapper(item)
                if row["end_date"] and row["end_date"] < since:
                    reached_cutoff = True
                    break
                results.append(row)
            if reached_cutoff:
                break
            total = data.get("totalResultsAvailable", len(results))
            offset += page_size
            if offset >= total:
                break
    return results


async def fetch_won_items(cookies_path: str, settings: dict, since) -> list[dict]:
    """Fetches the logged-in seller's closed & sold (has a winner) items."""
    return await _fetch_closed_items(cookies_path, settings, since, sold=True, item_mapper=_trade_item_to_row)


async def fetch_unsold_items(cookies_path: str, settings: dict, since) -> list[dict]:
    """Fetches the logged-in seller's closed & unsold (no winner) items."""
    return await _fetch_closed_items(cookies_path, settings, since, sold=False, item_mapper=_unsold_item_to_row)


def parse_contact_page(html: str) -> dict:
    """取引ナビ(お届け情報)ページから、お届け先氏名・住所・配送方法・追跡番号を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    result = {"recipient_name": None, "recipient_address": None, "shipping_method": None, "tracking_number": None}
    label_map = {
        "氏名": "recipient_name",
        "住所": "recipient_address",
        "配送方法": "shipping_method",
        "追跡番号": "tracking_number",
    }
    for block in soup.select(".libTableCnfTop"):
        header = block.find("div", class_="decThWrp")
        if not header or "お届け情報" not in header.get_text():
            continue
        for tr in block.select(".libTableCnf table tr"):
            th, td = tr.find("th"), tr.find("td")
            if not th or not td:
                continue
            key = label_map.get(th.get_text(strip=True))
            if key:
                result[key] = " ".join(td.get_text(" ", strip=True).split())
        break
    return result


def parse_payment_deadline(html: str):
    """取引ナビの「かんたん決済支払期限」表示から、支払い期日(YYYY/MM/DD)を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.find("div", class_="PayDeadline__text")
    if not el:
        return None
    m = re.search(r"(\d{1,2})月(\d{1,2})日", el.get_text())
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    today = datetime.now(JST).date()
    year = today.year
    if month < today.month - 6:  # 年またぎ(12月→1月など)の簡易対応
        year += 1
    return f"{year}/{month:02d}/{day:02d}"


async def fetch_contact_info(client: httpx.AsyncClient, contact_url: str, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        try:
            resp = await client.get(contact_url)
            resp.raise_for_status()
            return {
                "contact_url": contact_url,
                **parse_contact_page(resp.text),
                "payment_deadline": parse_payment_deadline(resp.text),
                "error": None,
            }
        except Exception as e:
            return {"contact_url": contact_url, "error": str(e)}


async def fetch_contact_info_many(cookies_path: str, settings: dict, contact_urls: list[str]) -> list[dict]:
    cookies = load_yahoo_cookies(cookies_path)
    headers = {"User-Agent": settings.get("user_agent", "yahoo-auction-tracker/1.0")}
    timeout = settings.get("request_timeout_seconds", 15)
    semaphore = asyncio.Semaphore(settings.get("request_concurrency", 5))
    async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=timeout, follow_redirects=True) as client:
        tasks = [fetch_contact_info(client, url, semaphore) for url in contact_urls]
        return await asyncio.gather(*tasks)
