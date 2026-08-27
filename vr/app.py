"""Vibe-Research 后端 —— A股数据层 HTTP 接口（FastAPI）。

端点全部在 /api 下，前端 vite 代理 /api → localhost:8900。
只读、无状态、按用户传入代码返回客观数据。不预置标的、不建议。

启动：
    uvicorn app:app --host 127.0.0.1 --port 8900
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import astock
import chat as chat_layer
import cli_runtime
import debate as debate_layer
import gstock
import newsradar
import portfolio as pf
import market
import myreports as mr
import firstboard
import watchtower
import message as msg_layer
from message import analyze as msg_analyze
import ths_block as ths_block_layer
import stock_universe

app = FastAPI(title="Vibe-Research API", version="0.1.3")

stock_universe.startup_load()

# 每半小时后台刷新持仓数据
pf.start_scheduler(1800)
# 消息轮询钩子（财联社由前端 5s 刷新；选股宝仅手动）
msg_layer.poller.start_poller()

# CORS：默认放开（本地自托管友好）；公网部署时用 VR_ALLOW_ORIGINS 收紧成白名单。
#   例：VR_ALLOW_ORIGINS="https://myhost"  （逗号分隔多个）
_ORIGINS = [o.strip() for o in os.environ.get("VR_ALLOW_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 可选鉴权：设了 VR_API_KEY 就要求所有 /api/* 带 `Authorization: Bearer <key>`
#   （本地自托管不设=开放；公网部署务必设，否则别人能读你的持仓/调你的后端）。
_API_KEY = os.environ.get("VR_API_KEY", "").strip()


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if (
        _API_KEY
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
        and request.url.path != "/api/health"
    ):
        if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
            return JSONResponse({"detail": "未授权：缺少或错误的 API Key（VR_API_KEY）"}, status_code=401)
    return await call_next(request)

_CODE_RE = r"^\d{6}$"


def _validate(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


@app.get("/api/health")
def health():
    return {"ok": True, "service": "vibe-research-api", "version": "0.1.3"}


class LLMConfig(BaseModel):
    provider: str = ""       # cli-* = 订阅接入（调本机 CLI）；其余 = API 接入
    baseURL: str = ""        # 订阅接入时留空
    apiKey: str = ""         # 订阅接入时留空
    model: str


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@app.post("/api/chat")
def chat(req: ChatReq):
    """系统 AI 对话，**流式** NDJSON（每行一个事件 {type: tool|delta|done|error}）。

    - API 接入：OpenAI 兼容 function-calling，边流答案边推工具调用事件。
    - 订阅接入（provider=cli-*）：调本机已登录的 CLI，stdout 边出边流（数据靠 context）。
    配置错误（缺 key / 未装 CLI）走 HTTP 400；运行时错误走流内 error 事件。用户配置随请求传入，后端不持久化。
    """
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")

    is_cli = req.llm.provider.startswith("cli-")
    if is_cli:
        kind = req.llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not req.llm.apiKey or not req.llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")

    cfg = req.llm.model_dump()

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(cfg, req.messages, req.context)
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — 运行时错误以流内事件上报，不中断连接
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _check_llm(llm: LLMConfig) -> dict:
    """校验模型配置并返回 cfg（chat / debate 流式端点共用）。"""
    if not llm.model:
        raise HTTPException(400, "缺少模型配置，请先在「接入 AI」里选择")
    if llm.provider.startswith("cli-"):
        kind = llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令。请先安装并登录该 CLI，或改用「API 接入」。")
    elif not llm.apiKey or not llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先在「接入 AI」里填写")
    return llm.model_dump()


def _ndjson(events):
    """把事件生成器包成 NDJSON 流；运行时异常转成流内 error 事件。"""
    def gen():
        try:
            for ev in events():
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


class DebateReq(BaseModel):
    code: str
    rounds: int = 1
    llm: LLMConfig


@app.post("/api/debate")
def debate(req: DebateReq):
    """多空辩论：先拉客观事实底稿，再多方 / 空方 / 主持依次发言，流式 NDJSON。"""
    code = _validate(req.code)
    cfg = _check_llm(req.llm)
    rounds = 2 if req.rounds >= 2 else 1
    return _ndjson(lambda: debate_layer.run_debate_stream(cfg, code, rounds))


class HoldingIn(BaseModel):
    code: str
    shares: float
    cost: float
    upsert: bool = False  # True：按代码覆盖；False：同代码加权合并加仓


@app.get("/api/portfolio")
def portfolio_get():
    """持仓 + 实时盈亏（浮动盈亏红涨绿跌）。"""
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"持仓读取异常：{e}") from e


@app.post("/api/portfolio/holding")
def portfolio_add(h: HoldingIn):
    """加一笔持仓。默认同代码加权合并；upsert=true 时按代码覆盖股数与成本。"""
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if h.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    # 成本价不限正负：融券 / 返息 / 摊薄后为负成本等情形按结果计算，用户想怎么输就怎么输。
    if h.upsert:
        out = pf.set_holding(code, h.shares, h.cost)
    else:
        out = pf.add_holding(code, h.shares, h.cost)
    watchtower.poke()  # 每日盯盘：持仓变化立即重建快照
    return {"data": out}


@app.delete("/api/portfolio/holding")
def portfolio_remove(code: str = Query(...)):
    out = pf.remove_holding(code.strip())
    watchtower.poke()  # 每日盯盘：持仓变化立即重建快照
    return {"data": out}


# ---- 我的研报（用户上传自己的研报，存本地、不上传、不进开源仓库）----

class ReportIn(BaseModel):
    name: str
    content_b64: str


@app.get("/api/myreports")
def myreports_list():
    return {"data": mr.list_reports()}


@app.post("/api/myreports")
def myreports_upload(r: ReportIn):
    """上传一份研报（base64）→ 存本地 + 按文件名自动打行业标签。"""
    try:
        return {"data": mr.save_report(r.name, r.content_b64)}
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/myreports/file/{rid}")
def myreports_file(rid: str):
    """下载/预览某份研报原文件。"""
    hit = mr.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@app.delete("/api/myreports/{rid}")
def myreports_delete(rid: str):
    return {"data": {"ok": mr.delete_report(rid)}}


class CloseIn(BaseModel):
    code: str
    date: str
    price: float
    shares: float
    cost: float


@app.post("/api/portfolio/close")
def portfolio_close(c: CloseIn):
    """记一笔已清仓（已实现盈亏）。存本地。"""
    code = (c.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if c.price <= 0 or c.shares <= 0:
        raise HTTPException(400, "清仓价与股数必须大于 0")
    # 买入成本不限正负（同持仓录入）：按 (清仓价 - 成本) × 股数 的结果计算已实现盈亏。
    date = (c.date or "").strip()
    if not date:
        raise HTTPException(400, "请填清仓日期")
    from datetime import datetime
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "清仓日期格式应为 YYYY-MM-DD") from None
    return {"data": pf.close_position(code, date, c.price, c.shares, c.cost)}


@app.delete("/api/portfolio/close")
def portfolio_close_remove(index: int = Query(...)):
    return {"data": pf.remove_closed(index)}


@app.post("/api/portfolio/refresh")
def portfolio_refresh():
    """手动刷新：立即重拉行情算盈亏。"""
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"刷新失败：{e}") from e


@app.get("/api/radar")
def radar():
    """资讯雷达：12 赛道公开 RSS 资讯（读缓存，无缓存返回赛道骨架）。"""
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达异常：{e}") from e


@app.post("/api/radar/refresh")
def radar_refresh():
    """强制重抓全部 RSS 源（耗时约 20-40s），更新缓存。"""
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资讯雷达刷新失败：{e}") from e


@app.get("/api/market/overview")
def market_overview():
    """市场情绪 + 板块资金流（板块/大盘级，全站共享缓存 5 分钟）。"""
    try:
        data = market.get_overview()
        try:
            ths_block_layer.feed_overview(data)
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"市场总览异常：{e}") from e


@app.get("/api/market/emotion")
def market_emotion():
    """短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    含连板梯队个股清单（code/name/连板数等）——2026-07-05 起如实展示客观公开榜单（东财同款），
    只呈现事实，不附推荐/评分/预测/买卖时机。全站共享缓存 5 分钟。
    """
    try:
        data = market.get_short_term_emotion()
        try:
            ths_block_layer.feed_emotion(data)
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"短线情绪异常：{e}") from e


@app.get("/api/monitor/snapshot")
def monitor_snapshot(watch: str = Query("")):
    """每日盯盘快照：持仓/自选/500亿大票异动/三板+/昨日成交前十 + 异动事件流。

    后端常驻线程盘中 3 秒轮询（腾讯 L1 快照），本接口只读内存、毫秒级返回——前端可放心
    3 秒轮询。watch 参数=前端本地自选股（逗号分隔 6 位代码），并入监控池下一轮生效。
    """
    codes = [c.strip() for c in watch.split(",") if c.strip()]
    watchtower.set_watch(codes)
    watchtower.ensure_started()
    return {"data": watchtower.get_snapshot()}


@app.get("/api/market/first-board")
def market_first_board():
    """涨停分析：当日全部涨停股 + 涨停原因题材串（问财，缺 key 优雅降级）。

    客观公开榜单数据（东财涨停池同款），只呈现事实，不附推荐/评分/预测/买卖时机。缓存 10 分钟。
    """
    try:
        data = firstboard.get_limit_up()
        try:
            ths_block_layer.feed_firstboard(data)
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"首板数据异常：{e}") from e


@app.get("/api/market/turnover-top")
def market_turnover_top():
    """全市场成交额榜 Top20（客观公开榜单数据，非推荐/非预测/不评分）。全站共享缓存 5 分钟。"""
    try:
        data = market.get_turnover_top()
        try:
            ths_block_layer.feed_turnover(data)
        except Exception:  # noqa: BLE001
            pass
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"成交额榜异常：{e}") from e


@app.get("/api/global/indices")
def global_indices():
    """全球指数快照（道指 / 标普500 / 纳斯达克 / 恒生 / 恒生科技）—— A 股看隔夜外围脸色。缓存 5 分钟。"""
    try:
        return {"data": market.get_global_indices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"全球指数异常：{e}") from e


@app.get("/api/global/stock")
def global_stock(symbol: str = Query(..., min_length=1, max_length=16)):
    """美股 / 港股个股聚合：行情 + 关键财务指标（东财域内源）。symbol 如 AAPL / BABA / 00700。"""
    try:
        data = gstock.us_hk_stock(symbol.strip())
        if not data:
            raise HTTPException(404, f"未找到美股/港股代码「{symbol}」")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"美港股查询异常：{e}") from e


@app.get("/api/indices")
def indices():
    """A股大盘指数实时行情（上证/深证成指/创业板指/沪深300）。仅标准库。"""
    try:
        return {"data": astock.index_quote()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"指数行情异常：{e}") from e


@app.get("/api/quote")
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")):
    """实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。仅标准库，永远可用。"""
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        return {"data": astock.tencent_quote(lst)}
    except Exception as e:  # noqa: BLE001 — 边界统一兜底
        raise HTTPException(502, f"行情源异常：{e}") from e


import time as _time
_PCT_CACHE: dict = {}


@app.get("/api/valuation/percentile")
def valuation_percentile(code: str = Query(...)):
    """PE-TTM / PB 历史分位（近5年）。全站缓存 30 分钟/代码（历史序列日频、变化慢）。"""
    code = _validate(code)
    hit = _PCT_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值分位异常：{e}") from e


_ANN_CACHE: dict = {}


@app.get("/api/announcements")
def announcements(code: str = Query(...)):
    """个股近期公告（东财，仅 requests）。缓存 15 分钟/代码。"""
    code = _validate(code)
    hit = _ANN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 900:
        return {"data": hit[1]}
    try:
        data = astock.announcements(code)
        _ANN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


_FIN_CACHE: dict = {}


@app.get("/api/financials")
def financials(code: str = Query(...)):
    """财务关键指标（同花顺财务摘要，最新报告期）。缓存 30 分钟/代码。"""
    code = _validate(code)
    hit = _FIN_CACHE.get(code)
    if hit and _time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.financials(code)
        _FIN_CACHE[code] = (_time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务摘要异常：{e}") from e


@app.get("/api/valuation")
def valuation(code: str = Query(...)):
    """完整估值：行情 + 一致预期 + 前向PE/PEG/消化年数。"""
    code = _validate(code)
    try:
        return {"data": astock.full_valuation(code)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"估值计算异常：{e}") from e


@app.get("/api/reports")
def reports(code: str = Query(...), pages: int = Query(2, ge=1, le=5)):
    """个股研报列表（东财，含 PDF 链接）。仅需 requests。"""
    code = _validate(code)
    try:
        rows = astock.eastmoney_reports(code, max_pages=pages)
        for r in rows:
            r["pdfUrl"] = astock.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"data": rows}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"研报源异常：{e}") from e


@app.get("/api/news")
def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    """个股新闻（东财，需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.stock_news(code, limit=limit)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"新闻源异常：{e}") from e


@app.get("/api/info")
def info(code: str = Query(...)):
    """个股基本面：行业/股本/上市时间（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.individual_info(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"基本面源异常：{e}") from e


@app.get("/api/disclosure")
def disclosure(code: str = Query(...)):
    """巨潮公告列表（需 akshare）。"""
    code = _validate(code)
    try:
        return {"data": astock.disclosure(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"公告源异常：{e}") from e


@app.get("/api/kline")
def kline(code: str = Query(...), category: int = Query(4), offset: int = Query(60, ge=1, le=800)):
    """K线（需 mootdx）。category 4=日 5=周 6=月 11=60分钟。"""
    code = _validate(code)
    try:
        return {"data": astock.kline(code, category=category, offset=offset)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"K线源异常：{e}") from e


@app.get("/api/finance")
def finance(code: str = Query(...)):
    """季报财务快照（需 mootdx）。"""
    code = _validate(code)
    try:
        return {"data": astock.finance(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"财务源异常：{e}") from e


# ---------------------------------------------------------------------------
# 资金面 / 筹码 / 信号（东财数据中心，v3.3 并入）—— 均为「用户查的那只股」的公开数据。
# 东财有 1s 限流，这些多为日/季级静态数据，统一走 30 分钟缓存，进一步降低被封风险。
# ---------------------------------------------------------------------------

_DC_CACHE: dict = {}  # key=(endpoint, code) -> (ts, data)


def _cached(endpoint: str, code: str, ttl: int, fetch):
    key = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    _DC_CACHE[key] = (_time.time(), data)
    return data


@app.get("/api/margin")
def margin(code: str = Query(...)):
    """融资融券明细（东财，日级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("margin", code, 1800, lambda: astock.margin_trading(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"融资融券异常：{e}") from e


@app.get("/api/block-trade")
def block_trade(code: str = Query(...)):
    """大宗交易（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("block", code, 1800, lambda: astock.block_trade(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"大宗交易异常：{e}") from e


@app.get("/api/holders")
def holders(code: str = Query(...)):
    """股东户数变化（东财，季度级）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("holders", code, 1800, lambda: astock.holder_num_change(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"股东户数异常：{e}") from e


@app.get("/api/dividend")
def dividend(code: str = Query(...)):
    """分红送转历史（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dividend", code, 1800, lambda: astock.dividend_history(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"分红送转异常：{e}") from e


@app.get("/api/fund-flow")
def fund_flow(code: str = Query(...)):
    """个股资金流（东财 push2his，120 日主力净流入）。缓存 15 分钟。
    注：push2his 对部分大陆住宅 IP 有间歇风控，可能返回空（非代码问题）。"""
    code = _validate(code)
    try:
        return {"data": _cached("fundflow", code, 900, lambda: astock.stock_fund_flow_120d(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"资金流异常：{e}") from e


@app.get("/api/dragon-tiger")
def dragon_tiger(code: str = Query(...)):
    """龙虎榜：该股近期上榜记录 + 买卖席位 + 机构净买（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("dt", code, 1800, lambda: astock.dragon_tiger_board(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"龙虎榜异常：{e}") from e


@app.get("/api/lockup")
def lockup(code: str = Query(...)):
    """限售解禁日历：历史解禁 + 未来 90 天待解禁（东财）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("lockup", code, 1800, lambda: astock.lockup_expiry(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"解禁日历异常：{e}") from e


@app.get("/api/blocks")
def blocks(code: str = Query(...)):
    """个股所属板块/概念归属（东财 slist）。缓存 30 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("blocks", code, 1800, lambda: astock.concept_blocks(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块归属异常：{e}") from e


@app.get("/api/hot-concepts")
def hot_concepts(code: str = Query(...)):
    """个股当下被市场归到哪些概念在炒（东财热门概念命中）。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("hotcon", code, 900, lambda: astock.hot_concepts(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"热门概念异常：{e}") from e


@app.get("/api/investor-qa")
def investor_qa(code: str = Query(...)):
    """互动易问答（巨潮）：投资者提问 + 公司回复。缓存 15 分钟。"""
    code = _validate(code)
    try:
        return {"data": _cached("irm", code, 900, lambda: astock.investor_qa(code))}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"互动易异常：{e}") from e


@app.get("/api/industry")
def industry(top: int = Query(20, ge=5, le=50)):
    """全行业涨跌幅排名（东财行业板块，板块级、零个股名单）。缓存 5 分钟。"""
    key = ("industry", str(top))
    hit = _DC_CACHE.get(key)
    if hit and _time.time() - hit[0] < 300:
        return {"data": hit[1]}
    try:
        data = astock.industry_comparison(top_n=top)
        _DC_CACHE[key] = (_time.time(), data)
        return {"data": data}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"行业排名异常：{e}") from e


# ── 消息分析 ──────────────────────────────────────────────────────────────


class IngestIn(BaseModel):
    format: str = "plain"
    source_id: str = "manual"
    text: str | None = None
    items: list[dict] | None = None
    options: dict | None = None


class IngestAdjustIn(BaseModel):
    drafts: list[dict]


class AnalyzeIn(BaseModel):
    raw_ids: list[str] = []
    analyzed_ids: list[str] = []


class MessageAnalyzeRunReq(BaseModel):
    llm: LLMConfig
    raw_ids: list[str] = []
    analyzed_ids: list[str] = []


class AnalyzedPatchIn(BaseModel):
    title: str | None = None
    keywords: list[str] | None = None
    url: str | None = None
    marks: list[str] | None = None
    summary: str | None = None
    detail: str | None = None
    effective_mode: str | None = None
    effective_at: str | None = None
    produced_at: str | None = None
    impact_level: str | None = None
    freshness: str | None = None
    effect_status: str | None = None
    status: str | None = None
    favorited: bool | None = None
    targets: list[dict] | None = None


class AnalyzedBatchIdsIn(BaseModel):
    ids: list[str]


class AnalyzedFavoriteIn(BaseModel):
    ids: list[str]
    favorited: bool = True


def _list_query(
    source: str = "",
    q: str = "",
    from_dt: str = "",
    to_dt: str = "",
    impact_level: str = "",
    effect_status: str = "",
    status: str = "",
    favorited: str = "",
    followed: str = "",
    sort: str = "produced_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> msg_layer.ListQuery:
    return msg_layer.ListQuery(
        source=source or None,
        q=q or None,
        from_dt=from_dt or None,
        to_dt=to_dt or None,
        impact_level=impact_level or None,
        effect_status=effect_status or None,
        status=status or None,
        favorited=favorited or None,
        followed=followed or None,
        sort=sort if sort in ("produced_at", "ingested_at", "impact_level", "title") else "produced_at",
        order=order if order in ("asc", "desc") else "desc",
        limit=limit,
        offset=offset,
    )


@app.get("/api/messages/sources")
def messages_sources():
    return {"data": [s.model_dump() for s in msg_layer.store.list_sources()]}


@app.post("/api/messages/ingest/preview")
def messages_ingest_preview(body: IngestIn):
    payload = msg_layer.IngestPayload(
        format=body.format,
        source_id=body.source_id,
        text=body.text,
        items=body.items,
        options=body.options or {},
    )
    drafts = msg_layer.parse_ingest(payload)
    return {"data": [d.model_dump() for d in drafts]}


@app.post("/api/messages/ingest/commit")
def messages_ingest_commit(body: IngestAdjustIn):
    if not body.drafts:
        raise HTTPException(400, "请提供 drafts")
    drafts = [msg_layer.RawMessageDraft.model_validate(d) for d in body.drafts]
    inserted = msg_layer.store.insert_raw_batch(drafts)
    analyzed = []
    for raw in inserted:
        draft = next((d for d in drafts if d.external_ref == raw.external_ref or d.title == raw.title), None)
        patch: dict = {}
        if draft:
            if draft.effective_mode == "scheduled":
                patch["effective_mode"] = "scheduled"
                patch["effective_at"] = draft.effective_at
            if draft.targets:
                patch["targets"] = [t.model_dump() for t in draft.targets]
            meta_il = (draft.meta or {}).get("impact_level")
            if meta_il:
                patch["impact_level"] = meta_il
        analyzed.append(msg_layer.store.upsert_analyzed_from_raw(raw, patch=patch))
    return {"data": {"inserted": [r.model_dump() for r in inserted], "analyzed": [a.model_dump() for a in analyzed]}}


@app.post("/api/messages/ingest/adjust")
def messages_ingest_adjust(body: IngestAdjustIn):
    drafts = [msg_layer.RawMessageDraft.model_validate(d) for d in body.drafts]
    inserted = msg_layer.store.insert_raw_batch(drafts)
    analyzed = []
    for i, raw in enumerate(inserted):
        d = drafts[i] if i < len(drafts) else None
        patch: dict = {}
        if d:
            if d.effective_mode == "scheduled":
                patch["effective_mode"] = "scheduled"
                patch["effective_at"] = d.effective_at
            if d.targets:
                patch["targets"] = [t.model_dump() for t in d.targets]
            meta_il = (d.meta or {}).get("impact_level")
            if meta_il:
                patch["impact_level"] = meta_il
        analyzed.append(msg_layer.store.upsert_analyzed_from_raw(raw, patch=patch))
    return {"data": {"inserted": [r.model_dump() for r in inserted], "analyzed": [a.model_dump() for a in analyzed]}}


@app.get("/api/messages/raw")
def messages_raw_list(
    source: str = "",
    q: str = "",
    from_dt: str = "",
    to_dt: str = "",
    sort: str = "produced_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    query = _list_query(source=source, q=q, from_dt=from_dt, to_dt=to_dt, sort=sort, order=order, limit=limit, offset=offset)
    rows, total = msg_layer.store.list_raw(query)
    return {"data": {"items": [r.model_dump() for r in rows], "total": total}}


@app.get("/api/messages/raw/archive")
def messages_raw_archive_list(
    source: str = "",
    q: str = "",
    from_dt: str = "",
    to_dt: str = "",
    sort: str = "produced_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    query = _list_query(source=source, q=q, from_dt=from_dt, to_dt=to_dt, sort=sort, order=order, limit=limit, offset=offset)
    rows, total = msg_layer.archive.list_raw_archive(query)
    return {"data": {"items": [r.model_dump() for r in rows], "total": total}}


@app.post("/api/messages/archive/run")
def messages_archive_run():
    """手动触发：立即生效且超过保留期的消息 raw 归档。"""
    return {"data": msg_layer.archive.archive_immediate_expired()}


@app.get("/api/messages/analyzed")
def messages_analyzed_list(
    source: str = "",
    q: str = "",
    from_dt: str = "",
    to_dt: str = "",
    impact_level: str = "",
    effect_status: str = "",
    status: str = "",
    favorited: str = "",
    followed: str = "",
    sort: str = "produced_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    query = _list_query(
        source=source,
        q=q,
        from_dt=from_dt,
        to_dt=to_dt,
        impact_level=impact_level,
        effect_status=effect_status,
        status=status,
        favorited=favorited,
        followed=followed,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    rows, total = msg_layer.store.list_analyzed(query)
    items = [r.model_dump() for r in rows]
    try:
        ths_block_layer.feed_message_targets(items)
    except Exception:  # noqa: BLE001
        pass
    return {"data": {"items": items, "total": total}}


@app.get("/api/messages/analyzed/{analyzed_id}")
def messages_analyzed_detail(analyzed_id: str):
    row = msg_layer.store.get_analyzed(analyzed_id)
    if not row:
        raise HTTPException(404, "未找到分析消息")
    raw_messages = msg_layer.store.get_raws_for_analyzed(analyzed_id)
    return {
        "data": {
            **row.model_dump(),
            "raw_messages": [r.model_dump() for r in raw_messages],
        }
    }


@app.patch("/api/messages/analyzed/{analyzed_id}")
def messages_analyzed_patch(analyzed_id: str, body: AnalyzedPatchIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    patch["analyzed_by"] = "human"
    row = msg_layer.store.update_analyzed(analyzed_id, patch)
    if not row:
        raise HTTPException(404, "未找到分析消息")
    return {"data": row.model_dump()}


@app.post("/api/messages/analyzed/favorite")
def messages_analyzed_favorite(body: AnalyzedFavoriteIn):
    ids = [i for i in body.ids if i]
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    n = msg_layer.store.set_favorited_batch(ids, body.favorited)
    return {"data": {"updated": n, "favorited": body.favorited}}


@app.post("/api/messages/analyzed/delete")
def messages_analyzed_delete(body: AnalyzedBatchIdsIn):
    ids = [i for i in body.ids if i]
    if not ids:
        raise HTTPException(400, "ids 不能为空")
    n = msg_layer.store.delete_analyzed_batch(ids)
    return {"data": {"deleted": n}}


@app.post("/api/messages/analyze/run")
def messages_analyze_run(req: MessageAnalyzeRunReq):
    """批量 AI 分析（NDJSON 流：progress / item / item_error / done）。"""
    cfg = _check_llm(req.llm)

    def events():
        yield from msg_analyze.run_batch_stream(
            cfg,
            raw_ids=req.raw_ids,
            analyzed_ids=req.analyzed_ids,
        )

    return _ndjson(events)


@app.post("/api/messages/analyze")
def messages_analyze(body: AnalyzeIn):
    job_ids = msg_layer.store.enqueue_analyze(raw_ids=body.raw_ids, analyzed_ids=body.analyzed_ids)
    return {"data": {"job_ids": job_ids, "queued": len(job_ids)}}


@app.get("/api/messages/analyze/queue")
def messages_analyze_queue():
    return {
        "data": {
            "counts": msg_layer.store.count_jobs_by_status(),
            "pending": msg_layer.store.list_pending_jobs(),
        }
    }


@app.post("/api/messages/poll/cls")
def messages_poll_cls():
    try:
        return {"data": msg_layer.cls.fetch_telegraph()}
    except Exception as e:  # noqa: BLE001
        msg_layer.store.set_poll_state("cls_telegraph", last_error=str(e)[:500])
        raise HTTPException(502, f"财联社轮询失败：{e}") from e


@app.post("/api/messages/poll/xgb")
def messages_poll_xgb():
    try:
        return {"data": msg_layer.xgb.fetch_pc_msgs()}
    except Exception as e:  # noqa: BLE001
        msg_layer.store.set_poll_state("xgb_msgs", last_error=str(e)[:500])
        raise HTTPException(502, f"选股宝轮询失败：{e}") from e


@app.post("/api/messages/xgb/resync-targets")
def messages_xgb_resync_targets():
    """从已入库选股宝 raw.meta 重建关联标的（修复历史数据）。"""
    try:
        n = msg_layer.xgb.resync_targets_from_meta()
        return {"data": {"synced": n}}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"同步关联标的失败：{e}") from e


# ── 同花顺板块（ths-linker + 本地成分股）────────────────────────────────────


class ThsBlockRefreshIn(BaseModel):
    ths_dir: str = ""


@app.get("/api/ths-blocks")
def ths_blocks_snapshot():
    """返回内存中的同花顺板块缓存（未刷新过则 kinds 为空）。"""
    return {"data": ths_block_layer.get_snapshot()}


@app.post("/api/ths-blocks/refresh")
def ths_blocks_refresh(body: ThsBlockRefreshIn | None = None):
    """从 ths-linker 重新拉取全部板块类型并更新全局缓存。"""
    ths_dir = (body.ths_dir if body else "") or None
    try:
        return {"data": ths_block_layer.refresh_cache(ths_dir=ths_dir)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块刷新失败：{e}") from e


@app.post("/api/ths-blocks/refresh/{kind}")
def ths_blocks_refresh_kind(kind: str, body: ThsBlockRefreshIn | None = None):
    """刷新单个板块类型并合并进全局缓存。"""
    ths_dir = (body.ths_dir if body else "") or None
    try:
        return {"data": ths_block_layer.refresh_kind(kind=kind, ths_dir=ths_dir)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块刷新失败：{e}") from e


class ThsBlockResolveIn(BaseModel):
    names: list[str] = []


@app.post("/api/ths-blocks/resolve")
def ths_blocks_resolve(body: ThsBlockResolveIn | None = None):
    """批量解析板块名称，返回匹配状态与同花顺板块引用。"""
    names = (body.names if body else []) or []
    try:
        return {"data": ths_block_layer.export_resolve(names)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"板块解析失败：{e}") from e


@app.get("/api/ths-blocks/index-info")
def ths_blocks_index_info():
    """返回板块名称索引是否就绪及规模。"""
    return {"data": ths_block_layer.index_info()}


@app.get("/api/ths-blocks/stocks")
def ths_blocks_stocks(
    kind: str = Query(..., description="板块大类型"),
    block_id: str = Query(..., alias="block_id", description="板块 ID"),
):
    """单板块成分股（需先刷新板块缓存）。"""
    try:
        return {"data": ths_block_layer.get_block_stocks(kind=kind, block_id=block_id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"读取成分股失败：{e}") from e
