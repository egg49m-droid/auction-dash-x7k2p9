import asyncio
import json
import re
from datetime import datetime, timezone, timedelta

import httpx

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
            resp.raise_for_status()
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
