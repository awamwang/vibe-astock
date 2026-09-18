"""飞书插件页面：拉取今日短线、推送今日短线盯盘、发送消息。缺配置时只提示并链到插件配置。"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote

from fastapi import Request

from duanxian.util import china_today

from .config import DUANXIAN_BITABLE_COLUMNS, LarkConfig, duanxian_table_ids
from .duanxian_row import extract_duanxian_values, to_bitable_fields
from .fields import format_cell

_PLUGIN_NAME = "lark-stock"

_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>飞书</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font: 14px/1.55 system-ui, sans-serif; background: #0b1220; color: #e5e7eb; }
    main { max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
    h1 { font-size: 1.25rem; font-weight: 600; margin: 0 0 1.1rem; }
    section { border: 1px solid #1f2937; border-radius: 12px; background: #111827; padding: 1rem 1.1rem 1.15rem; margin-bottom: 1rem; }
    h2 { font-size: 0.95rem; font-weight: 600; margin: 0 0 0.35rem; }
    .hint, .muted { color: #9ca3af; font-size: 12px; margin: 0 0 0.75rem; }
    .warn { color: #fbbf24; margin: 0 0 0.65rem; }
    a.config { color: #93c5fd; }
    button { border: 0; border-radius: 8px; background: #1d4ed8; color: #fff; padding: 0.45rem 0.9rem; font: inherit; cursor: pointer; }
    button.alt { background: #0f766e; }
    button:disabled { opacity: 0.55; cursor: default; }
    textarea { width: 100%; box-sizing: border-box; min-height: 6.5rem; margin: 0 0 0.7rem; padding: 0.55rem 0.65rem; border-radius: 8px; border: 1px solid #374151; background: #0b1220; color: inherit; font: inherit; resize: vertical; }
    .result { margin-top: 0.85rem; }
    .bad { color: #fca5a5; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.35rem; }
    th, td { text-align: left; vertical-align: top; padding: 0.35rem 0.2rem; border-top: 1px solid #1f2937; }
    th { width: 8.5rem; color: #9ca3af; font-weight: 500; }
    .rid { color: #6b7280; font-size: 11px; margin: 0.8rem 0 0.15rem; }
  </style>
</head>
<body>
  <main>
    <h1>飞书</h1>
    <section>
      <h2>今日短线</h2>
      __TODAY__
    </section>
    <section>
      <h2>发送消息</h2>
      __SEND__
    </section>
  </main>
  <script>
    const root = location.pathname.endsWith("/") ? location.pathname.slice(0, -1) : location.pathname;

    function show(el, text, bad) {
      el.hidden = false;
      el.replaceChildren();
      el.className = bad ? "result bad" : "result";
      el.textContent = text;
    }

    function renderRecords(data) {
      const wrap = document.createElement("div");
      const records = data.records || [];
      if (!records.length) {
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "没有找到「" + (data.date_field || "日期") + "」为 " + (data.date || "") + " 的记录";
        wrap.appendChild(p);
        return wrap;
      }
      records.forEach((rec, index) => {
        const rid = document.createElement("p");
        rid.className = "rid";
        rid.textContent = records.length > 1 ? ("记录 " + (index + 1)) : "记录";
        wrap.appendChild(rid);
        const table = document.createElement("table");
        (rec.rows || []).forEach((row) => {
          const tr = document.createElement("tr");
          const th = document.createElement("th");
          const td = document.createElement("td");
          th.textContent = row.label || "";
          td.textContent = row.value || "—";
          tr.appendChild(th);
          tr.appendChild(td);
          table.appendChild(tr);
        });
        wrap.appendChild(table);
      });
      return wrap;
    }

    document.getElementById("pull")?.addEventListener("click", async () => {
      const btn = document.getElementById("pull");
      const box = document.getElementById("today-result");
      btn.disabled = true;
      show(box, "拉取中…", false);
      try {
        const res = await fetch(root + "/today", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!data.ok) {
          show(box, data.error || (data.missing || []).join("、") || "拉取失败", true);
          return;
        }
        box.hidden = false;
        box.className = "result";
        box.replaceChildren(renderRecords(data));
      } catch (err) {
        show(box, (err && err.message) || "拉取失败", true);
      } finally {
        btn.disabled = false;
      }
    });

    document.getElementById("push")?.addEventListener("click", async () => {
      const btn = document.getElementById("push");
      const box = document.getElementById("push-result");
      btn.disabled = true;
      show(box, "推送中…", false);
      try {
        const res = await fetch(root + "/push", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!data.ok) {
          show(box, data.error || (data.missing || []).join("、") || "推送失败", true);
          return;
        }
        box.hidden = false;
        box.className = "result";
        const wrap = document.createElement("div");
        const p = document.createElement("p");
        p.className = "hint";
        p.textContent = (data.action === "update" ? "已更新 " : "已新增 ") + (data.date || "") + " 的短线记录";
        wrap.appendChild(p);
        if (data.hint) {
          const warn = document.createElement("p");
          warn.className = "warn";
          warn.textContent = data.hint;
          wrap.appendChild(warn);
        }
        wrap.appendChild(renderRecords({
          records: [{ rows: data.rows || [] }],
          date: data.date,
          date_field: data.date_field,
        }));
        box.replaceChildren(wrap);
      } catch (err) {
        show(box, (err && err.message) || "推送失败", true);
      } finally {
        btn.disabled = false;
      }
    });

    document.getElementById("send-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const btn = document.getElementById("send-btn");
      const box = document.getElementById("send-result");
      const text = (document.getElementById("msg").value || "").trim();
      if (!text) {
        show(box, "请输入要发送的消息", true);
        return;
      }
      btn.disabled = true;
      show(box, "发送中…", false);
      try {
        const res = await fetch(root + "/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        const data = await res.json().catch(() => ({}));
        if (!data.ok) {
          show(box, data.error || (data.missing || []).join("、") || "发送失败", true);
          return;
        }
        show(box, "已发送", false);
        document.getElementById("msg").value = "";
      } catch (err) {
        show(box, (err && err.message) || "发送失败", true);
      } finally {
        btn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def config_url(plugin_id: str) -> str:
    """插件管理页配置区。新标签打开。"""
    pid = quote(str(plugin_id or _PLUGIN_NAME).strip() or _PLUGIN_NAME, safe="")
    return f"/settings/plugins?plugin={pid}&config=1"


def bitable_gaps(config: LarkConfig) -> list[tuple[str, str]]:
    """拉取今日短线还缺的配置项。"""
    gaps: list[tuple[str, str]] = []
    if not config.bitable_app_token:
        gaps.append(("LARK_BITABLE_APP_TOKEN", "多维表格 app_token"))
    if not config.bitable_table_id:
        gaps.append(("LARK_BITABLE_TABLE_ID", "多维表格 table_id"))
    date_name = str((config.duanxian_columns or {}).get("DUANXIAN_DATE_BITABLE_KEY_NAME") or "").strip()
    if not date_name:
        gaps.append(("DUANXIAN_DATE_BITABLE_KEY_NAME", "日期列名"))
    return gaps


def push_gaps(config: LarkConfig) -> list[tuple[str, str]]:
    """推送今日短线还缺的配置项。"""
    app, table = duanxian_table_ids(config)
    gaps: list[tuple[str, str]] = []
    if not app:
        gaps.append(("DUANXIAN_BITABLE_APP_TOKEN", "短线盘面多维表格 app_token"))
    if not table:
        gaps.append(("DUANXIAN_BITABLE_TABLE_ID", "短线盘面多维表格 table_id"))
    date_name = str((config.duanxian_columns or {}).get("DUANXIAN_DATE_BITABLE_KEY_NAME") or "").strip()
    if not date_name:
        gaps.append(("DUANXIAN_DATE_BITABLE_KEY_NAME", "日期列名"))
    return gaps


def im_gaps(config: LarkConfig) -> list[tuple[str, str]]:
    """发送消息还缺的配置项。"""
    if not str(config.im_receive_id or "").strip():
        return [("LARK_IM_RECEIVE_ID", "消息接收方 ID")]
    return []


def _need_config(gaps: list[tuple[str, str]], plugin_id: str) -> str:
    labels = "、".join(html.escape(label) for _, label in gaps)
    href = html.escape(config_url(plugin_id), quote=True)
    return (
        f'<p class="warn">请先配置：{labels}。</p>'
        f'<a class="config" href="{href}" target="_blank" rel="noreferrer">去配置</a>'
    )


def _date_field(config: LarkConfig) -> str:
    return str((config.duanxian_columns or {}).get("DUANXIAN_DATE_BITABLE_KEY_NAME") or "").strip() or "日期"


def render_home(config: LarkConfig, plugin_id: str) -> str:
    """插件首页。两个功能分区；缺配置的分区不放出操作。"""
    pull = bitable_gaps(config)
    push = push_gaps(config)
    if pull and push:
        today = _need_config(
            list(dict.fromkeys([*pull, *push])),
            plugin_id,
        )
    else:
        parts: list[str] = []
        if pull:
            parts.append(_need_config(pull, plugin_id))
        else:
            field = html.escape(_date_field(config))
            day = html.escape(china_today())
            parts.append(
                f'<p class="hint">从多维表格读取「{field}」为今天（{day}）的那条记录。</p>'
                '<button id="pull" type="button">拉取今日短线</button>'
                '<div id="today-result" class="result" hidden></div>'
            )
        if push:
            parts.append(_need_config(push, plugin_id))
        else:
            field = html.escape(_date_field(config))
            day = html.escape(china_today())
            parts.append(
                f'<p class="hint">从短线钩子取今日盘面，按「{field}」={day} 新增或更新飞书表格。应用须对该表有「可编辑」权限（表格右上角「…」→添加文档应用）。</p>'
                '<button id="push" class="alt" type="button">推送今日短线盯盘</button>'
                '<div id="push-result" class="result" hidden></div>'
            )
        today = "".join(parts)
    message = im_gaps(config)
    if message:
        send = _need_config(message, plugin_id)
    else:
        send = (
            '<p class="hint">发送到已配置的消息接收方。</p>'
            '<form id="send-form">'
            '<textarea id="msg" placeholder="输入要发送的消息"></textarea>'
            '<button id="send-btn" type="submit">发送</button>'
            '</form>'
            '<div id="send-result" class="result" hidden></div>'
        )
    return _PAGE.replace("__TODAY__", today).replace("__SEND__", send)


def record_rows(fields: dict[str, Any], config: LarkConfig) -> list[dict[str, str]]:
    """按短线列顺序展示，表里多出来的列排在后面。"""
    columns = config.duanxian_columns or {}
    used: set[str] = set()
    rows: list[dict[str, str]] = []
    for col in DUANXIAN_BITABLE_COLUMNS:
        name = str(columns.get(col.key) or col.label)
        if name not in fields:
            continue
        used.add(name)
        rows.append({"label": col.label, "value": format_cell(fields[name])})
    for name, value in fields.items():
        key = str(name)
        if key in used:
            continue
        rows.append({"label": key, "value": format_cell(value)})
    return rows


def _gap_payload(gaps: list[tuple[str, str]], plugin_id: str) -> dict[str, Any]:
    return {
        "ok": False,
        "need_config": True,
        "missing": [label for _, label in gaps],
        "config_url": config_url(plugin_id),
        "error": "请先配置：" + "、".join(label for _, label in gaps),
    }


def handle_today(service: Any, plugin_id: str) -> dict[str, Any]:
    """拉取日期列等于今天的短线记录。"""
    gaps = bitable_gaps(service.config)
    if gaps:
        return _gap_payload(gaps, plugin_id)
    day = china_today()
    field = _date_field(service.config)
    try:
        records = service.bitable.find_by_date(field, day)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "date": day,
        "date_field": field,
        "records": [
            {
                "record_id": str(item.get("record_id") or ""),
                "rows": record_rows(item.get("fields") or {}, service.config),
            }
            for item in records
        ],
    }


def _fetch_live_snapshot() -> dict[str, Any]:
    from duanxian.hooks import build_live_payload

    payload = build_live_payload()
    if not isinstance(payload, dict):
        raise TypeError("短线钩子未返回对象")
    return payload


def handle_push(
    service: Any,
    plugin_id: str,
    *,
    fetch_live: Any | None = None,
) -> dict[str, Any]:
    """从短线钩子取今日盘面，按日期新增或更新飞书表格。"""
    gaps = push_gaps(service.config)
    if gaps:
        return _gap_payload(gaps, plugin_id)
    try:
        payload = (fetch_live or _fetch_live_snapshot)()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取短线钩子失败：{exc}"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "短线钩子未返回对象"}
    day = str(payload.get("date") or china_today()).strip() or china_today()
    field = _date_field(service.config)
    values = extract_duanxian_values(payload, date=day)
    fields = to_bitable_fields(values, service.config.duanxian_columns or {})
    if field not in fields:
        fields[field] = day
    store = getattr(service, "duanxian_bitable", None) or service.bitable
    try:
        result = store.upsert_by_date(field, day, fields)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    written = result.get("fields") or fields
    out = {
        "ok": True,
        "action": result.get("action"),
        "record_id": result.get("record_id"),
        "matched": result.get("matched"),
        "date": day,
        "date_field": field,
        "rows": record_rows(written, service.config),
    }
    hint = str(result.get("hint") or "").strip()
    if hint:
        out["hint"] = hint
        out["skipped"] = list(result.get("skipped") or [])
    return out


def read_json(request: Request) -> dict[str, Any]:
    """读取已缓存的 JSON 请求体。"""
    raw = getattr(request, "_body", b"") or b""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("请求体不是 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体须为 JSON 对象")
    return data


def handle_send(service: Any, request: Request, plugin_id: str) -> dict[str, Any]:
    """把输入框里的文本发到已配置的接收方。"""
    gaps = im_gaps(service.config)
    if gaps:
        return _gap_payload(gaps, plugin_id)
    try:
        body = read_json(request)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    text = str(body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "请输入要发送的消息"}
    if len(text) > 20000:
        return {"ok": False, "error": "消息过长"}
    try:
        message_id = service.messenger.send_text(text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "message_id": message_id}
