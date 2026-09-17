import { useState, useEffect, useMemo, useRef, Fragment, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { pctColor } from "@/lib/colors";
import {
  Sparkles, Loader2, RefreshCw, TrendingUp, TrendingDown,
  Flame, BarChart3, Waves,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { finite } from "@/lib/agent";
import { fmtCountPct, fmtCountPermille, marketTotal } from "@/lib/marketRatio";
import { api, type MarketOverview, type TurnoverTop, type Quote } from "@/lib/api";
import {
  fetchFocusBlocks,
  fetchLiveEmotion,
  fetchLiveZtEffect,
  fetchLianbanEmotion,
  fetchMarketSession,
  fetchMoodBlocks,
  fetchShortBoard,
  type FocusBlockItem,
  type FocusBlocksSnapshot,
  type LiveEmotion,
  type LiveZtEffect,
  type LianbanStock,
  type MarketSession,
  type MoodBlocksSnapshot,
  type ShortBoardEnv,
  type ShortBoardSnapshot,
  type ShortTermEmotion,
} from "@/lib/liveBoard";
import {
  fetchBoardEmotionResonance,
  formatResonanceScore,
  resonanceLabelClass,
  type BoardEmotionResonanceSnapshot,
} from "@/lib/boardEmotionResonance";
import { useDeepDive, DeepDivePanel, RunAllButton, type DiveItem } from "@/components/ui/DeepDive";
import { cn } from "@/lib/utils";
import { StockLabel } from "@/components/stock/StockLabel";
import { BlockLabel } from "@/components/block/BlockLabel";
import { BlockResolveScope } from "@/components/block/BlockResolveContext";
import { SectionPopupButton } from "@/components/SectionPopupButton";
import { delayUntilNextUnixSlot, SPRITE_SLOT_MS } from "@/lib/wallClock";
import { pingShortSprite } from "@/lib/shortSprite";
import { SortTh, type SortOrder } from "@/components/ui/SortTh";

const AUTO_KEY = "vibe-astock-short-board-auto-refresh";
const LIVE_MS = SPRITE_SLOT_MS;
const HEAVY_MS = 60_000;

type FocusSortKey = "name" | "power" | "pct" | "m_net" | "zt";

const FOCUS_SORT_DEFAULTS: Record<FocusSortKey, SortOrder> = {
  name: "asc",
  power: "desc",
  pct: "desc",
  m_net: "desc",
  zt: "desc",
};

function focusSortValue(b: FocusBlockItem, key: FocusSortKey): number | string | null {
  if (key === "name") return b.name || "";
  const v = b.today?.[key];
  return v == null || Number.isNaN(v) ? null : v;
}

const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null | undefined) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`);
const yiCompact = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "—";
  const n = v / 1e8;
  return `${n.toLocaleString("zh-CN", { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 2 })}亿`;
};

export type TabKey = "emotion" | "turnover" | "sectors" | "mood" | "focus" | "rotation";

export type ShortBoardPopoutSection =
  | "market"
  | "emotion"
  | "tab-emotion"
  | "tab-turnover"
  | "tab-sectors"
  | "tab-mood"
  | "tab-focus"
  | "tab-rotation";

export const SHORT_BOARD_POPOUT_TITLES: Record<ShortBoardPopoutSection, string> = {
  market: "市场整体",
  emotion: "短线情绪",
  "tab-emotion": "昨日短线情绪",
  "tab-turnover": "全市场成交额 TOP20",
  "tab-sectors": "板块资金趋势榜",
  "tab-mood": "板块人气",
  "tab-focus": "重点板块跟踪",
  "tab-rotation": "资金轮动",
};

export const SHORT_BOARD_TABS: { key: TabKey; label: string }[] = [
  { key: "emotion", label: "昨日短线情绪" },
  { key: "focus", label: "重点板块跟踪" },
  { key: "mood", label: "板块人气" },
  { key: "turnover", label: "全市场成交额 TOP20" },
  { key: "sectors", label: "板块资金趋势榜" },
  { key: "rotation", label: "资金轮动" },
];

const DEFAULT_TAB: TabKey = "emotion";
const TAB_KEY_SET = new Set<string>(SHORT_BOARD_TABS.map((t) => t.key));

/** 从 URL ?tab= 解析底部标签；非法或缺省时回落到默认签 */
function parseTabParam(raw: string | null): TabKey {
  if (raw && TAB_KEY_SET.has(raw)) return raw as TabKey;
  return DEFAULT_TAB;
}

function tabFromPopout(section?: ShortBoardPopoutSection): TabKey | null {
  if (!section?.startsWith("tab-")) return null;
  const key = section.slice(4);
  return TAB_KEY_SET.has(key) ? (key as TabKey) : null;
}

function SectionHead({
  title, icon, caliber, hint, onRefresh, refreshing, extra,
}: {
  title: string;
  icon?: ReactNode;
  caliber?: string;
  hint?: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  extra?: ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
        {icon} {title}
        {caliber && <Caliber text={caliber} />}
      </h3>
      {hint}
      <span className="ml-auto flex items-center gap-2">
        {extra}
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="text-muted-foreground hover:text-primary"
            title="刷新本区"
          >
            {refreshing
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        )}
      </span>
    </div>
  );
}

/** 今日 / 昨日对照卡。色规则对齐 awam TwoDataProp：今日相对昨日更大→红（reversed 则相反）。
 *  无昨日归档时右侧固定 `/-` 占位，避免只显示今日误以为没有对照能力。 */
function EnvCard({
  name, today, yesterday, format, formatYesterday, reversed, className,
}: {
  name: string;
  today: number | null | undefined;
  yesterday?: number | null;
  format: (v: number) => string;
  formatYesterday?: (v: number) => string;
  reversed?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-[5.5rem] rounded-lg border border-border/50 bg-card/60 px-2.5 py-2 shadow-sm", className)}>
      <p className="truncate text-[11px] font-semibold text-foreground/80">{name}</p>
      <div className="mt-1 border-t border-border/40 pt-1 font-mono text-sm">
        <EnvCompare today={today} yesterday={yesterday} format={format} formatYesterday={formatYesterday} reversed={reversed} />
      </div>
    </div>
  );
}

/** 今/昨斜杠对照（表格内联）；色规则同 EnvCard。 */
function EnvCompare({
  today, yesterday, format, formatYesterday, reversed, className,
}: {
  today: number | null | undefined;
  yesterday?: number | null;
  format: (v: number) => string;
  formatYesterday?: (v: number) => string;
  reversed?: boolean;
  className?: string;
}) {
  const fmtY = formatYesterday ?? format;
  const hasT = today != null && Number.isFinite(today);
  const hasY = yesterday != null && Number.isFinite(yesterday);
  let color = "text-foreground";
  if (hasT && hasY && today !== yesterday) {
    const bigger = reversed ? (yesterday as number) > (today as number) : (today as number) > (yesterday as number);
    color = bigger ? "text-danger" : "text-success";
  } else if (hasT && !reversed && (today as number) > 0) {
    color = "text-danger";
  } else if (hasT && !reversed && (today as number) < 0) {
    color = "text-success";
  }
  return (
    <span className={cn("font-mono", className)}>
      <span className={cn("font-bold", hasT ? color : "text-muted-foreground/40")}>
        {hasT ? format(today as number) : "—"}
      </span>
      <span className="text-muted-foreground">/{hasY ? fmtY(yesterday as number) : "-"}</span>
    </span>
  );
}

/** 文本类今日/昨日对照（阶段、龙头等）。 */
function EnvTextCard({
  name, today, yesterday, accent,
}: {
  name: string;
  today?: string | null;
  yesterday?: string | null;
  accent?: string;
}) {
  const hasT = Boolean(today);
  const hasY = Boolean(yesterday);
  return (
    <div className="min-w-[6.5rem] max-w-[11rem] rounded-lg border border-border/40 bg-background/50 px-2.5 py-2">
      <p className="truncate text-[11px] font-semibold text-foreground/70">{name}</p>
      <div className="mt-1 border-t border-border/30 pt-1 text-sm leading-snug">
        <span className={cn("font-semibold", hasT ? (accent || "text-foreground") : "text-muted-foreground/40")}>
          {hasT ? today : "—"}
        </span>
        <span className="text-muted-foreground/70">/{hasY ? yesterday : "-"}</span>
      </div>
    </div>
  );
}

function EnvThemesCard({
  today, yesterday,
}: {
  today?: string[] | null;
  yesterday?: string[] | null;
}) {
  const t = today?.filter(Boolean) ?? [];
  const y = yesterday?.filter(Boolean) ?? [];
  return (
    <div className="min-w-[12rem] flex-1 rounded-lg border border-border/40 bg-background/50 px-2.5 py-2">
      <p className="truncate text-[11px] font-semibold text-foreground/70">主线题材</p>
      <div className="mt-1 border-t border-border/30 pt-1.5">
        {t.length ? (
          <div className="flex flex-wrap gap-1">
            {t.map((theme) => (
              <span
                key={theme}
                className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 dark:text-amber-300"
              >
                {theme}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground/40">—</span>
        )}
        <p className="mt-1.5 truncate text-[10px] text-muted-foreground/60" title={y.join(" · ") || undefined}>
          昨 {y.length ? y.join(" · ") : "-"}
        </p>
      </div>
    </div>
  );
}

function EnvGroup({
  label, hint, caliber, children, tone = "default",
}: {
  label: string;
  hint?: string;
  caliber?: string;
  children: ReactNode;
  tone?: "default" | "qcj";
}) {
  return (
    <div
      className={cn(
        "rounded-lg p-2.5",
        tone === "qcj"
          ? "border border-amber-500/35 bg-amber-500/[0.07]"
          : "border border-border/40 bg-muted/15",
      )}
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span
          className={cn(
            "inline-flex items-center gap-1 text-[11px] font-semibold tracking-wide",
            tone === "qcj" ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground",
          )}
        >
          {label}
          {caliber && <Caliber text={caliber} />}
        </span>
        {hint && <span className="text-[10px] text-muted-foreground/55">{hint}</span>}
      </div>
      <div className="flex flex-wrap items-stretch gap-2">{children}</div>
    </div>
  );
}

const QCJ_LEVEL_RANK: Record<string, number> = {
  冰点期: 0,
  退潮期: 1,
  降温期: 2,
  修复期: 3,
  升温期: 4,
  高潮期: 5,
};

function qcjLevelAccent(level?: string | null, prev?: string | null): string | undefined {
  if (!level) return undefined;
  const rank = QCJ_LEVEL_RANK[level];
  if (rank == null) return "text-amber-800 dark:text-amber-300";
  if (prev && QCJ_LEVEL_RANK[prev] != null && rank !== QCJ_LEVEL_RANK[prev]) {
    return rank > QCJ_LEVEL_RANK[prev] ? "text-danger" : "text-success";
  }
  if (rank <= 1) return "text-success";
  if (rank >= 4) return "text-danger";
  return "text-amber-800 dark:text-amber-300";
}

export function ShortBoard({ popoutSection }: { popoutSection?: ShortBoardPopoutSection } = {}) {
  const isPopout = !!popoutSection;
  const popoutTab = tabFromPopout(popoutSection);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = popoutTab ?? parseTabParam(searchParams.get("tab"));
  /** 底部标签写入 URL（默认签不占参数）；弹窗模式由路由段决定，不改 query */
  const setTab = (key: TabKey) => {
    if (isPopout) return;
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (key === DEFAULT_TAB) next.delete("tab");
      else next.set("tab", key);
      if (next.toString() === prev.toString()) return prev;
      return next;
    }, { replace: true });
  };
  const [board, setBoard] = useState<ShortBoardSnapshot | null>(null);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [emotion, setEmotion] = useState<ShortTermEmotion | null>(null);
  const [turnover, setTurnover] = useState<TurnoverTop | null>(null);
  const [moodBlocks, setMoodBlocks] = useState<MoodBlocksSnapshot | null>(null);
  const [focusBlocks, setFocusBlocks] = useState<FocusBlocksSnapshot | null>(null);
  const [session, setSession] = useState<MarketSession | null>(null);
  const [liveEmo, setLiveEmo] = useState<LiveEmotion | null>(null);
  const [ztEffect, setZtEffect] = useState<LiveZtEffect | null>(null);
  const [resonance, setResonance] = useState<BoardEmotionResonanceSnapshot | null>(null);
  const [lianbanQuotes, setLianbanQuotes] = useState<Record<string, Quote>>({});
  const [autoRefresh, setAutoRefresh] = useState<boolean>(
    () => localStorage.getItem(AUTO_KEY) === "1");

  const [boardDone, setBoardDone] = useState(false);
  const [ovDone, setOvDone] = useState(false);
  const [emoDone, setEmoDone] = useState(false);
  const [toDone, setToDone] = useState(false);
  const [moodDone, setMoodDone] = useState(false);
  const [focusDone, setFocusDone] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [focusSortKey, setFocusSortKey] = useState<FocusSortKey>("power");
  const [focusSortOrder, setFocusSortOrder] = useState<SortOrder>("desc");

  const mark = (key: string, on: boolean) => setBusy((b) => ({ ...b, [key]: on }));

  const toggleFocusSort = (key: FocusSortKey) => {
    if (focusSortKey === key) setFocusSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setFocusSortKey(key);
      setFocusSortOrder(FOCUS_SORT_DEFAULTS[key]);
    }
  };

  const sortedFocusBlocks = useMemo(() => {
    const list = [...(focusBlocks?.blocks ?? [])];
    const dir = focusSortOrder === "asc" ? 1 : -1;
    list.sort((a, b) => {
      const av = focusSortValue(a, focusSortKey);
      const bv = focusSortValue(b, focusSortKey);
      if (focusSortKey === "name") {
        const cmp = String(av ?? "").localeCompare(String(bv ?? ""), "zh-CN");
        if (cmp !== 0) return dir * cmp;
      } else {
        if (av == null && bv == null) { /* fall through */ }
        else if (av == null) return 1;
        else if (bv == null) return -1;
        else if (av !== bv) return dir * (Number(av) - Number(bv));
      }
      return (a.name || "").localeCompare(b.name || "", "zh-CN")
        || (a.code || "").localeCompare(b.code || "");
    });
    return list;
  }, [focusBlocks?.blocks, focusSortKey, focusSortOrder]);

  const refreshLianban = (codes: string[]) => {
    if (!codes.length) return;
    api.quote(codes.join(",")).then(setLianbanQuotes).catch(() => {});
  };

  const loadBoard = () => {
    mark("board", true);
    return fetchShortBoard().then(setBoard).catch(() => {})
      .finally(() => { setBoardDone(true); mark("board", false); });
  };
  const loadSentiment = () => {
    mark("sentiment", true);
    return api.marketOverview().then(setOverview).catch(() => {})
      .finally(() => { setOvDone(true); mark("sentiment", false); });
  };
  const loadLiveEmo = () => {
    mark("liveEmo", true);
    return fetchLiveEmotion().then(setLiveEmo).catch(() => {})
      .finally(() => mark("liveEmo", false));
  };
  const loadZtEffect = () => {
    mark("ztEffect", true);
    return fetchLiveZtEffect().then(setZtEffect).catch(() => {})
      .finally(() => mark("ztEffect", false));
  };
  const loadResonance = () => {
    mark("resonance", true);
    return fetchBoardEmotionResonance().then(setResonance).catch(() => {})
      .finally(() => mark("resonance", false));
  };
  const loadEmotion = () => {
    mark("emotion", true);
    return fetchLianbanEmotion().then(setEmotion).catch(() => {})
      .finally(() => { setEmoDone(true); mark("emotion", false); });
  };
  const loadTurnover = () => {
    mark("turnover", true);
    return api.turnoverTop().then(setTurnover).catch(() => {})
      .finally(() => { setToDone(true); mark("turnover", false); });
  };
  const loadMoodBlocks = () => {
    mark("mood", true);
    return fetchMoodBlocks().then(setMoodBlocks).catch(() => {})
      .finally(() => { setMoodDone(true); mark("mood", false); });
  };
  const loadFocusBlocks = () => {
    mark("focus", true);
    return fetchFocusBlocks().then(setFocusBlocks).catch(() => {})
      .finally(() => { setFocusDone(true); mark("focus", false); });
  };
  const loadSectors = () => {
    mark("sectors", true);
    return api.marketOverview().then(setOverview).catch(() => {})
      .finally(() => { setOvDone(true); mark("sectors", false); });
  };
  const loadSession = () => fetchMarketSession().then(setSession).catch(() => {});

  const loadLive = () => Promise.all([
    loadBoard(),
    loadLiveEmo(),
    loadZtEffect(),
    loadResonance(),
    loadSession(),
    Promise.resolve(refreshLianban((emotion?.lianban_stocks ?? []).map((s) => s.code))),
  ]).then(() => pingShortSprite());
  /** 仅拉取指定底部标签所需数据（自动刷新 / 切签各走这一条） */
  const loadTabData = (key: TabKey) => {
    if (key === "emotion") return loadEmotion();
    if (key === "turnover") return loadTurnover();
    if (key === "mood") return loadMoodBlocks();
    if (key === "focus") return loadFocusBlocks();
    // sectors / rotation 同源 marketOverview
    return loadSectors();
  };

  useEffect(() => {
    void loadLive();
    // 首屏：顶部区 + 当前标签；其余标签切过去时再拉
    void loadSentiment();
    void loadTabData(tab);
  }, []);

  useEffect(() => {
    refreshLianban((emotion?.lianban_stocks ?? []).map((s) => s.code));
  }, [emotion?.date, emotion?.lianban_stocks?.length]);

  const liveInFlight = useRef(false);
  const heavyInFlight = useRef(false);
  const tabBootstrapped = useRef(false);
  const activeTabRef = useRef<TabKey>(tab);
  activeTabRef.current = tab;

  // 切到某标签时拉一次（首屏已由上面的 mount effect 加载，跳过第一次）
  useEffect(() => {
    if (!tabBootstrapped.current) {
      tabBootstrapped.current = true;
      return;
    }
    void loadTabData(tab);
  }, [tab]);

  useEffect(() => {
    const live = session?.phase === "盘中" || session?.phase === "集合竞价";
    if (!autoRefresh || !live) return;
    let cancelled = false;
    let liveTimer = 0;
    let heavyTimer = 0;

    const scheduleLive = () => {
      liveTimer = window.setTimeout(tickLive, delayUntilNextUnixSlot());
    };
    const scheduleHeavy = () => {
      heavyTimer = window.setTimeout(tickHeavy, HEAVY_MS);
    };

    const tickLive = () => {
      if (cancelled) return;
      if (liveInFlight.current) {
        scheduleLive();
        return;
      }
      liveInFlight.current = true;
      void Promise.resolve(loadLive()).finally(() => {
        liveInFlight.current = false;
        if (!cancelled) scheduleLive();
      });
    };
    const tickHeavy = () => {
      if (cancelled) return;
      if (heavyInFlight.current) {
        scheduleHeavy();
        return;
      }
      heavyInFlight.current = true;
      const key = activeTabRef.current;
      // 顶部「市场整体」涨跌宽度仍按重载周期刷；底部标签只刷当前选中项
      const tasks: Promise<unknown>[] = [loadSentiment()];
      if (key !== "sectors" && key !== "rotation") {
        tasks.push(loadTabData(key));
      }
      void Promise.all(tasks).finally(() => {
        heavyInFlight.current = false;
        if (!cancelled) scheduleHeavy();
      });
    };

    scheduleLive();
    scheduleHeavy();
    return () => {
      cancelled = true;
      window.clearTimeout(liveTimer);
      window.clearTimeout(heavyTimer);
    };
  }, [autoRefresh, session?.phase]);

  const closeSettledRef = useRef(false);
  const sawLiveRef = useRef(false);
  useEffect(() => {
    const live = session?.phase === "盘中" || session?.phase === "集合竞价";
    if (live) {
      sawLiveRef.current = true;
      closeSettledRef.current = false;
      return;
    }
    if (!autoRefresh || !sawLiveRef.current) return;
    if (session?.phase !== "已收盘") return;
    if (closeSettledRef.current) return;
    closeSettledRef.current = true;
    void loadLive();
    void loadSentiment();
    void loadTabData(activeTabRef.current);
  }, [autoRefresh, session?.phase]);

  const toggleAuto = () => {
    const next = !autoRefresh;
    setAutoRefresh(next);
    localStorage.setItem(AUTO_KEY, next ? "1" : "0");
  };

  const liveNow = session?.phase === "盘中" || session?.phase === "集合竞价";
  const today = new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });

  const pending = (done: boolean) => (
    <p className="py-4 text-center text-sm text-muted-foreground/60">
      {done ? "暂无数据：可能是非交易时段或数据暂时不可用" : "加载中…"}
    </p>
  );

  const sentiment = overview?.sentiment;
  const sentY = sentiment?.yesterday || {};
  const sentTotal = marketTotal(undefined, sentiment?.up, sentiment?.down, sentiment?.flat);
  const sentTotalY = marketTotal(undefined, sentY.up, sentY.down, sentY.flat);
  const sectors = overview?.sectors || [];
  const ley = liveEmo?.yesterday || {};
  const zteY = ztEffect?.yesterday || {};
  const pctEmo = (v: number) => `${(v * 100).toFixed(1)}%`;

  const dd = useDeepDive("lianban", emotion?.date || "");
  const lianbanPrompt = (s: LianbanStock) =>
    `${emotion?.date || ""}（已收盘）A 股连板股「${s.name}（${s.code}）」的客观数据：\n` +
    `该日收盘 ${s.price} 元、涨停 +${s.pct}%，已连续涨停 ${s.boards} 天（${s.boards} 连板），` +
    (finite(lianbanQuotes[s.code]?.change_pct) !== null
      ? `今日最新 ${lianbanQuotes[s.code].price} 元（${lianbanQuotes[s.code].change_pct > 0 ? "+" : ""}${lianbanQuotes[s.code].change_pct}%，实时、非收盘），`
      : "") +
    `成交额 ${yi(s.amount)}，流通市值 ${yi(s.float_cap)}，所属概念/行业 ${s.industry || "未知"}，` +
    `涨停原因题材：${s.reason || "（暂缺，需要自查）"}。\n\n` +
    "请深入分析这只股票本轮连板的驱动：\n" +
    "1. 先调用工具查询这只股票的近期新闻与研报，结合上面的题材串，说清本轮连板的核心驱动（消息面 / 题材面 / 资金面），以及走到第 " +
    `${s.boards} 板的位置上驱动有没有变化；\n` +
    "2. 就**这个题材板块整体**说清它的强度与所处阶段（情绪接力 / 有产业逻辑或业绩支撑，发酵期 / 分歧期），" +
    "并给出依据 —— 只讲题材板块层面，不要由此推断这只个股接下来会怎样；\n" +
    "3. 客观列出值得注意的点（连板高度、成交额是放大还是缩量、流通盘大小、题材扩散位置）。\n" +
    "个股层面只陈述已经发生的客观数据与事实，方向与强弱判断做到题材板块层面为止：" +
    "不预测个股涨跌、不给个股参与倾向、不推荐任何标的、不构成投资建议。" +
    "输出用纯 Markdown（不要在表格或正文里使用 <br> 等 HTML 标签）。";
  const lianbanCtx = (s: LianbanStock) => `连板股 ${s.name}(${s.code}) ${s.boards}连板 深入分析`;
  const lianbanItem = (s: LianbanStock): DiveItem => ({ key: s.code, prompt: lianbanPrompt(s), context: lianbanCtx(s) });

  const t: ShortBoardEnv = board?.today || {};
  const y: ShortBoardEnv = board?.yesterday || {};
  const volumeActual = t.volume_kind === "actual";
  const fundCaliber =
    "盘中：上证 / A 股为全日预测量能，公式是「今日累计 ÷ 昨日此时 × 昨日全天」；缺昨日此时对照时回退为今日累计额。\n" +
    "定稿后：改为当日真实成交额（收盘累计额，不再外推）。若盘中已经落盘过，收盘后只补一次真实快照覆盖，之后不再打上游。\n" +
    "主力净流入：东财口径；无归档时用日 K 补昨日。\n" +
    "5 日 / 20 日量比：当日 A 股量能 ÷ 此前 N 个交易日均额；盘中用预测量能，定稿后用真实量能。历史用 short_board 落盘与 market_series 两市成交额序列。";
  const intFmt = (v: number) => String(Math.round(v));
  const pct1 = (v: number) => v.toFixed(2);
  const ratioFmt = (v: number) => `${v.toFixed(2)}x`;

  const tabs = SHORT_BOARD_TABS;
  const activeTab = tab;

  const refreshTab = () => { void loadTabData(activeTab); };
  const tabBusy =
    (activeTab === "emotion" && busy.emotion) ||
    (activeTab === "turnover" && busy.turnover) ||
    (activeTab === "mood" && busy.mood) ||
    (activeTab === "focus" && busy.focus) ||
    ((activeTab === "sectors" || activeTab === "rotation") && busy.sectors);

  const showMarket = !isPopout || popoutSection === "market";
  const showEmotion = !isPopout || popoutSection === "emotion";
  const showTabs = !isPopout || !!popoutTab;
  const resonanceHref = resonance?.date
    ? `/short-resonance?date=${encodeURIComponent(resonance.date)}#board-emotion`
    : "/short-resonance#board-emotion";
  const resonanceDefault = resonance?.default;

  const blockNames = useMemo(() => {
    const names: string[] = [];
    for (const s of emotion?.lianban_stocks ?? []) {
      if (s.industry) names.push(s.industry);
    }
    for (const s of sectors) {
      if (s.name) names.push(s.name);
    }
    for (const b of moodBlocks?.blocks ?? []) {
      if (b.name) names.push(b.name);
    }
    for (const b of focusBlocks?.blocks ?? []) {
      if (b.name) names.push(b.name);
    }
    for (const s of turnover?.stocks ?? []) {
      if (s.industry) names.push(s.industry);
    }
    return names;
  }, [emotion?.lianban_stocks, sectors, moodBlocks?.blocks, focusBlocks?.blocks, turnover?.stocks]);

  return (
    <BlockResolveScope names={blockNames}>
    <div>
      {!isPopout && (
      <PageHeader
        title="短线盘面"
        subtitle={`${session?.label ?? today} · 市场整体 / 短线情绪 / 资金一屏盯盘`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleAuto}
              title={autoRefresh
                ? `已开：市场整体与短线情绪每 ${LIVE_MS / 1000} 秒；底部当前标签每 ${HEAVY_MS / 1000} 秒（切换标签会立即刷一次）。只在盘中生效`
                : "开启后在交易时段自动刷新"}
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
              context={`短线盘面：情绪温度 ${t.temperature ?? "—"}，上涨 ${t.n_up ?? "—"}，下跌 ${t.n_down ?? "—"}，实际涨停 ${t.n_sjzt ?? "—"}；情绪分 ${t.qcj_temp != null ? `${t.qcj_temp}°` : "—"}（${t.qcj_level ?? "—"}），龙头 ${t.qcj_leader ?? "—"}，主线 ${(t.qcj_themes || []).join("、") || "—"}`}
              label="问 AI"
              suggestions={["今天短线情绪怎么样", "炸板率和涨停溢价怎么读", "资金面有什么信号"]}
            />
            <Link
              to="/short-sprite"
              target="_blank"
              rel="noreferrer"
              className="text-sm text-primary/80 hover:text-primary"
            >
              短线精灵
            </Link>
            <SectionPopupButton
              compact
              path="/popout/short-sprite"
              windowName="va-popout-short-sprite"
              title="短线精灵命中弹窗"
            />
          </div>
        }
      />
      )}

      {/* 1. 市场整体：涨跌宽度 + 资金量能 */}
      {showMarket && (<>
      <SectionHead
        title="市场整体"
        icon={<BarChart3 className="h-4 w-4" />}
        caliber={
          "场次对照：左侧 = 行情所属场次，右侧 = 其前一交易日（周末展示周五 vs 周四）。\n" +
          "归档只在「日历今天就是这场」且处于收盘落盘窗（收盘前 5 秒至收盘后）时写入。\n" +
          "涨跌宽度：情绪温度（衡量整个市场的情绪）、大盘宽度、题材投机、上涨/下跌/平盘家数、活跃度；按日归档作昨日对照。\n" +
          "资金量能：盘中为预测量能（今日累计÷昨日此时×昨日全天），定稿后改为真实成交额且只补一次收盘快照；主力净流入；缺失字段按可用行情补全。\n" +
          "5 日 / 20 日量比：当日 A 股量能 ÷ 此前 N 个交易日均额；盘中用预测量能，定稿后用真实量能。历史用 short_board 落盘与 market_series 两市成交额序列。\n" +
          "颜色：相对昨日变强/变多为红（下跌类指标相反）。"
        }
        hint={
          <span className="text-[11px] text-muted-foreground/50">
            {board?.date && (
              <>
                {board.date}
                {board.prev_date && <> · 对照 {board.prev_date}</>}
                {board.is_live === false && <> · 非实时场次</>}
              </>
            )}
            {board?.updated && <> · 更新于 {board.updated}</>}
          </span>
        }
        onRefresh={() => { loadBoard(); loadSentiment(); }}
        refreshing={busy.board || busy.sentiment}
        extra={!isPopout ? (
          <SectionPopupButton
            compact
            path="/popout/short-board/market"
            windowName="va-popout-sb-market"
            title="独立窗口打开市场整体"
          />
        ) : undefined}
      />
      <GlassCard className="mb-6 !p-3">
        {!board?.available && boardDone ? (
          <p className="py-3 text-center text-sm text-muted-foreground/60">
            {board?.reason || "环境指标暂不可用"}
          </p>
        ) : !boardDone && !board ? (
          pending(false)
        ) : (
          <div className="space-y-2.5">
            <EnvGroup label="涨跌宽度" hint="情绪温度衡量整个市场情绪 · 宽度 · 活跃度">
              <EnvCard name="情绪温度" today={t.temperature} yesterday={y.temperature} format={intFmt} />
              <EnvTextCard name="大盘宽度" today={sentiment?.breadth} yesterday={sentY.breadth} />
              <EnvTextCard name="题材投机" today={sentiment?.speculation} yesterday={sentY.speculation} />
              <EnvCard
                name="上涨数"
                today={sentiment?.up}
                yesterday={sentY.up}
                format={(v) => fmtCountPct(v, sentTotal)}
                formatYesterday={(v) => fmtCountPct(v, sentTotalY)}
              />
              <EnvCard
                name="下跌数"
                today={sentiment?.down}
                yesterday={sentY.down}
                format={(v) => fmtCountPct(v, sentTotal)}
                formatYesterday={(v) => fmtCountPct(v, sentTotalY)}
                reversed
              />
              <EnvCard name="平盘" today={sentiment?.flat} yesterday={sentY.flat} format={intFmt} />
              <EnvTextCard name="活跃度" today={sentiment?.active} yesterday={sentY.active} />
            </EnvGroup>
            <EnvGroup
              label="资金量能"
              hint={volumeActual ? "真实量能 · 主力净流入 · 量比" : "预测量能 · 主力净流入 · 量比"}
              caliber={fundCaliber}
            >
              <EnvCard name={volumeActual ? "上证量能" : "上证预测量能"} today={t.v_sh} yesterday={y.v_sh} format={yiCompact} />
              <EnvCard name={volumeActual ? "A股量能" : "A股预测量能"} today={t.v_ca} yesterday={y.v_ca} format={yiCompact} />
              <EnvCard name="主力净流入" today={t.m_net} yesterday={y.m_net} format={yiCompact} />
              <EnvCard name="5日量比" today={t.vol_ratio_5d} yesterday={y.vol_ratio_5d} format={ratioFmt} />
              <EnvCard name="20日量比" today={t.vol_ratio_20d} yesterday={y.vol_ratio_20d} format={ratioFmt} />
            </EnvGroup>
          </div>
        )}
      </GlassCard>
      </>)}

      {/* 2. 短线情绪：情绪全景 + 打板质量 */}
      {showEmotion && (<>
      <SectionHead
        title="短线情绪"
        icon={<Flame className="h-4 w-4" />}
        caliber={
          "场次对照：左侧 = 行情所属场次，右侧 = 其前一交易日（周末展示周五 vs 周四）。\n" +
          "情绪全景：情绪分°（偏向连板情绪与赚钱效应）、阶段、涨跌停家数、龙头、主线题材；昨日场次优先取历史序列。\n" +
          "实时打板：连板高度 / 连板家数 / 晋级率 / 炸板家数随盘刷新；晋级率分母为上一场涨停家数。\n" +
          "昨涨停效应：打板成功率开 / 连板溢价 / 昨涨停跌超5%；昨涨停名单与开盘溢价按日缓存，仅涨跌幅随盘刷新。\n" +
          "颜色：相对昨日变强/变多为红（下跌类指标相反）。"
        }
        hint={
          <span className="text-[11px] text-muted-foreground/50">
            {board?.date && (
              <>
                {board.date}
                {board.prev_date && <> · 对照 {board.prev_date}</>}
                {board.is_live === false && <> · 非实时场次</>}
              </>
            )}
            {liveEmo?.available && (
              <>
                {(board?.date || board?.updated) && " · "}
                <span className="text-warning">
                  打板 {liveEmo.date} {liveEmo.as_of}
                  {liveEmo.is_live === false ? "（定稿）" : "（随盘）"}
                </span>
              </>
            )}
            {board?.updated && <> · 更新于 {board.updated}</>}
          </span>
        }
        onRefresh={() => { loadBoard(); loadLiveEmo(); loadZtEffect(); loadResonance(); }}
        refreshing={busy.board || busy.liveEmo || busy.ztEffect || busy.resonance}
        extra={!isPopout ? (
          <SectionPopupButton
            compact
            path="/popout/short-board/emotion"
            windowName="va-popout-sb-emotion"
            title="独立窗口打开短线情绪"
          />
        ) : undefined}
      />
      <GlassCard className="mb-6 !p-3">
        {!board?.available && boardDone ? (
          <p className="py-3 text-center text-sm text-muted-foreground/60">
            {board?.reason || "环境指标暂不可用"}
          </p>
        ) : !boardDone && !board ? (
          pending(false)
        ) : (
          <div className="space-y-2.5">
            <EnvGroup label="情绪全景" hint="情绪分°偏连板与赚钱效应 · 阶段 · 龙头 · 主线" tone="qcj">
              <EnvCard
                name="情绪分°"
                today={t.qcj_temp}
                yesterday={y.qcj_temp}
                format={(v) => `${Math.round(v)}°`}
                className="border-amber-500/25 bg-background/40"
              />
              <EnvTextCard
                name="阶段"
                today={t.qcj_level}
                yesterday={y.qcj_level}
                accent={qcjLevelAccent(t.qcj_level, y.qcj_level)}
              />
              <EnvCard
                name="涨停"
                today={t.qcj_zt}
                yesterday={y.qcj_zt}
                format={(v) => fmtCountPermille(v, sentTotal)}
                formatYesterday={(v) => fmtCountPermille(v, sentTotalY)}
                className="border-amber-500/25 bg-background/40"
              />
              <EnvCard
                name="跌停"
                today={t.qcj_dt}
                yesterday={y.qcj_dt}
                format={(v) => fmtCountPermille(v, sentTotal)}
                formatYesterday={(v) => fmtCountPermille(v, sentTotalY)}
                reversed
                className="border-amber-500/25 bg-background/40"
              />
              <EnvTextCard
                name="龙头"
                today={t.qcj_leader_top ? `${t.qcj_leader ?? ""} · ${t.qcj_leader_top}` : t.qcj_leader}
                yesterday={y.qcj_leader_top ? `${y.qcj_leader ?? ""} · ${y.qcj_leader_top}` : y.qcj_leader}
                accent="text-amber-900 dark:text-amber-200"
              />
              <EnvThemesCard today={t.qcj_themes} yesterday={y.qcj_themes} />
            </EnvGroup>
            <EnvGroup
              label="打板质量"
              hint="成功率 · 溢价 · 高度晋级 · 炸板（盘中刷新）"
              caliber={
                "打板成功率开 = 昨日涨停股今日开盘相对昨收红盘的比例（今开 > 昨收，平开不算）。\n" +
                "涨停溢价 = 昨日涨停股今日平均涨跌幅（选股宝口径）。\n" +
                "连板溢价 = 昨日 2 板及以上个股今日平均涨跌幅（高标承接）。\n" +
                "晋级率 = 今日仍涨停家数 ÷ 上一场涨停家数。\n" +
                "炸板率 = 选股宝炸板率（越高越冷）。\n" +
                "连板高度 / 连板（2板+）/ 炸板家数 = 今日实时打板池读数。\n" +
                "昨涨停跌超5% = 昨日涨停池里，今日涨跌幅 ≤ −5% 的只数（恰好 −5% 也算；不是全市场跌超 5%）。"
              }
            >
              <EnvCard
                name="打板成功率开"
                today={ztEffect?.open_success_rate}
                yesterday={zteY.open_success_rate}
                format={pctEmo}
              />
              <EnvCard name="涨停溢价(%)" today={t.zt_avg_zr} yesterday={y.zt_avg_zr} format={pct1} />
              <EnvCard
                name="连板溢价(%)"
                today={ztEffect?.consec_premium_avg}
                yesterday={zteY.consec_premium_avg}
                format={pct1}
              />
              <EnvCard
                name="晋级率"
                today={liveEmo?.promotion_rate}
                yesterday={ley.promotion_rate}
                format={pctEmo}
              />
              <EnvCard name="炸板率(%)" today={t.broken_r} yesterday={y.broken_r} format={pct1} reversed />
              <EnvCard
                name="连板高度"
                today={liveEmo?.max_boards}
                yesterday={ley.max_boards}
                format={(v) => `${Math.round(v)} 板`}
              />
              <EnvCard
                name="连板（2板+）"
                today={liveEmo?.lianban_count}
                yesterday={ley.lianban_count}
                format={(v) => `${fmtCountPermille(v, sentTotal)} 家`}
                formatYesterday={(v) => `${fmtCountPermille(v, sentTotalY)} 家`}
              />
              <EnvCard
                name="昨涨停跌超5%"
                today={ztEffect?.deep_loss_5_count}
                yesterday={zteY.deep_loss_5_count}
                format={intFmt}
                reversed
              />
              <EnvCard
                name="炸板家数"
                today={liveEmo?.zb_count}
                yesterday={ley.zb_count}
                format={intFmt}
                reversed
              />
            </EnvGroup>
          </div>
        )}
        <Link
          to={resonanceHref}
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 flex flex-wrap items-center gap-3 rounded-lg border border-border/40 bg-muted/15 px-3 py-2.5 transition-colors hover:border-primary/40 hover:bg-primary/5"
        >
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold tracking-wide text-muted-foreground">
            <Waves className="h-3.5 w-3.5" /> 打板情绪共振
          </span>
          <span className={cn("font-mono text-lg font-bold tabular-nums", pctColor(resonanceDefault?.score ?? null))}>
            {formatResonanceScore(resonanceDefault?.score ?? null)}
          </span>
          <span className={cn("text-sm font-semibold", resonanceLabelClass(resonanceDefault?.label || "不足"))}>
            {resonanceDefault?.label || (busy.resonance ? "…" : "不足")}
          </span>
          <span className="ml-auto text-[11px] text-primary/80">查看中间过程 →</span>
        </Link>
      </GlassCard>
      </>)}

      {/* 3. 标签页：昨日短线情绪 / 重点跟踪 / 板块人气 / 成交额 / 板块资金 / 资金轮动 */}
      {showTabs && (<>
      {!isPopout && (
      <div className="mb-3 flex flex-wrap items-center gap-1 border-b border-border/50 pb-0">
        {tabs.map((tItem) => (
          <div key={tItem.key} className="relative flex items-center gap-0.5">
            <button
              onClick={() => setTab(tItem.key)}
              className={cn(
                "relative px-3 py-2 text-sm transition-colors",
                activeTab === tItem.key
                  ? "font-semibold text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tItem.label}
              {activeTab === tItem.key && (
                <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />
              )}
            </button>
            <SectionPopupButton
              compact
              path={`/popout/short-board/tab-${tItem.key}`}
              windowName={`va-popout-sb-tab-${tItem.key}`}
              title={`独立窗口打开${tItem.label}`}
              className="mb-0.5"
              features="popup=yes,width=960,height=720,left=60,top=60,resizable=yes,scrollbars=yes"
            />
          </div>
        ))}
        <button
          onClick={refreshTab}
          className="ml-auto mb-1 text-muted-foreground hover:text-primary"
          title="刷新当前标签"
        >
          {tabBusy
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="h-3.5 w-3.5" />}
        </button>
      </div>
      )}
      {isPopout && popoutTab && (
        <div className="mb-2 flex items-center justify-end">
          <button
            onClick={refreshTab}
            className="text-muted-foreground hover:text-primary"
            title="刷新"
          >
            {tabBusy
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}

      {activeTab === "emotion" && (
        <GlassCard className="mb-6">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/60">
            <Caliber text={
              "表里的「行业 / 概念」经常只有四个字——行业名称常被截断为四字，不是这里显示不全。"
            } />
            <span>已收盘那一场的定稿 · 连板股 · 客观公开榜单</span>
            {emotion?.date && (
              <span className="ml-auto">{emotion.date} 收盘定稿 · 只有表格里标（实时）的两列随盘刷新</span>
            )}
          </div>
          {!emotion || !Array.isArray(emotion.lianban_stocks) ? (
            pending(emoDone)
          ) : (
            <div>
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <p className="text-[11px] text-muted-foreground">连板股（2 板以上连续涨停）· 客观公开榜单，非推荐 / 非预测</p>
                  <span className="ml-auto">
                    <RunAllButton
                      dd={dd}
                      items={emotion.lianban_stocks.map(lianbanItem)}
                      nameOf={(k) => emotion.lianban_stocks.find((s) => s.code === k)?.name || k}
                    />
                  </span>
                </div>
                {emotion.lianban_stocks.length === 0 ? (
                  <p className="text-xs text-muted-foreground/50">今日无 2 板以上个股</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                          {["名称", "连板", "现价（实时）", "今日涨跌（实时）", "昨日成交额", "流通市值", "涨停原因", "概念", ""].map((h) => (
                            <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {emotion.lianban_stocks.map((s) => (
                          <Fragment key={s.code}>
                            <tr className="border-b border-border/30">
                              <td className="px-2 py-2"><StockLabel code={s.code} name={s.name} /></td>
                              <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                              <td className="px-2 py-2 font-mono">
                                {lianbanQuotes[s.code]?.price ?? (
                                  <span className="text-muted-foreground/50" title="实时行情未取到，显示昨收">{s.price}</span>
                                )}
                              </td>
                              <td className={cn("px-2 py-2 font-mono", pctColor(finite(lianbanQuotes[s.code]?.change_pct)))}>
                                {finite(lianbanQuotes[s.code]?.change_pct) !== null
                                  ? `${lianbanQuotes[s.code].change_pct > 0 ? "+" : ""}${lianbanQuotes[s.code].change_pct}%`
                                  : <span className="text-muted-foreground/50" title="实时行情未取到">—</span>}
                              </td>
                              <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                              <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.float_cap)}</td>
                              <td className="max-w-56 px-2 py-2 text-xs">
                                {s.reason ? <span className="text-foreground">{s.reason}</span> : <span className="text-muted-foreground/50">—</span>}
                              </td>
                              <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">
                                {s.industry ? <BlockLabel name={s.industry} /> : "—"}
                              </td>
                              <td className="whitespace-nowrap px-2 py-2 text-right">
                                <button
                                  onClick={() => dd.toggle(lianbanItem(s))}
                                  className="inline-flex items-center gap-1 rounded-lg border border-primary/50 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20"
                                >
                                  {dd.running === s.code ? <Loader2 className="h-3 w-3 animate-spin" /> : dd.open === s.code ? null : <Sparkles className="h-3 w-3" />}
                                  {dd.open === s.code ? "收起" : dd.analysis[s.code] ? "展开" : "深入分析"}
                                </button>
                              </td>
                            </tr>
                            {dd.open === s.code && (
                              <DeepDivePanel
                                dd={dd}
                                stockKey={s.code}
                                colSpan={9}
                                noteTitle={`连板深析 · ${s.name} ${s.boards}板`}
                                onRerun={() => dd.rerun(lianbanItem(s))}
                              />
                            )}
                          </Fragment>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
            </div>
          )}
        </GlassCard>
      )}

      {activeTab === "turnover" && (
        <GlassCard className="mb-6">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/60">
            <BarChart3 className="h-3.5 w-3.5" />
            <Caliber text={
              "沪深京 A 股按当日累计成交额从大到小排。\n" +
              "盘中看到的成交额是「到刷新那一刻为止」的累计值，不是收盘值；总市值按当前价算。"
            } />
            <span>客观公开榜单，非推荐 / 非预测</span>
            {turnover?.updated && <span className="ml-auto">更新于 {turnover.updated}</span>}
          </div>
          {!turnover || turnover.stocks.length === 0 ? (
            pending(toDone)
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["#", "名称", "现价", "涨跌%", "成交额", "总市值", "行业"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {turnover.stocks.map((s, i) => (
                    <tr key={s.code} className="border-b border-border/30">
                      <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                      <td className="px-2 py-2"><StockLabel code={s.code} name={s.name} /></td>
                      <td className="px-2 py-2 font-mono">{s.price ?? "—"}</td>
                      <td className={cn("px-2 py-2 font-mono", s.pct == null ? "text-muted-foreground" : pctColor(s.pct))}>
                        {s.pct == null ? "—" : `${s.pct > 0 ? "+" : ""}${s.pct}%`}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
                      <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.mcap)}</td>
                      <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">
                        {s.industry ? <BlockLabel name={s.industry} /> : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}

      {activeTab === "sectors" && (
        <GlassCard className="mb-6">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/60">
            <TrendingUp className="h-3.5 w-3.5" />
            <Caliber text={
              "净流入 / 流入 / 流出为行业板块资金流的**盘中即时值**，单位亿元，净流入 = 流入 − 流出。\n" +
              "⚠️ 未区分主力资金与全部成交资金，**不能当作主力净流入**来读。"
            } />
            <span>行业 · 按今日净流入排序</span>
          </div>
          {sectors.length === 0 ? (
            pending(ovDone)
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["行业", "涨跌%", "今日净流入", "流入(亿)", "流出(亿)", "成分股数"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sectors.slice(0, 15).map((s) => (
                    <tr key={s.name} className="border-b border-border/30">
                      <td className="px-2 py-2 font-medium"><BlockLabel name={s.name} /></td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.inflow)}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(s.outflow)}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{s.firms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}

      {activeTab === "mood" && (
        <GlassCard className="mb-6">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/60">
            <Flame className="h-3.5 w-3.5" />
            <Caliber text={
              "概念板块人气榜，按人气从高到低排序。\n" +
              "人气、涨跌幅、涨速、主力净额与板块涨停家数；主力净额界面按亿元展示。\n" +
              "客观公开榜单，非推荐 / 非预测。"
            } />
            <span>概念板块 · 按人气排序</span>
            {moodBlocks?.updated && <span className="ml-auto">更新于 {moodBlocks.updated}</span>}
          </div>
          {!moodBlocks?.available || moodBlocks.blocks.length === 0 ? (
            moodBlocks && !moodBlocks.available && moodDone
              ? <p className="py-4 text-center text-sm text-muted-foreground/60">{moodBlocks.reason || "暂无数据"}</p>
              : pending(moodDone)
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    {["#", "板块", "人气", "涨跌幅", "主力净额", "涨速", "涨停"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {moodBlocks.blocks.map((b) => (
                    <tr key={b.code} className="border-b border-border/30">
                      <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{b.sort}</td>
                      <td className="px-2 py-2">
                        <BlockLabel name={b.name} variant="text" className="font-medium" />
                        {" "}
                        <span className="text-xs text-muted-foreground/50">{b.code}</span>
                      </td>
                      <td className={cn("px-2 py-2 font-mono",
                        b.power != null && b.power > 5000 ? "font-bold text-danger" : "")}>
                        {b.power == null ? "—" : b.power.toLocaleString("zh-CN")}
                      </td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(b.pct))}>
                        {b.pct == null ? "—" : `${b.pct > 0 ? "+" : ""}${b.pct.toFixed(2)}%`}
                      </td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(b.m_net))}>
                        {b.m_net == null ? "—" : `${b.m_net > 0 ? "+" : ""}${yiCompact(b.m_net)}`}
                      </td>
                      <td className={cn("px-2 py-2 font-mono", pctColor(b.speed))}>
                        {b.speed == null ? "—" : `${b.speed > 0 ? "+" : ""}${b.speed.toFixed(2)}%`}
                      </td>
                      <td className={cn("px-2 py-2 font-mono",
                        b.zt != null && b.zt >= 5 ? "font-bold text-danger" : "text-muted-foreground")}>
                        {b.zt == null ? "—" : b.zt}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}

      {activeTab === "focus" && (
        <GlassCard className="mb-6">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground/60">
            <BarChart3 className="h-3.5 w-3.5" />
            <Caliber text={
              "跟踪昨日人气>5000 的板块，以及消息关注里收藏的板块。\n" +
              "标签「人气」= 昨人气热点，「收藏」= 关注板块；可同时带两个标签。\n" +
              "人气/涨幅等为开盘啦指定板块点查；涨停来自 PlateAnalysis；昨日人气榜定稿可落盘。\n" +
              "读数格式：今日/昨日（斜杠对照）；相对昨日变大/变强为红，变小为绿。\n" +
              "默认按今日人气倒序；可点击表头切换排序。\n" +
              "今 / 昨按数据场次对照，非日历今天。客观公开数据，非推荐。"
            } />
            <span>
              今 {focusBlocks?.as_of ?? "—"} · 昨 {focusBlocks?.prev ?? "—"}
              {focusBlocks?.hot_power != null ? ` · 人气阈值 ${focusBlocks.hot_power}` : ""}
            </span>
            {focusBlocks?.updated && <span className="ml-auto">更新于 {focusBlocks.updated}</span>}
          </div>
          {!focusBlocks?.available || focusBlocks.blocks.length === 0 ? (
            focusBlocks && !focusBlocks.available && focusDone
              ? <p className="py-4 text-center text-sm text-muted-foreground/60">{focusBlocks.reason || "暂无数据"}</p>
              : pending(focusDone)
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    <SortTh
                      col="name"
                      label="板块"
                      sortCol={focusSortKey}
                      order={focusSortOrder}
                      onSort={toggleFocusSort}
                      className="whitespace-nowrap px-2 py-2 font-medium"
                    />
                    <th className="whitespace-nowrap px-2 py-2 font-medium">标签</th>
                    <SortTh
                      col="power"
                      label="人气"
                      sortCol={focusSortKey}
                      order={focusSortOrder}
                      onSort={toggleFocusSort}
                      className="whitespace-nowrap px-2 py-2 font-medium"
                    />
                    <SortTh
                      col="pct"
                      label="涨幅"
                      sortCol={focusSortKey}
                      order={focusSortOrder}
                      onSort={toggleFocusSort}
                      className="whitespace-nowrap px-2 py-2 font-medium"
                    />
                    <SortTh
                      col="m_net"
                      label="主力净额"
                      sortCol={focusSortKey}
                      order={focusSortOrder}
                      onSort={toggleFocusSort}
                      className="whitespace-nowrap px-2 py-2 font-medium"
                    />
                    <SortTh
                      col="zt"
                      label="涨停"
                      sortCol={focusSortKey}
                      order={focusSortOrder}
                      onSort={toggleFocusSort}
                      className="whitespace-nowrap px-2 py-2 font-medium"
                    />
                  </tr>
                </thead>
                <tbody>
                  {sortedFocusBlocks.map((b) => (
                    <tr key={`${b.code || b.name}-${(b.tags || []).join(",")}`} className="border-b border-border/30">
                      <td className="px-2 py-2">
                        <BlockLabel name={b.name} variant="text" className="font-medium" />
                        {b.code ? (
                          <>
                            {" "}
                            <span className="text-xs text-muted-foreground/50">{b.code}</span>
                          </>
                        ) : (
                          <span className="ml-1 text-xs text-muted-foreground/50">未映射</span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <div className="flex flex-wrap gap-1">
                          {(b.tag_labels || []).map((lab) => (
                            <span
                              key={lab}
                              className={cn(
                                "rounded px-1.5 py-0.5 text-[10px]",
                                lab === "人气"
                                  ? "bg-danger/15 text-danger"
                                  : "bg-amber-500/15 text-amber-700 dark:text-amber-400",
                              )}
                            >
                              {lab}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <EnvCompare
                          today={b.today.power}
                          yesterday={b.yesterday.power}
                          format={(v) => v.toLocaleString("zh-CN")}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <EnvCompare
                          today={b.today.pct}
                          yesterday={b.yesterday.pct}
                          format={(v) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <EnvCompare
                          today={b.today.m_net}
                          yesterday={b.yesterday.m_net}
                          format={(v) => `${v > 0 ? "+" : ""}${yiCompact(v)}`}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <EnvCompare
                          today={b.today.zt}
                          yesterday={b.yesterday.zt}
                          format={(v) => String(Math.round(v))}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}

      {activeTab === "rotation" && (
        <div className="mb-6 grid gap-4 md:grid-cols-2">
          {[
            {
              title: "流入 Top", icon: TrendingUp, color: "text-danger",
              rows: sectors.filter((s) => s.net > 0).slice(0, 6),
              empty: "今日没有行业净流入",
            },
            {
              title: "流出 Top", icon: TrendingDown, color: "text-success",
              rows: sectors.filter((s) => s.net < 0).sort((a, b) => a.net - b.net).slice(0, 6),
              empty: "今日没有行业净流出",
            },
          ].map((col) => (
            <GlassCard key={col.title}>
              <h4 className={cn("mb-3 flex items-center gap-1.5 text-sm font-semibold", col.color)}>
                <col.icon className="h-4 w-4" /> {col.title}
                <Caliber text={
                  "就是板块资金榜的两头：流入榜只放净流入为正的、流出榜只放为负的，各取前六。\n" +
                  "口径：行业资金流盘中即时值，不能当主力净流入读。"
                } />
              </h4>
              {col.rows.length === 0 ? (
                ovDone && sectors.length > 0
                  ? <p className="py-4 text-center text-sm text-muted-foreground/60">{col.empty}</p>
                  : pending(ovDone)
              ) : (
                <div className="space-y-1.5">
                  {col.rows.map((s, i) => (
                    <div key={s.name} className="flex items-center gap-3 border-b border-border/30 pb-1.5 text-sm last:border-0">
                      <span className="w-5 text-xs text-muted-foreground/50">{i + 1}</span>
                      <span className="flex-1 truncate"><BlockLabel name={s.name} /></span>
                      <span className={cn("font-mono text-xs", pctColor(s.pct))}>{s.pct > 0 ? "+" : ""}{s.pct}%</span>
                      <span className={cn("w-20 text-right font-mono text-xs", pctColor(s.net))}>{s.net > 0 ? "+" : ""}{fmt(s.net)} 亿</span>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
      )}
      </>)}

      {!isPopout && <Disclaimer />}
    </div>
    </BlockResolveScope>
  );
}
