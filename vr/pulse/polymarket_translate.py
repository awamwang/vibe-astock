"""预测市场标题英译中（可选）。LLM 不可用时退回纯英文。"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from .paths import get_pulse_data_dir

logger = logging.getLogger(__name__)

_BATCH = 4
_MAX_TOKENS = 4000
_BATCH_DELAY = 0.8
_CACHE: dict[str, str] | None = None


def _cache_path() -> Path:
    return get_pulse_data_dir() / "polymarket_translations.json"


def _load_cache() -> dict[str, str]:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(_cache_path().read_text("utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_CACHE, ensure_ascii=False), "utf-8")
    except OSError as exc:
        logger.warning("pulse translation cache save failed: %s", exc)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _build_llm():
    try:
        from duanxian.config import make_llm  # noqa: PLC0415

        return make_llm(temperature=0.2)
    except Exception:
        return None


async def _translate_batch(questions: list[str]) -> dict[str, str]:
    llm = _build_llm()
    if llm is None:
        return {}

    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    prompt = (
        "把下面的预测市场标题逐条翻译成简洁自然的中文。"
        "保留人名、地名、机构、缩写（如 Fed、GDP、Nvidia、OpenAI）原样。"
        "只返回一个 JSON 对象，key 为序号字符串，value 为中文译文，不要任何解释或代码块标记。\n\n"
        f"{numbered}"
    )
    try:
        bound = llm.bind(max_tokens=_MAX_TOKENS) if hasattr(llm, "bind") else llm
        if hasattr(bound, "ainvoke"):
            resp = await bound.ainvoke(prompt)
        else:
            resp = await asyncio.to_thread(bound.invoke, prompt)
        text = getattr(resp, "content", None) or str(resp)
        data = _extract_json(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pulse translation batch failed: %s", exc)
        return {}

    out: dict[str, str] = {}
    for i, question in enumerate(questions):
        value = data.get(str(i + 1))
        if isinstance(value, str) and value.strip():
            out[question] = value.strip()
    return out


async def _translate_missing(missing: list[str], cache: dict[str, str], max_rounds: int = 6) -> None:
    stalls = 0
    for _ in range(max_rounds):
        remaining = [q for q in missing if q not in cache]
        if not remaining:
            return
        progressed = False
        for i in range(0, len(remaining), _BATCH):
            before = len(cache)
            cache.update(await _translate_batch(remaining[i : i + _BATCH]))
            _save_cache()
            if len(cache) > before:
                progressed = True
            await asyncio.sleep(_BATCH_DELAY)
        stalls = 0 if progressed else stalls + 1
        if stalls >= 2:
            return


async def translate_questions(questions: list[str], llm_timeout: float = 20.0) -> dict[str, str]:
    cache = _load_cache()
    unique = list(dict.fromkeys(q for q in questions if q))
    missing = [q for q in unique if q not in cache]
    if missing:
        try:
            await asyncio.wait_for(_translate_missing(missing, cache), timeout=llm_timeout)
        except Exception:  # noqa: BLE001
            pass
    return {q: cache[q] for q in unique if q in cache}
