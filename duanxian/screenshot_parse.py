"""券商持仓截图 AI 解析：读图 → 结构化权益/持仓草稿（不落盘，确认后再写）。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import requests

_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CODE_RE = re.compile(r"^\d{6}$")

_SYSTEM = (
    "你是证券账户截图结构化抽取助手。只根据图片可见内容填写 JSON，"
    "不要编造看不见的数字；看不清的字段填 null。只输出 JSON，不要 markdown。"
)

_USER_PROMPT = """从这张券商/交易软件截图中抽取账户与持仓信息。

要求：
1. 尽量解析图中所有账户汇总数字与持仓表行（含持仓股数为 0 的历史行）。
2. 股票代码统一为 6 位数字字符串。
3. 金额、价格、股数去掉千分位逗号，用数字；百分比若图中是 -3.34% 则写成 -3.34（不要写成小数比例）。
4. 总权益优先取「总资产」；若无总资产则取能代表账户总权益的字段。
5. 字段看不清或图中没有则填 null；不要猜测。

严格输出如下 JSON 对象（键名固定）：
{
  "broker": "券商或软件名，未知则 null",
  "account_name": "账户名（如 中金财富-王*），无则 null",
  "account_display": "界面右下角账户标识（如 中金财富6323），无则 null",
  "equity": 总资产或总权益数字或 null,
  "cash_balance": 资金余额数字或 null,
  "available": 可用金额或 null,
  "withdrawable": 可取金额或 null,
  "frozen": 冻结金额或 null,
  "stock_market_value": 股票市值或 null,
  "position_pnl": 持仓盈亏或 null,
  "daily_pnl": 当日盈亏或 null,
  "daily_pnl_pct": 当日盈亏比（百分数，如 -3.34）或 null,
  "note": "一句话备注；勿重复上述已拆字段，无可 null",
  "holdings": [
    {
      "code": "600000",
      "name": "名称或 null",
      "shares": 当前持仓股数,
      "available_shares": 可用余额或 null,
      "cost": 成本价或 null,
      "price": 现价或 null,
      "pnl": 盈亏或 null,
      "market_value": 市值或 null
    }
  ]
}
"""


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v):  # NaN
            return None
        return float(v)
    s = str(v).strip().replace(",", "").replace("，", "").replace("%", "").replace("元", "")
    s = s.replace("−", "-").replace("－", "-")
    if not s or s in {"—", "-", "null", "None", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_code(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"\D", "", str(v))
    if len(s) > 6:
        s = s[-6:]
    if len(s) < 6:
        s = s.zfill(6)
    return s if _CODE_RE.match(s) else None


def _strip_data_url(image_b64: str) -> tuple[str, str]:
    """返回 (mime, raw_b64)。默认 image/png。"""
    raw = (image_b64 or "").strip()
    mime = "image/png"
    if raw.startswith("data:"):
        head, _, body = raw.partition(",")
        if not body:
            raise ValueError("无效的图片 data URI")
        m = re.match(r"data:([^;]+)", head)
        if m:
            mime = m.group(1).strip() or mime
        raw = body
    if not raw:
        raise ValueError("图片内容为空")
    # 粗估体积：base64 约 4/3
    approx = len(raw) * 3 // 4
    if approx > _MAX_IMAGE_BYTES:
        raise ValueError(f"图片过大（约 {approx // 1024 // 1024}MB），上限 {_MAX_IMAGE_BYTES // 1024 // 1024}MB")
    return mime, raw


def normalize_parsed(raw: Any) -> dict:
    """把模型输出整理成前端对照表可用的固定结构。"""
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("解析结果不是 JSON 对象")

    holdings_in = raw.get("holdings") or []
    if not isinstance(holdings_in, list):
        holdings_in = []

    holdings: list[dict] = []
    seen: set[str] = set()
    for row in holdings_in:
        if not isinstance(row, dict):
            continue
        code = _norm_code(row.get("code"))
        if not code or code in seen:
            continue
        shares = _to_float(row.get("shares"))
        if shares is None:
            continue
        shares = float(shares)
        cost = _to_float(row.get("cost"))
        include = shares > 0 and cost is not None and cost > 0
        holdings.append({
            "code": code,
            "name": (str(row["name"]).strip() if row.get("name") not in (None, "") else None),
            "shares": round(shares, 4),
            "available_shares": _to_float(row.get("available_shares")),
            "cost": None if cost is None else round(float(cost), 4),
            "price": _to_float(row.get("price")),
            "pnl": _to_float(row.get("pnl")),
            "market_value": _to_float(row.get("market_value")),
            "include": include,
        })
        seen.add(code)

    equity = _to_float(raw.get("equity"))
    note = raw.get("note")
    if note is not None:
        note = str(note).strip() or None

    def _text(key: str) -> Optional[str]:
        v = raw.get(key)
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s or None

    cash = _to_float(raw.get("cash_balance"))
    withdrawable = _to_float(raw.get("withdrawable"))
    # 图中常把「资金余额」与「可取」写成同一数；缺一则互填
    if cash is None and withdrawable is not None:
        cash = withdrawable
    if withdrawable is None and cash is not None:
        withdrawable = cash

    return {
        "broker": _text("broker"),
        "account_name": _text("account_name"),
        "account_display": _text("account_display"),
        "equity": None if equity is None else round(float(equity), 2),
        "cash_balance": cash,
        "available": _to_float(raw.get("available")),
        "withdrawable": withdrawable,
        "frozen": _to_float(raw.get("frozen")),
        "stock_market_value": _to_float(raw.get("stock_market_value")),
        "position_pnl": _to_float(raw.get("position_pnl")),
        "daily_pnl": _to_float(raw.get("daily_pnl")),
        "daily_pnl_pct": _to_float(raw.get("daily_pnl_pct")),
        "note": note,
        "holdings": holdings,
    }


def _resolve_base(cfg: dict) -> str:
    base = (cfg.get("baseURL") or "").rstrip("/")
    if not base:
        raise ValueError("缺少 Base URL")
    if not base.endswith(("/v1", "/v3", "/api/v3")):
        base = base + "/v1"
    return base


def _extract_json_object(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("模型未返回内容")
    try:
        return normalize_parsed(text)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("模型输出中未找到 JSON")
    return normalize_parsed(m.group(0))


def parse_screenshot(image_b64: str, llm: dict) -> dict:
    """调用用户配置的 OpenAI 兼容视觉模型解析截图。CLI 订阅不支持。"""
    provider = str(llm.get("provider") or "")
    if provider.startswith("cli-"):
        raise ValueError("截图解析需要支持识图的 API 模型（OpenAI 兼容），请改用「API 接入」")
    if not llm.get("apiKey") or not llm.get("baseURL") or not llm.get("model"):
        raise ValueError("缺少模型配置，请先在「接入 AI」里填写 Base URL / API Key / 模型")

    mime, raw_b64 = _strip_data_url(image_b64)
    data_url = f"data:{mime};base64,{raw_b64}"

    # 与 vr/chat 一致：挡 SSRF（公网姿态下尤其重要）
    try:
        import chat as chat_layer  # noqa: PLC0415  vr 已在 sys.path
        chat_layer._check_base_url(str(llm.get("baseURL") or ""))
    except ImportError:
        pass
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    payload = {
        "model": llm["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    # 部分兼容端支持 json_object；失败时降级重试不带 response_format
    last_err: Optional[Exception] = None
    for with_json in (True, False):
        body = dict(payload)
        if with_json:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(
                f"{_resolve_base(llm)}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm['apiKey']}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=120,
            )
            if r.status_code != 200:
                # 不支持 response_format 时换无格式再试
                if with_json and r.status_code in (400, 422):
                    last_err = RuntimeError(f"模型接口 HTTP {r.status_code}: {r.text[:300]}")
                    continue
                raise RuntimeError(f"模型接口 HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
            return _extract_json_object(content)
        except RuntimeError as exc:
            last_err = exc
            if with_json:
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("截图解析失败")


_APPLY_FIELD_KEYS = (
    "account_name", "account_display", "broker",
    "cash_balance", "available", "withdrawable", "frozen",
    "stock_market_value", "position_pnl", "daily_pnl", "daily_pnl_pct",
)


def extract_account_fields(body: dict) -> dict:
    """从确认写入体抽出命名账户栏位。"""
    src = body.get("account_fields") if isinstance(body.get("account_fields"), dict) else body
    out: dict[str, Any] = {}
    for k in _APPLY_FIELD_KEYS:
        if k not in src:
            continue
        v = src[k]
        if v is None or v == "":
            continue
        if k in {
            "cash_balance", "available", "withdrawable", "frozen",
            "stock_market_value", "position_pnl", "daily_pnl", "daily_pnl_pct",
        }:
            fv = _to_float(v)
            if fv is not None:
                out[k] = fv
        else:
            out[k] = str(v).strip()
    return out


def validate_apply_payload(body: dict) -> tuple[Optional[float], str, list[dict], bool, dict]:
    """校验确认写入体：equity 可空（不改权益）、holdings、replace、账户栏位。"""
    equity = body.get("equity", None)
    if equity is not None and equity != "":
        eq = float(equity)
        if eq < 0:
            raise ValueError("权益不能为负")
    else:
        eq = None
    note = str(body.get("note") or "")
    replace = bool(body.get("replace", True))
    fields = extract_account_fields(body or {})
    rows_in = body.get("holdings") or []
    if not isinstance(rows_in, list):
        raise ValueError("holdings 须为数组")
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows_in:
        if not isinstance(row, dict):
            continue
        if row.get("include") is False:
            continue
        code = _norm_code(row.get("code"))
        shares = _to_float(row.get("shares"))
        cost = _to_float(row.get("cost"))
        if not code or shares is None or cost is None:
            continue
        if shares <= 0 or cost <= 0:
            continue
        if code in seen:
            raise ValueError(f"持仓代码重复：{code}")
        seen.add(code)
        out.append({"code": code, "shares": float(shares), "cost": float(cost)})
    return eq, note, out, replace, fields
