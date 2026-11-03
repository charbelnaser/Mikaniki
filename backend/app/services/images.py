"""
Web photos under the mechanic's answers ("where is the ignition coil on a 2016 Corolla").

Provider chosen by IMAGE_SEARCH_PROVIDER:
- google: Programmable Search (Custom Search JSON API, searchType=image) - GOOGLE_CSE_KEY + GOOGLE_CSE_ID.
  Closed to new customers and shut down on 2027-01-01; the engine only searches its listed sites.
- brave:  Brave Search API image search - BRAVE_API_KEY.

Only thumbnails are shown, each linking to the page it comes from with the site name, like a search engine.
Results are cached in memory, so a repeated query costs one call per process per TTL, and at most
IMAGE_SEARCH_DAILY_LIMIT calls are made per day (the counter lives in memory and restarts with the
process, so also set a monthly limit in the provider's dashboard).
"""

import time
from dataclasses import dataclass
from datetime import date

import httpx

from ..config import get_settings

GOOGLE = "https://www.googleapis.com/customsearch/v1"
BRAVE = "https://api.search.brave.com/res/v1/images/search"
TIMEOUT = 8
_TTL = 60 * 60 * 24 * 7

_cache: dict[str, tuple[float, list["WebImage"]]] = {}
_calls = {"day": date.min, "count": 0}  # paid calls made today


@dataclass
class WebImage:
    thumb_url: str
    page_url: str      # page the photo comes from (always linked)
    source: str        # its site, shown as the credit
    title: str | None


def enabled() -> bool:
    s = get_settings()
    return (s.image_search_provider == "google" and bool(s.google_cse_key and s.google_cse_id)) or \
           (s.image_search_provider == "brave" and bool(s.brave_api_key))


def parse_google(data: dict) -> list[WebImage]:
    out = []
    for item in data.get("items") or []:
        image = item.get("image") or {}
        thumb, page = image.get("thumbnailLink"), image.get("contextLink")
        if thumb and page:
            out.append(WebImage(thumb_url=thumb, page_url=page, source=item.get("displayLink") or "",
                                title=item.get("title")))
    return out


def parse_brave(data: dict) -> list[WebImage]:
    out = []
    for item in data.get("results") or []:
        thumb, page = (item.get("thumbnail") or {}).get("src"), item.get("url")
        if thumb and page:
            out.append(WebImage(thumb_url=thumb, page_url=page, source=item.get("source") or "",
                                title=item.get("title")))
    return out


async def search(query: str, count: int = 4) -> list[WebImage]:
    """Up to `count` photos, [] when no provider is configured. Raises httpx.HTTPError when unreachable."""
    if not enabled():
        return []
    s = get_settings()
    key = f"{s.image_search_provider}:{count}:{query.strip().lower()}"
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    if _calls["day"] != date.today():
        _calls.update(day=date.today(), count=0)
    if _calls["count"] >= s.image_search_daily_limit:
        return []  # daily budget used: no photos until tomorrow (diagrams and links still show)
    _calls["count"] += 1
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        if s.image_search_provider == "google":
            r = await client.get(GOOGLE, params={"key": s.google_cse_key, "cx": s.google_cse_id, "q": query,
                                                 "searchType": "image", "num": count, "safe": "active"})
            r.raise_for_status()
            result = parse_google(r.json())
        else:
            r = await client.get(BRAVE, params={"q": query, "count": count, "safesearch": "strict"},
                                 headers={"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"})
            r.raise_for_status()
            result = parse_brave(r.json())
    _cache[key] = (time.time() + _TTL, result[:count])
    return result[:count]
