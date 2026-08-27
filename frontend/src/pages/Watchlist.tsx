import { Fragment, useEffect, useMemo, useState } from "react";
import { Plus, X, RefreshCw, Star, Loader2, Sparkles, Trash2, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import {
  useDeepDive,
  RunAllButton,
  WatchlistAnalyzePanel,
  type DiveItem,
  type WatchlistAnalyzeTab,
} from "@/components/ui/DeepDive";
import {
  buildWatchlistDeepPrompt,
  buildWatchlistShortPrompt,
  watchlistDeepContext,
  watchlistShortContext,
} from "@/lib/watchlistAnalyze";
import { loadWatchItems, saveWatchItems, addCodes, removeCodes, hydrateFromServer, pullServerWatch, pushServerWatch, type WatchItem } from "@/lib/watchlist";
import { useLiveQuotes, isTradingHours } from "@/hooks/useLiveQuotes";
import { pctColor } from "@/lib/colors";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { StockLabel } from "@/components/stock/StockLabel";

const pct = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);

const LIVE_KEY = "vr-watchlist-live";
const SERVER_PULL_MS = 60_000;

/** 北京时间 YYYYMMDD，供 DeepDive 存档键使用 */
function beijingDateKey(): string {
  const d = new Date();
  const bj = new Date(d.getTime() + d.getTimezoneOffset() * 60_000 + 8 * 3600_000);
  const y = bj.getFullYear();
  const m = String(bj.getMonth() + 1).padStart(2, "0");
  const day = String(bj.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

// localStorage 在隐私模式 / 嵌入式浏览器里可能直接抛异常。读写都要兜底，
// 否则初始化时一抛整个自选股页就白屏（与 lib/watchlist.ts 的处理保持一致）。
const loadLive = (): boolean => {
  try {
    return localStorage.getItem(LIVE_KEY) === "on";
  } catch {
    return false;
  }
};
const saveLive = (on: boolean) => {
  try {
    localStorage.setItem(LIVE_KEY, on ? "on" : "off");
  } catch {
    /* 存储不可用：开关本次会话内仍生效，只是不被记住 */
  }
};

function formatImportTime(value: string | null | undefined): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

type SourceGroup = { source: string; count: number; latest: string | null };

function buildSourceSummary(items: WatchItem[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>();
  for (const it of items) {
    const g = groups.get(it.source) ?? { source: it.source, count: 0, latest: null };
    g.count += 1;
    if (it.updated_at && (!g.latest || it.updated_at > g.latest)) g.latest = it.updated_at;
    groups.set(it.source, g);
  }
  return Array.from(groups.values()).sort((a, b) => {
    const aPlugin = a.source.startsWith("插件：") ? 0 : 1;
    const bPlugin = b.source.startsWith("插件：") ? 0 : 1;
    if (aPlugin !== bPlugin) return aPlugin - bPlugin;
    return a.source.localeCompare(b.source, "zh-CN");
  });
}

export function Watchlist() {
  const [items, setItems] = useState<WatchItem[]>(loadWatchItems);
  const [input, setInput] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  // 实时行情默认**关闭**——开着会持续请求，让用户自己决定要不要开。
  const [live, setLive] = useState(loadLive);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());

  const codes = useMemo(() => items.map((it) => it.code), [items]);
  const sourceSummary = useMemo(() => buildSourceSummary(items), [items]);

  const applyServerItems = (next: WatchItem[] | null) => {
    if (!next?.length) return;
    setItems(next);
  };

  useEffect(() => {
    void hydrateFromServer(() => api.watchlist()).then(applyServerItems);
    const timer = window.setInterval(() => {
      void pullServerWatch(() => api.watchlist()).then(applyServerItems);
    }, SERVER_PULL_MS);
    const onFocus = () => {
      void pullServerWatch(() => api.watchlist()).then(applyServerItems);
    };
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  const { quotes, loading, updatedAt, polling, error, refresh } = useLiveQuotes(codes, live);
  const ddDeep = useDeepDive("watchlist", beijingDateKey());
  const ddShort = useDeepDive("watchlist-short", beijingDateKey());
  const [openCode, setOpenCode] = useState<string | null>(null);
  const [analyzeTab, setAnalyzeTab] = useState<WatchlistAnalyzeTab>("deep");

  const toggleLive = () => {
    setLive((on) => {
      const next = !on;
      saveLive(next);
      return next;
    });
  };

  const persist = (next: WatchItem[]) => {
    setItems(next);
    saveWatchItems(next);
    void pushServerWatch(next, (c) => api.saveWatchlist(c)).then((synced) => {
      if (synced) setItems(synced);
    });
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const keep = new Set(next.map((it) => it.code));
      const out = new Set<string>();
      for (const c of prev) if (keep.has(c)) out.add(c);
      return out;
    });
  };

  const add = () => {
    const { next, added } = addCodes(items, input);
    if (added === 0) {
      setHint(input.trim() ? "没识别到新的 6 位代码（可能已在自选里）" : null);
      setInput("");
      return;
    }
    persist(next);
    setInput("");
    setHint(`已添加 ${added} 只`);
  };
  const remove = (c: string) => {
    persist(removeCodes(items, [c]));
  };

  const allSelected = codes.length > 0 && selected.size === codes.length;
  const someSelected = selected.size > 0;

  const toggleOne = (c: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(codes));
  };

  const removeSelected = () => {
    if (selected.size === 0) return;
    const n = selected.size;
    persist(removeCodes(items, Array.from(selected)));
    setHint(`已删除 ${n} 只`);
  };

  const clearAll = () => {
    if (codes.length === 0) return;
    if (!window.confirm(`确定清空全部 ${codes.length} 只自选股？此操作不可撤销。`)) return;
    const n = codes.length;
    persist([]);
    setHint(`已清空 ${n} 只`);
  };

  const deepItem = (code: string): DiveItem => ({
    key: code,
    prompt: buildWatchlistDeepPrompt(code, quotes[code]),
    context: watchlistDeepContext(code, quotes[code]),
  });

  const shortItem = (code: string): DiveItem => ({
    key: code,
    prompt: buildWatchlistShortPrompt(code, quotes[code]),
    context: watchlistShortContext(code, quotes[code]),
  });

  const ensureAnalyze = (code: string, tab: WatchlistAnalyzeTab) => {
    setOpenCode(code);
    setAnalyzeTab(tab);
    const dd = tab === "deep" ? ddDeep : ddShort;
    const item = tab === "deep" ? deepItem(code) : shortItem(code);
    if (!dd.analysis[code] && dd.running !== code) void dd.rerun(item);
  };

  const closeAnalyze = () => {
    ddDeep.stopAll();
    ddShort.stopAll();
    setOpenCode(null);
  };

  const switchTab = (tab: WatchlistAnalyzeTab) => {
    if (!openCode) return;
    setAnalyzeTab(tab);
    const dd = tab === "deep" ? ddDeep : ddShort;
    const item = tab === "deep" ? deepItem(openCode) : shortItem(openCode);
    if (!dd.analysis[openCode] && dd.running !== openCode) void dd.rerun(item);
  };

  const nameByCode = useMemo(
    () => Object.fromEntries(codes.map((c) => [c, quotes[c]?.name || c])),
    [codes, quotes],
  );

  const batchDiveItems = useMemo(
    () => (someSelected ? codes.filter((c) => selected.has(c)) : codes).map(deepItem),
    [codes, quotes, someSelected, selected],
  );

  const aiContext = useMemo(
    () =>
      codes.length
        ? "我的自选股（本地）：\n" +
          codes
            .map((c) => {
              const q = quotes[c];
              return q
                ? `${q.name}(${c}) 现价${q.price} ${pct(q.change_pct)} PE(TTM)${q.pe_ttm ?? "—"} 换手${q.turnover_pct ?? "—"}%`
                : `${c}（行情未取到）`;
            })
            .join("\n")
        : "还没有自选股。",
    [codes, quotes],
  );

  return (
    <div>
      <PageHeader
        title="自选股"
        subtitle="批量添加 / 批量删除 / 一键清空。上方展示来源与导入时间概览。"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLive}
              title={live ? "关闭实时行情" : "开启实时行情（交易时段每 3 秒自动刷新）"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                live
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="relative flex h-2 w-2">
                {polling && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/70" />
                )}
                <span
                  className={cn(
                    "relative inline-flex h-2 w-2 rounded-full",
                    live ? "bg-primary" : "bg-muted-foreground/40",
                  )}
                />
              </span>
              实时行情
            </button>
            {codes.length > 0 && (
              <AskAiButton
                context={aiContext}
                label="让 AI 读自选"
                suggestions={["这几只里哪些估值偏高", "帮我按赛道分组看看", "各自最大的风险点是什么"]}
              />
            )}
          </div>
        }
      />

      <GlassCard className="mb-4">
        <label className="mb-1.5 block text-xs text-muted-foreground">
          批量添加 —— 粘贴一串代码即可（逗号 / 空格 / 换行都行，自动识别 6 位 A 股代码）
        </label>
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
            }}
            rows={2}
            placeholder={"如：600519 000858, 002463\n300750 688017"}
            className="flex-1 resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            onClick={add}
            className="inline-flex h-9 shrink-0 items-center gap-1.5 self-start rounded-lg bg-primary/15 px-4 text-sm font-medium text-primary shadow-glow hover:bg-primary/25"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
        </div>
        {hint && <p className="mt-2 text-xs text-muted-foreground/70">{hint}</p>}
      </GlassCard>

      {sourceSummary.length > 0 && (
        <GlassCard className="mb-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
            <span className="font-medium text-foreground/90">来源概览</span>
            {sourceSummary.map((g) => (
              <span key={g.source} className="inline-flex flex-wrap items-center gap-1.5">
                <span className={cn(g.source.startsWith("插件：") && "text-primary")}>{g.source}</span>
                <span className="text-muted-foreground/70">{g.count} 只</span>
                {g.latest && (
                  <span className="font-mono text-muted-foreground/60">导入 {formatImportTime(g.latest)}</span>
                )}
              </span>
            ))}
          </div>
        </GlassCard>
      )}

      <GlassCard glow>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 font-semibold">
            <Star className="h-4 w-4 text-primary" /> 自选总览
            <span className="text-xs font-normal text-muted-foreground">（{codes.length}）</span>
          </h3>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/70">
            {codes.length > 0 && (
              <>
                <button
                  onClick={removeSelected}
                  disabled={!someSelected}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs transition-colors",
                    someSelected
                      ? "border-destructive/40 text-destructive hover:bg-destructive/10"
                      : "border-border/40 text-muted-foreground/40 cursor-not-allowed",
                  )}
                  title={someSelected ? `删除已选 ${selected.size} 只` : "先勾选要删除的标的"}
                >
                  <Trash2 className="h-3 w-3" />
                  删除所选{someSelected ? `（${selected.size}）` : ""}
                </button>
                <button
                  onClick={clearAll}
                  className="inline-flex items-center gap-1 rounded-lg border border-border/60 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
                  title="清空全部自选股"
                >
                  <Trash2 className="h-3 w-3" />
                  一键清空
                </button>
                <RunAllButton
                  dd={ddDeep}
                  items={batchDiveItems}
                  selectedOnly={someSelected}
                  nameOf={(k) => nameByCode[k] || k}
                />
              </>
            )}
            {error ? (
              <span className="text-warning">{error}</span>
            ) : (
              <>
                {live && !polling && codes.length > 0 && (
                  <span>{isTradingHours() ? "已暂停（页面未激活）" : "非交易时段 · 已暂停"}</span>
                )}
                {polling && <span className="text-primary/80">实时 · 每 3 秒</span>}
                {updatedAt && (
                  <span className="font-mono">
                    {new Date(updatedAt).toLocaleTimeString("zh-CN", { hour12: false })}
                  </span>
                )}
              </>
            )}
            <button
              onClick={refresh}
              disabled={loading}
              className="text-muted-foreground hover:text-primary"
              title="立即刷新"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </button>
          </div>
        </div>
        {codes.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground/60">
            还没有自选股，用上面的框粘贴一串代码批量添加。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  <th className="w-8 px-2 py-2">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = someSelected && !allSelected;
                      }}
                      onChange={toggleAll}
                      title={allSelected ? "取消全选" : "全选"}
                      className="h-3.5 w-3.5 accent-primary"
                      aria-label="全选"
                    />
                  </th>
                  {["名称", "代码", "现价", "涨跌%", "PE(TTM)", "PB", "换手%", "", "分析"].map((h, i) => (
                    <th key={h || `a${i}`} className="whitespace-nowrap px-2 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const c = item.code;
                  const q = quotes[c];
                  const checked = selected.has(c);
                  return (
                    <Fragment key={c}>
                      <tr className={cn("border-b border-border/30", checked && "bg-primary/5")}>
                        <td className="px-2 py-2.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleOne(c)}
                            className="h-3.5 w-3.5 accent-primary"
                            aria-label={`选择 ${q?.name || c}`}
                          />
                        </td>
                        <td className="px-2 py-2.5"><StockLabel code={c} name={q?.name} variant="nameOnly" /></td>
                        <td className="px-2 py-2.5"><StockLabel code={c} name={q?.name} variant="codeOnly" /></td>
                        <td className={cn("px-2 py-2.5 font-mono", pctColor(q?.change_pct))}>{q ? q.price : "—"}</td>
                        <td className={cn("px-2 py-2.5 font-mono", pctColor(q?.change_pct))}>{q ? pct(q.change_pct) : "—"}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.pe_ttm ?? "—"}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.pb ?? "—"}</td>
                        <td className="px-2 py-2.5 font-mono text-muted-foreground">{q?.turnover_pct ?? "—"}</td>
                        <td className="px-2 py-2.5">
                          <button
                            onClick={() => remove(c)}
                            className="text-muted-foreground/50 hover:text-destructive"
                            title="移除"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </td>
                        <td className="whitespace-nowrap px-2 py-2.5 text-right">
                          <div className="inline-flex flex-wrap items-center justify-end gap-1">
                            <button
                              type="button"
                              onClick={() => {
                                if (openCode === c && analyzeTab === "deep") closeAnalyze();
                                else ensureAnalyze(c, "deep");
                              }}
                              className={cn(
                                "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors",
                                openCode === c && analyzeTab === "deep"
                                  ? "border-primary bg-primary/15 text-primary"
                                  : "border-primary/50 bg-primary/10 text-primary hover:bg-primary/20",
                              )}
                            >
                              {ddDeep.running === c && analyzeTab === "deep" ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <Sparkles className="h-3 w-3" />
                              )}
                              {openCode === c && analyzeTab === "deep" ? "收起" : ddDeep.analysis[c] ? "深度" : "深度分析"}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (openCode === c && analyzeTab === "short") closeAnalyze();
                                else ensureAnalyze(c, "short");
                              }}
                              className={cn(
                                "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors",
                                openCode === c && analyzeTab === "short"
                                  ? "border-secondary bg-secondary/15 text-secondary"
                                  : "border-secondary/50 bg-secondary/10 text-secondary hover:bg-secondary/20",
                              )}
                            >
                              {ddShort.running === c && analyzeTab === "short" ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : (
                                <TrendingUp className="h-3 w-3" />
                              )}
                              {openCode === c && analyzeTab === "short" ? "收起" : ddShort.analysis[c] ? "短线" : "短线分析"}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {openCode === c && (
                        <WatchlistAnalyzePanel
                          openCode={openCode}
                          tab={analyzeTab}
                          onTab={switchTab}
                          onClose={closeAnalyze}
                          ddDeep={ddDeep}
                          ddShort={ddShort}
                          stockKey={c}
                          colSpan={10}
                          stockName={q?.name || c}
                          onRerunDeep={() => void ddDeep.rerun(deepItem(c))}
                          onRerunShort={() => void ddShort.rerun(shortItem(c))}
                        />
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      <Disclaimer />
    </div>
  );
}
