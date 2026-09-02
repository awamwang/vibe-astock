"""测 SOCKS 代理能否访问 Polymarket / Kalshi。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vr"))
os.environ.setdefault("VR_PULSE_PROXY", "socks5://127.0.0.1:7881")


async def main() -> None:
    from pulse.http_client import make_async_client, pulse_proxy_url

    print("proxy=", pulse_proxy_url(), flush=True)
    async with make_async_client(timeout=45.0) as c:
        r = await c.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": "2",
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        data = r.json() if r.status_code == 200 else None
        n = len(data) if isinstance(data, list) else "?"
        print("polymarket", r.status_code, "n=", n, flush=True)
        r2 = await c.get(
            "https://api.elections.kalshi.com/trade-api/v2/events",
            params={"limit": "2", "status": "open", "with_nested_markets": "true"},
        )
        body = r2.json() if r2.status_code == 200 else {}
        print("kalshi", r2.status_code, "events=", len(body.get("events") or []), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
