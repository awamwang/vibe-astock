"""一次性拉取 GlobalPercent 最新概览并打印温度计摘要。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vr"))

# 未显式设置时默认本机 SOCKS（可用 VR_PULSE_PROXY 覆盖）
os.environ.setdefault("VR_PULSE_PROXY", "socks5://127.0.0.1:7881")


async def main() -> None:
    from pulse.http_client import pulse_proxy_url
    from pulse.market_pulse import _build, fetch_overview

    print(f"proxy: {pulse_proxy_url()}", flush=True)
    print("开始重建（Polymarket ∥ Kalshi，可能需数分钟）…", flush=True)
    overview = await _build()
    snap = await fetch_overview(force=False)

    as_of = overview.get("as_of") or snap.get("as_of")
    summary = overview.get("summary") or snap.get("summary")
    highlights = overview.get("highlights") or snap.get("highlights") or []
    modules = overview.get("modules") or snap.get("modules") or []

    print(f"\nas_of: {as_of}")
    print(f"summary: {summary}")
    print(f"modules: {len(modules)}  highlights: {len(highlights)}")
    print("\n=== Highlights ===")
    for h in highlights:
        p = h.get("prob_yes")
        pct = f"{p * 100:.1f}%" if isinstance(p, (int, float)) else "—"
        chg = h.get("change_24h")
        chg_s = f" ({chg * 100:+.1f}pt)" if isinstance(chg, (int, float)) and chg else ""
        title = h.get("title") or h.get("title_en") or ""
        pick = f" · 档位 {h.get('pick_label')}" if h.get("pick_label") else ""
        print(f"[{h.get('topic')}] {pct}{chg_s}  {title}{pick}  ({h.get('source')})")

    print("\n=== Modules (top by volume) ===")
    for m in modules:
        core = "core" if m.get("core") else "ref"
        sc = m.get("source_counts") or {}
        print(
            f"{m.get('key')} [{core}] n={m.get('market_count')} "
            f"vol24h={m.get('volume_24h') or 0:.0f} sources={sc}"
        )
        for row in (m.get("markets") or [])[:3]:
            p = row.get("prob_yes")
            pct = f"{p * 100:.1f}%" if isinstance(p, (int, float)) else "—"
            q = row.get("question_zh") or row.get("question") or ""
            pick = f" | {row.get('pick_label')}" if row.get("pick_label") else ""
            print(f"  - {pct}  {q[:72]}{pick}  ({row.get('source')})")

    out = ROOT / "scripts" / "_pulse_latest.json"
    out.write_text(json.dumps(overview, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n完整 JSON 已写: {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
