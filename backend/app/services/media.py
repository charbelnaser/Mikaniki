"""
Pictures and videos shown under the mechanic's answers.

- Part photos: Wikimedia Commons (free licences; the credit is returned and must be displayed).
  Generic photos of the part type, not of the user's exact car.
- Repair videos: YouTube Data API v3 (optional, needs YOUTUBE_API_KEY; ~100 searches/day free).
  Shown through the official embedded player. Without a key the frontend links to a YouTube search.

Both are cached in memory, so the same part / query costs one call per process per TTL.
"""

import re
import time
from dataclasses import dataclass
from html import unescape

import httpx

from ..config import get_settings

COMMONS = "https://commons.wikimedia.org/w/api.php"
YOUTUBE = "https://www.googleapis.com/youtube/v3/search"
TIMEOUT = 8
_TTL = 60 * 60 * 24 * 7

_cache: dict[str, tuple[float, object]] = {}


@dataclass
class PartPhoto:
    thumb_url: str
    page_url: str            # Commons file page (licence details)
    author: str | None
    license: str | None


@dataclass
class Video:
    video_id: str
    title: str
    channel: str | None


def _commons_headers() -> dict[str, str]:
    """Wikimedia blocks (403) API clients whose User-Agent has no contact (email or URL): WIKIMEDIA_CONTACT."""
    contact = get_settings().wikimedia_contact or "contact not configured"
    return {"User-Agent": f"Mikaniki/0.1 ({contact})"}


def _cached(key: str):
    hit = _cache.get(key)
    return hit[1] if hit and hit[0] > time.time() else None


def _store(key: str, value):
    _cache[key] = (time.time() + _TTL, value)
    return value


def _text(html: str | None) -> str | None:
    """Commons metadata is HTML ('<a href=...>Sonett72</a> at ...'): keep the text only."""
    if not html:
        return None
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split()) or None


def parse_commons(data: dict) -> PartPhoto | None:
    """Most relevant result that has a thumbnail and a known licence."""
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_ = _text((meta.get("LicenseShortName") or {}).get("value"))
        if info.get("thumburl") and license_:
            return PartPhoto(
                thumb_url=info["thumburl"], page_url=info.get("descriptionurl") or "",
                author=_text((meta.get("Artist") or {}).get("value")), license=license_,
            )
    return None


async def part_photo(part: str) -> PartPhoto | None:
    """Generic photo of a car part (English name, e.g. 'ignition coil'). Raises httpx.HTTPError if unreachable."""
    key = f"photo:{part.lower()}"
    if (hit := _cached(key)) is not None:
        return hit or None
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": f"{part} car filetype:bitmap", "gsrlimit": 5, "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": 400, "iiextmetadatafilter": "Artist|LicenseShortName",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=_commons_headers()) as client:
        r = await client.get(COMMONS, params=params)
        r.raise_for_status()
        photo = parse_commons(r.json())
    if photo is None:  # retry without "car": some parts are only filed under their own name
        params["gsrsearch"] = f"{part} filetype:bitmap"
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=_commons_headers()) as client:
            r = await client.get(COMMONS, params=params)
            r.raise_for_status()
            photo = parse_commons(r.json())
    _store(key, photo or False)
    return photo


async def repair_video(query: str) -> Video | None:
    """Top embeddable YouTube video, or None without YOUTUBE_API_KEY. Raises httpx.HTTPError if unreachable."""
    api_key = get_settings().youtube_api_key
    if not api_key:
        return None
    key = f"video:{query.lower()}"
    if (hit := _cached(key)) is not None:
        return hit or None
    params = {"part": "snippet", "type": "video", "videoEmbeddable": "true", "maxResults": 1,
              "q": query, "key": api_key}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(YOUTUBE, params=params)
        r.raise_for_status()
        items = r.json().get("items") or []
    video = None
    if items and (vid := (items[0].get("id") or {}).get("videoId")):
        snippet = items[0].get("snippet") or {}
        video = Video(video_id=vid, title=unescape(snippet.get("title") or ""), channel=snippet.get("channelTitle"))
    _store(key, video or False)
    return video
