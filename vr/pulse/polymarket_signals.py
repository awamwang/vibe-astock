"""Polymarket 公开 API 拉取与整形。只读、免登录。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"
CLOB_HISTORY_URL = "https://clob.polymarket.com/prices-history"

_TTL_SECONDS = 300
_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < _TTL_SECONDS:
        return hit[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _CACHE[key] = (time.time(), value)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_json_field(raw: Any, default: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default
    return raw if raw is not None else default


def _shape(market: dict[str, Any], topic: str) -> dict[str, Any]:
    outcomes = _parse_json_field(market.get("outcomes"), [])
    prices = _parse_json_field(market.get("outcomePrices"), [])
    token_ids = _parse_json_field(market.get("clobTokenIds"), [])
    return {
        "question": market.get("question"),
        "question_zh": None,
        "topic": topic,
        "outcomes": outcomes,
        "prices": [_safe_float(p) for p in prices],
        "prob_yes": _safe_float(prices[0]) if prices else None,
        "pick_label": None,
        "change_24h": _safe_float(market.get("oneDayPriceChange")),
        "change_7d": _safe_float(market.get("oneWeekPriceChange")),
        "volume_24h": _safe_float(market.get("volume24hr")),
        "liquidity": _safe_float(market.get("liquidity")),
        "end_date": market.get("endDateIso") or market.get("endDate"),
        "slug": market.get("slug"),
        "token_id_yes": token_ids[0] if token_ids else None,
        "source": "polymarket",
    }


async def pull_raw_markets(pages: int = 3, force: bool = False) -> list[dict[str, Any]]:
    cache_key = f"markets:{pages}"
    raw = None if force else _cache_get(cache_key)
    if raw is not None:
        return raw
    raw_list: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (vibe-astock)"}
    async with httpx.AsyncClient(timeout=45.0, headers=headers) as client:
        for page in range(pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": "100",
                "offset": str(page * 100),
                "order": "volume24hr",
                "ascending": "false",
            }
            batch: list[dict[str, Any]] | None = None
            for attempt in range(3):
                try:
                    resp = await client.get(GAMMA_MARKETS_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, list):
                        batch = data
                    elif isinstance(data, dict):
                        batch = data.get("data") or []
                    else:
                        batch = []
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("polymarket page %d attempt %d: %s", page, attempt, exc)
                    await asyncio.sleep(1.0 * (attempt + 1))
            if batch is None:
                break
            if not batch:
                break
            for market in batch:
                mid = market.get("id")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    raw_list.append(market)
    if raw_list:
        _cache_set(cache_key, raw_list)
    return raw_list


async def fetch_history(token_id: str, interval: str = "1w", fidelity: int = 720) -> list[dict[str, Any]]:
    cache_key = f"history:{token_id}:{interval}:{fidelity}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    params = {"market": token_id, "interval": interval, "fidelity": str(fidelity)}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            CLOB_HISTORY_URL,
            params=params,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    history = data.get("history", []) if isinstance(data, dict) else []
    points = [{"t": p.get("t"), "p": _safe_float(p.get("p"))} for p in history]
    _cache_set(cache_key, points)
    return points
