"""多源概率总览聚合：分类、合并、快照、异步刷新。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from . import kalshi_signals, market_taxonomy, polymarket_signals
from .paths import get_pulse_data_dir

logger = logging.getLogger(__name__)

_rebuilding = False


def _snapshot_path() -> Path:
    return get_pulse_data_dir() / "pulse_snapshot.json"


def _load_snapshot() -> dict[str, Any] | None:
    try:
        data = json.loads(_snapshot_path().read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, ValueError, OSError):
        return None


def _save_snapshot(overview: dict[str, Any]) -> None:
    try:
        path = _snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(overview, ensure_ascii=False), "utf-8")
    except OSError as exc:
        logger.warning("pulse snapshot save failed: %s", exc)


async def _shaped_polymarket(force: bool) -> list[dict[str, Any]]:
    raw = await polymarket_signals.pull_raw_markets(pages=3, force=force)
    shaped: list[dict[str, Any]] = []
    for market in raw:
        question = market.get("question") or ""
        module = market_taxonomy.classify(question)
        row = polymarket_signals._shape(market, module)
        row["source"] = "polymarket"
        shaped.append(row)
    return shaped


def _group_by_module(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {m: [] for m in market_taxonomy.MODULES}
    for market in markets:
        module = market.get("topic")
        buckets.setdefault(module, []).append(market)

    modules: list[dict[str, Any]] = []
    for key in market_taxonomy.MODULES:
        group = buckets.get(key, [])
        group.sort(key=lambda m: m.get("volume_24h") or 0.0, reverse=True)
        cap = market_taxonomy.MODULE_CAPS.get(key)
        if cap is not None:
            group = group[:cap]
        if not group:
            continue
        source_counts: dict[str, int] = {}
        for market in group:
            src = market.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        modules.append({
            "key": key,
            "core": key in market_taxonomy.CORE_SET,
            "market_count": len(group),
            "volume_24h": sum(m.get("volume_24h") or 0.0 for m in group),
            "source_counts": source_counts,
            "markets": group,
        })
    return modules


def _pick_highlights(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """短线盘面卡片用：从核心模块抽少量高成交合约。"""
    want_topics = ("货币政策", "地缘政治", "AI科技", "加密")
    by_topic = {m["key"]: m for m in modules}
    out: list[dict[str, Any]] = []
    for topic in want_topics:
        group = by_topic.get(topic)
        if not group:
            continue
        for m in group.get("markets") or []:
            if m.get("prob_yes") is None:
                continue
            out.append({
                "key": f"{m.get('source')}:{m.get('slug') or m.get('question')}",
                "topic": topic,
                "title": m.get("question_zh") or m.get("question"),
                "title_en": m.get("question"),
                "pick_label": m.get("pick_label"),
                "prob_yes": m.get("prob_yes"),
                "change_24h": m.get("change_24h"),
                "volume_24h": m.get("volume_24h"),
                "source": m.get("source"),
            })
            break  # 每模块取成交最高一条
    return out


def _build_summary(modules: list[dict[str, Any]], highlights: list[dict[str, Any]]) -> str:
    """一两句中文温度计描述，给短线盘面展示。"""
    bits: list[str] = []
    for h in highlights:
        if h.get("topic") != "货币政策":
            continue
        q = (h.get("title_en") or h.get("title") or "").lower()
        p = h.get("prob_yes")
        if p is None:
            continue
        pct = round(p * 100, 1)
        if "no change" in q or "unchanged" in q:
            bits.append(f"Fed 下次按兵不动约 {pct}%")
        elif "decrease" in q or "cut" in q:
            bits.append(f"Fed 降息约 {pct}%")
        elif "increase" in q or "hike" in q:
            bits.append(f"Fed 加息约 {pct}%")
        else:
            bits.append(f"货币政策关注合约约 {pct}%")
        break
    for h in highlights:
        if h.get("topic") != "地缘政治":
            continue
        p = h.get("prob_yes")
        if p is None:
            continue
        title = h.get("title") or h.get("title_en") or "地缘事件"
        bits.append(f"地缘热门「{title[:28]}」约 {round(p * 100, 1)}%")
        break
    if not bits:
        core_n = sum(1 for m in modules if m.get("core"))
        bits.append(f"已归类 {core_n} 个核心宏观模块；价格即集体下注概率，非买卖信号。")
    else:
        bits.append("预测市场价格=概率，作外围情绪对照，非交易建议。")
    return "；".join(bits)


async def _translate(markets: list[dict[str, Any]]) -> None:
    try:
        from .polymarket_translate import translate_questions

        questions = [m["question"] for m in markets if m.get("question")]
        # 短线盘面只要 highlights，翻译预算收紧，避免拖垮重建
        zh_map = await translate_questions(questions[:40], llm_timeout=60.0)
        for market in markets:
            market["question_zh"] = zh_map.get(market.get("question"))
    except Exception:  # noqa: BLE001
        pass


async def _build() -> dict[str, Any]:
    pm, ks = await asyncio.gather(
        _shaped_polymarket(force=True),
        kalshi_signals.fetch_shaped(force=True),
    )
    merged = pm + ks
    if not merged:
        prev = _load_snapshot()
        if prev:
            logger.warning("pulse rebuild empty; keeping previous snapshot")
            return prev
    await _translate(merged)
    modules = _group_by_module(merged)
    highlights = _pick_highlights(modules)
    overview = {
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "sources": ["polymarket", "kalshi"],
        "module_order": market_taxonomy.MODULES,
        "core_modules": market_taxonomy.CORE_MODULES,
        "modules": modules,
        "highlights": highlights,
        "summary": _build_summary(modules, highlights),
    }
    _save_snapshot(overview)
    return overview


async def _background_rebuild() -> None:
    global _rebuilding
    try:
        await _build()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pulse background rebuild failed: %s", exc)
    finally:
        _rebuilding = False


def _empty_updating() -> dict[str, Any]:
    return {
        "as_of": None,
        "sources": ["polymarket", "kalshi"],
        "modules": [],
        "highlights": [],
        "summary": "正在拉取 Polymarket / Kalshi 公开概率（首次较慢）…",
        "updating": True,
    }


async def fetch_overview(force: bool = False) -> dict[str, Any]:
    """正常读盘上快照；无快照或 force 时后台重建，立刻返回（不阻塞短线盘面）。"""
    global _rebuilding
    snap = _load_snapshot()

    if snap is None:
        if not _rebuilding:
            _rebuilding = True
            asyncio.create_task(_background_rebuild())
        return _empty_updating()

    # 兼容旧快照：补 highlights / summary
    if "highlights" not in snap:
        mods = snap.get("modules") or []
        snap["highlights"] = _pick_highlights(mods)
        snap["summary"] = _build_summary(mods, snap["highlights"])

    if force and not _rebuilding:
        _rebuilding = True
        asyncio.create_task(_background_rebuild())

    if force or _rebuilding:
        return {**snap, "updating": True}
    return snap
