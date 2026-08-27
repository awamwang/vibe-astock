"""临时脚本：测试 ths-linker WebSocket 连通性与 stock_code 推送。"""
from __future__ import annotations

import json
import os
import sys
import time

try:
    import websocket
except ImportError:
    print("需要 websocket-client: pip install websocket-client")
    sys.exit(1)

URL = os.environ.get("THS_LINKER_WS_URL", "ws://127.0.0.1:8765")


def main() -> int:
    print(f"连接 {URL} …")
    try:
        ws = websocket.create_connection(URL, timeout=5)
    except Exception as exc:
        print(f"连接失败: {type(exc).__name__}: {exc}")
        return 2
    ws.settimeout(3.0)
    msgs: list[dict] = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and len(msgs) < 8:
        try:
            raw = ws.recv()
            msgs.append(json.loads(raw))
        except websocket.WebSocketTimeoutException:
            break
        except Exception as exc:
            print(f"接收异常: {type(exc).__name__}: {exc}")
            break
    ws.send(json.dumps({"type": "stock_code", "action": "get"}, ensure_ascii=False))
    try:
        raw = ws.recv()
        msgs.append(json.loads(raw))
    except Exception as exc:
        print(f"get 响应失败: {type(exc).__name__}: {exc}")
    ws.close()
    print(f"共收到 {len(msgs)} 条消息:")
    for i, m in enumerate(msgs, 1):
        print(f"--- [{i}] type={m.get('type')} action={m.get('action')}")
        print(json.dumps(m, ensure_ascii=False, indent=2)[:800])
    stock_pushes = [
        m for m in msgs
        if m.get("type") == "stock_code" and m.get("action") in ("get", "push")
    ]
    if not stock_pushes:
        print("未收到 stock_code 消息，请确认 ths-linker 已启动且勾选监听")
        return 3
    last = stock_pushes[-1]
    code = last.get("code")
    if not code and isinstance(last.get("stocks"), dict):
        for info in last["stocks"].values():
            if isinstance(info, dict) and info.get("code"):
                code = info["code"]
                break
    print(f"当前股票代码: {code or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
