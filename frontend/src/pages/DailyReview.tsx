import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { pctColor } from "@/lib/colors";
import { Loader2, RefreshCw, Plus, X, Globe } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import {
  api, type IndexQuote, type Quote, type GlobalIndex,
  type OverseasSnapshot, type OverseasRow,
} from "@/lib/api";
import { fetchMarketSession, type MarketSession } from "@/lib/liveBoard";
import { loadWatchItems, saveWatchItems, addCodes } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

// A股红涨绿跌。全球市场（美股/港股指数）**也沿用红涨**——与整个看板及东财等中国平台一致。

const AUTO_KEY = "vibe-astock-auto-refresh";
const LIVE_MS = 5_000;      // 轻量行情：腾讯批量，5 秒
const HEAVY_MS = 60_000;    // 全球指数兜底：60 秒

export function DailyReview() {
  const [indices, setIndices] = useState<IndexQuote[]>([]);
  const [idxErr, setIdxErr] = useState(false);
  const [globalIdx, setGlobalIdx] = useState<GlobalIndex[]>([]);
  // 实时行情属于哪一场：盘前接口返回的是上一场收盘，不标出来会被当成今天的
  const [session, setSession] = useState<MarketSession | null>(null);
  // 隔夜外围：指数 + 七姐妹。走自己的接口是为了拿到**行情所属交易日**
  const [oversea, setOversea] = useState<OverseasSnapshot | null>(null);
  // 自动刷新开关：**默认关**（别替用户决定要不要一直打请求），选择记在本地
  const [autoRefresh, setAutoRefresh] = useState<boolean>(
    () => localStorage.getItem(AUTO_KEY) === "1");
  // 关注股票（自选，存本地）
  const [watchItems, setWatchItems] = useState(loadWatchItems);
  const watchCodes = watchItems.map((it) => it.code);
  const [watchQuotes, setWatchQuotes] = useState<Record<string, Quote>>({});
  const [watchInput, setWatchInput] = useState("");
  const [watchLoading, setWatchLoading] = useState(false);

  // 轻量实时组：全是腾讯批量行情，一次一个请求，5 秒一刷不吃力
  const loadLive = () => {
    api.indices().then(setIndices).catch(() => setIdxErr(true));
    api.overseas().then(setOversea).catch(() => {});
    fetchMarketSession().then(setSession).catch(() => {});
  };

  // 重量组：全球指数兜底（隔夜外围挂了才用）
  const loadHeavy = () => {
    api.globalIndices().then(setGlobalIdx).catch(() => {});
  };

  const loadIndices = () => { loadLive(); loadHeavy(); };

  const refreshWatch = (codes: string[]) => {
    if (!codes.length) { setWatchQuotes({}); return; }
    setWatchLoading(true);
    api.quote(codes.join(",")).then(setWatchQuotes).catch(() => {}).finally(() => setWatchLoading(false));
  };

  useEffect(() => {
    loadIndices();
    refreshWatch(watchItems.map((it) => it.code));
  }, []);

  // ⭐ 自动刷新。交易时段用后端 `session.phase`；收盘不刷；cleanup 清两个句柄。
  useEffect(() => {
    const live = session?.phase === "盘中" || session?.phase === "集合竞价";
    if (!autoRefresh || !live) return;

    const liveTimer = setInterval(() => {
      loadLive();
      if (watchCodes.length) refreshWatch(watchCodes);
    }, LIVE_MS);
    const heavyTimer = setInterval(loadHeavy, HEAVY_MS);
    return () => { clearInterval(liveTimer); clearInterval(heavyTimer); };
  }, [autoRefresh, session?.phase, watchCodes]);

  const toggleAuto = () => {
    const next = !autoRefresh;
    setAutoRefresh(next);
    localStorage.setItem(AUTO_KEY, next ? "1" : "0");
  };

  const addWatch = () => {
    const { next, added } = addCodes(watchItems, watchInput);
    setWatchInput("");
    if (!added) return;
    setWatchItems(next);
    saveWatchItems(next);
    refreshWatch(next.map((it) => it.code));
  };

  const removeWatch = (c: string) => {
    const next = watchItems.filter((it) => it.code !== c);
    setWatchItems(next);
    saveWatchItems(next);
    refreshWatch(next.map((it) => it.code));
  };

  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  const liveNow = session?.phase === "盘中" || session?.phase === "集合竞价";

  const dataSummary = indices.length
    ? indices.map((i) => `${i.name} ${i.price}（${i.change_pct > 0 ? "+" : ""}${i.change_pct}%）`).join("；")
    : "（指数数据未取到）";

  return (
    <div>
      <PageHeader
        title="盘面数据"
        subtitle={`${session?.label ?? today} · 指数 / 外围 / 自选（短线情绪见「短线盘面」）`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleAuto}
              title={autoRefresh
                ? `已开：指数/外围/自选每 ${LIVE_MS / 1000} 秒。只在盘中生效`
                : "开启后在交易时段自动刷新行情"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors",
                autoRefresh
                  ? "bg-primary/15 text-primary hover:bg-primary/25"
                  : "text-muted-foreground hover:text-primary",
              )}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", autoRefresh && liveNow && "animate-spin")} />
              {autoRefresh ? (liveNow ? `每 ${LIVE_MS / 1000} 秒自动刷新` : "自动刷新（非交易时段暂停）") : "自动刷新"}
            </button>
            <AskAiButton
              context={`今日大盘数据：${dataSummary}`}
              label="问 AI"
              suggestions={["今天大盘怎么走", "哪些指数领涨领跌", "盘面有什么值得注意"]}
            />
          </div>
        }
      />

      {/* 1. 大盘指数（实时） */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-sm font-semibold text-muted-foreground">大盘指数</h3>
          <Caliber text={
            "涨跌幅对比前一交易日收盘。\n" +
            "「实时」是延时行情，页面上没标截至几点。"
          } />
          {session && (
            <span className={cn("text-[11px]", session.is_today ? "text-muted-foreground/50" : "text-warning")}>
              {session.label}
            </span>
          )}
          {session?.phase === "集合竞价" && (
            <span className="text-[11px] text-muted-foreground/50">还没成交，涨跌幅为 0 是正常的</span>
          )}
        </div>
        <button onClick={loadIndices} className="text-muted-foreground hover:text-primary" title="刷新"><RefreshCw className="h-3.5 w-3.5" /></button>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {indices.length === 0
          ? [1, 2, 3, 4].map((i) => (
              <GlassCard key={i} className="p-3">
                <p className="text-xs text-muted-foreground">{idxErr ? "行情未接通" : "加载中…"}</p>
                <p className="mt-1 font-mono text-lg font-bold text-muted-foreground/40">—</p>
              </GlassCard>
            ))
          : indices.map((i) => (
              <GlassCard key={i.name} className="p-3">
                <p className="truncate text-xs text-muted-foreground">{i.name}</p>
                <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(i.change_pct))}>{i.price}</p>
                <p className={cn("text-xs", pctColor(i.change_pct))}>{i.change_pct > 0 ? "+" : ""}{i.change_pct}%</p>
              </GlassCard>
            ))}
      </div>

      {/* 1b. 隔夜外围：美股 / 港股指数 + 美股七姐妹 */}
      {(oversea?.available || globalIdx.length > 0) && (() => {
        const rows: OverseasRow[] = oversea?.available && oversea.indices?.length
          ? oversea.indices
          : globalIdx.map((g) => ({ name: g.name, price: g.price ?? 0, change_pct: g.change_pct ?? 0,
                                    session: null, region: g.region }));
        const us = rows.filter((r) => r.region === "美股");
        const hk = rows.filter((r) => r.region !== "美股");
        const mag7 = oversea?.available ? (oversea.mag7 ?? []) : [];
        const cell = (r: OverseasRow, sub?: string) => (
          <GlassCard key={r.name} className="p-3">
            <p className="truncate text-xs text-muted-foreground">
              {r.name}{sub && <span className="ml-1 font-mono text-[10px] text-muted-foreground/40">{sub}</span>}
            </p>
            <p className={cn("mt-1 font-mono text-lg font-bold", pctColor(r.change_pct))}>{r.price}</p>
            <p className={cn("text-xs", pctColor(r.change_pct))}>
              {r.change_pct > 0 ? "+" : ""}{r.change_pct}%
            </p>
          </GlassCard>
        );
        return (
          <>
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Globe className="h-4 w-4" /> 隔夜外围</h3>
              <Caliber text={
                "美股港股的涨跌幅都是对比它们各自的前一交易日收盘。\n" +
                "港股在北京时间白天可能正在交易，所以会标「盘中」——那是抓取那一刻的延时行情，没标具体几点。"
              } />
              <span className="text-[11px] text-muted-foreground/50">A 股常看美股 / 港股脸色</span>
              {oversea?.us_label && <span className="text-[11px] text-warning">{oversea.us_label}</span>}
              {oversea?.hk_label && <span className="text-[11px] text-warning">{oversea.hk_label}</span>}
              <button onClick={() => { api.overseas().then(setOversea).catch(() => {}); loadHeavy(); }}
                className="ml-auto text-muted-foreground hover:text-primary" title="刷新外围">
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>

            {us.length > 0 && (
              <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">{us.map((r) => cell(r))}</div>
            )}

            {mag7.length > 0 && (
              <>
                <p className="mb-2 text-[11px] text-muted-foreground/60">
                  美股七姐妹 · 权重股带指数走，看它们比看指数细
                </p>
                <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                  {mag7.map((r) => cell(r, r.ticker))}
                </div>
              </>
            )}

            {hk.length > 0 && (
              <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">{hk.map((r) => cell(r))}</div>
            )}
          </>
        );
      })()}

      {/* 2. 关注股票（自选） */}
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-muted-foreground">关注股票</h3>
        <div className="flex items-center gap-2">
          <Link to="/watchlist" className="text-xs text-primary/80 hover:text-primary">完整自选页 →</Link>
          <Link to="/short-board" className="text-xs text-primary/80 hover:text-primary">短线盘面 →</Link>
          {watchCodes.length > 0 && (
            <button onClick={() => refreshWatch(watchCodes)} className="text-muted-foreground hover:text-primary" title="刷新价格">
              {watchLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>
      <GlassCard className="mb-6">
        <div className="mb-3 flex gap-2">
          <input
            value={watchInput}
            onChange={(e) => setWatchInput(e.target.value.replace(/[^\d,\s]/g, "").slice(0, 80))}
            onKeyDown={(e) => e.key === "Enter" && addWatch()}
            placeholder="加自选：可批量，如 600519 000858"
            className="w-60 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button onClick={addWatch}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-4 py-2 text-sm font-medium text-primary shadow-glow hover:bg-primary/25">
            <Plus className="h-4 w-4" /> 增加
          </button>
        </div>
        {watchCodes.length === 0 ? (
          <p className="text-sm text-muted-foreground/60">加上你关注的股票，随时看它们的实时价格与涨跌。数据存本地，不上传。</p>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {watchCodes.map((c) => {
              const q = watchQuotes[c];
              return (
                <div key={c} className="group relative rounded-lg bg-muted/25 p-3">
                  <button onClick={() => removeWatch(c)} title="移除"
                    className="absolute right-1.5 top-1.5 text-muted-foreground/40 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100">
                    <X className="h-3.5 w-3.5" />
                  </button>
                  {(() => {
                    const ok = q != null && Number.isFinite(q.price) && q.price > 0;
                    return (
                      <>
                        <p className="truncate text-xs text-muted-foreground">{q?.name || c}</p>
                        <p className={cn("mt-1 font-mono text-lg font-bold",
                          ok ? pctColor(q!.change_pct) : "text-muted-foreground/40")}>
                          {ok ? q!.price : "—"}
                        </p>
                        <p className={cn("text-xs", ok ? pctColor(q!.change_pct) : "text-muted-foreground/40")}>
                          {ok ? `${q!.change_pct > 0 ? "+" : ""}${q!.change_pct}%` : "行情不可用"}
                        </p>
                      </>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        )}
      </GlassCard>

      <Disclaimer />
    </div>
  );
}
