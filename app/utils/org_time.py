"""Bot timezone: prefer organization setting from API, fallback Asia/Bangkok."""

from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.api_client import ApiClient

DEFAULT_TIMEZONE = 'Asia/Bangkok'
_cache: dict[int, tuple[float, str]] = {}
_CACHE_TTL_SEC = 300.0


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


async def get_org_timezone(api: ApiClient, tg_id: int) -> str:
    now = time.monotonic()
    cached = _cache.get(tg_id)
    if cached and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]
    try:
        data = await api.get_org_settings(tg_id)
        tz = str((data or {}).get('timezone') or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    except Exception:
        tz = DEFAULT_TIMEZONE
    _cache[tg_id] = (now, tz)
    return tz


async def now_in_org(api: ApiClient, tg_id: int) -> datetime:
    tz = await get_org_timezone(api, tg_id)
    return datetime.now(_zone(tz)).replace(tzinfo=None)


async def today_in_org(api: ApiClient, tg_id: int) -> date:
    return (await now_in_org(api, tg_id)).date()
