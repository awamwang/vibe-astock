import { useState, useEffect, useMemo, Fragment, type ReactNode } from "react";
import { pctColor } from "@/lib/colors";
import {
  Sparkles, Loader2, RefreshCw, TrendingUp, TrendingDown,
  Flame, BarChart3, Radar,
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
  fetchLiveEmotion,
  fetchLianbanEmotion,
  fetchMarketSession,
  fetchMoodBlocks,
  fetchShortBoard,
  type LiveEmotion,
  type LianbanStock,
  type MarketSession,
  type MoodBlocksSnapshot,
  type ShortBoardEnv,
  type ShortBoardSnapshot,
  type ShortTermEmotion,
} from "@/lib/liveBoard";
import { useDeepDive, DeepDivePanel, RunAllButton, type DiveItem } from "@/components/ui/DeepDive";
import { cn } from "@/lib/utils";
import { StockLabel } from "@/components/stock/StockLabel";
import { BlockLabel } from "@/components/block/BlockLabel";
import { BlockResolveScope } from "@/components/block/BlockResolveContext";

const AUTO_KEY = "vibe-astock-short-board-auto-refresh";
const LIVE_MS = 5_000;
const HEAVY_MS = 60_000;

const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null | undefined) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`);
const yiCompact = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "—";
  const n = v / 1e8;
  return `${n.toLocaleString("zh-CN", { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 2 })}亿`;
};

type TabKey = "emotion" | "turnover" | "sectors" | "mood" | "rotation";

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
    <div className={cn("min-w-[5.5rem] rounded-lg border border-border/50 bg-card/60 px-2.5 py-2 shadow-sm", className)}>
      <p className="truncate text-[11px] font-semibold text-foreground/80">{name}</p>
      <div className="mt-1 border-t border-border/40 pt-1 font-mono text-sm">
        <span className={cn("font-bold", hasT ? color : "text-muted-foreground/40")}>
          {hasT ? format(today as number) : "—"}
        </span>
        <span className="text-muted-foreground">/{hasY ? fmtY(yesterday as number) : "-"}</span>
      </div>
    </div>
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
  label, hint, children, tone = "default",
}: {
  label: string;
  hint?: string;
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
      <div className="mb-2 flex items-baseline gap-2">
        <span
          className={cn(
            "text-[11px] font-semibold tracking-wide",
            tone === "qcj" ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground",
          )}
        >
          {label}
        </span>
        {hint && <span className="text-[10px] text-muted-foreground/55">{hint}</span>}
      </div>
      <div className="flex flex-wrap items-stretch gap-2">{children}</div>
    </div>
  );
}

function PlaceholderCard({ name }: { name: string }) {
  return (
    <div className="min-w-[7rem] rounded-lg border border-dashed border-border/60 bg-muted/15 px-2.5 py-2">
      <p className="truncate text-[11px] font-semibold text-muted-foreground/70">{name}</p>
      <p className="mt-1 border-t border-border/30 pt-1 text-xs text-muted-foreground/50">待接入</p>
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

export function ShortBoard() {
  const [board, setBoard] = useState<ShortBoardSnapshot | null>(null);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [emotion, setEmotion] = useState<ShortTermEmotion | null>(null);
  const [turnover, setTurnover] = useState<TurnoverTop | null>(null);
  const [moodBlocks, setMoodBlocks] = useState<MoodBlocksSnapshot | null>(null);
  const [session, setSession] = useState<MarketSession | null>(null);
  const [liveEmo, setLiveEmo] = useState<LiveEmotion | null>(null);
  const [lianbanQuotes, setLianbanQuotes] = useState<Record<string, Quote>>({});
  const [tab, setTab] = useState<TabKey>("emotion");
  const [autoRefresh, setAutoRefresh] = useState<boolean>(
    () => localStorage.getItem(AUTO_KEY) === "1");

  const [boardDone, setBoardDone] = useState(false);
  const [ovDone, setOvDone] = useState(false);
  const [emoDone, setEmoDone] = useState(false);
  const [toDone, setToDone] = useState(false);
  const [moodDone, setMoodDone] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const mark = (key: string, on: boolean) => setBusy((b) => ({ ...b, [key]: on }));

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
  const loadSectors = () => {
    mark("sectors", true);
    return api.marketOverview().then(setOverview).catch(() => {})
      .finally(() => { setOvDone(true); mark("sectors", false); });
  };
  const loadSession = () => fetchMarketSession().then(setSession).catch(() => {});

  const loadLive = () => {
    loadBoard();
    loadLiveEmo();
    loadSession();
    refreshLianban((emotion?.lianban_stocks ?? []).map((s) => s.code));
  };
  const loadHeavy = () => {
    loadSentiment();
    loadTurnover();
    loadMoodBlocks();
  };

  useEffect(() => {
    loadLive();
    loadHeavy();
    loadEmotion();
  }, []);

  useEffect(() => {
    refreshLianban((emotion?.lianban_stocks ?? []).map((s) => s.code));
  }, [emotion?.date, emotion?.lianban_stocks?.length]);

  useEffect(() => {
    const live = session?.phase === "盘中" || session?.phase === "集合竞价";
    if (!autoRefresh || !live) return;
    const liveTimer = setInterval(loadLive, LIVE_MS);
    const heavyTimer = setInterval(loadHeavy, HEAVY_MS);
    return () => { clearInterval(liveTimer); clearInterval(heavyTimer); };
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
  const intFmt = (v: number) => String(Math.round(v));
  const pct1 = (v: number) => v.toFixed(2);

  const tabs: { key: TabKey; label: string }[] = [
    { key: "emotion", label: "昨日短线情绪" },
    { key: "turnover", label: "全市场成交额 TOP20" },
    { key: "sectors", label: "板块资金趋势榜" },
    { key: "mood", label: "板块人气" },
    { key: "rotation", label: "资金轮动" },
  ];

  const refreshTab = () => {
    if (tab === "emotion") loadEmotion();
    else if (tab === "turnover") loadTurnover();
    else if (tab === "mood") loadMoodBlocks();
    else loadSectors();
  };

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
    for (const s of turnover?.stocks ?? []) {
      if (s.industry) names.push(s.industry);
    }
    return names;
  }, [emotion?.lianban_stocks, sectors, moodBlocks?.blocks, turnover?.stocks]);

  return (
    <BlockResolveScope names={blockNames}>
    <div>
      <PageHeader
        title="短线盘面"
        subtitle={`${session?.label ?? today} · 情绪温度 / 打板质量 / 资金一屏盯盘`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleAuto}
              title={autoRefresh
                ? `已开：短线指标每 ${LIVE_MS / 1000} 秒、板块资金 / 成交额 / 板块人气每 ${HEAVY_MS / 1000} 秒。只在盘中生效`
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
          </div>
        }
      />

      {/* 1. 环境指标条 */}
      <SectionHead
        title="短线指标"
        icon={<Radar className="h-4 w-4" />}
        caliber={
          "场次对照：左侧 = 行情所属场次，右侧 = 其前一交易日（周末展示周五 vs 周四）。\n" +
          "归档只在「日历今天就是这场」且处于收盘落盘窗（收盘前 5 秒至收盘后）时写入。\n" +
          "涨跌宽度：情绪温度、大盘宽度、题材投机、上涨/下跌/平盘家数、活跃度；按日归档作昨日对照。\n" +
          "资金量能：上证 / A 股成交额、主力净流入；缺失字段按可用行情补全。\n" +
          "实时打板：最高连板 / 连板家数 / 晋级率 / 炸板家数随盘刷新；晋级率分母为上一场涨停家数。\n" +
          "情绪全景：情绪分、阶段、涨跌停家数、龙头、主线题材；昨日场次优先取历史序列。\n" +
          "颜色：相对昨日变强/变多为红（下跌类指标相反）。\n" +
          "「量能对比昨日」「量能5日，量比」暂未接入，仅占位。"
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
        onRefresh={() => { loadBoard(); loadLiveEmo(); loadSentiment(); }}
        refreshing={busy.board || busy.liveEmo || busy.sentiment}
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
            <EnvGroup label="涨跌宽度" hint="情绪温度 · 宽度 · 活跃度">
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
            <EnvGroup label="资金量能" hint="成交额 · 主力净流入">
              <EnvCard name="上证成交额" today={t.v_sh} yesterday={y.v_sh} format={yiCompact} />
              <EnvCard name="A股成交额" today={t.v_ca} yesterday={y.v_ca} format={yiCompact} />
              <EnvCard name="主力净流入" today={t.m_net} yesterday={y.m_net} format={yiCompact} />
              {board?.placeholders?.volume_vs_yesterday && <PlaceholderCard name="量能对比昨日" />}
              {board?.placeholders?.volume_5d_ratio && <PlaceholderCard name="量能5日，量比" />}
            </EnvGroup>
            <EnvGroup label="打板质量" hint="炸板 · 溢价 · 连板晋级（盘中刷新）">
              <EnvCard name="炸板率(%)" today={t.broken_r} yesterday={y.broken_r} format={pct1} reversed />
              <EnvCard name="涨停溢价(%)" today={t.zt_avg_zr} yesterday={y.zt_avg_zr} format={pct1} />
              <EnvCard
                name="最高连板"
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
                name="晋级率"
                today={liveEmo?.promotion_rate}
                yesterday={ley.promotion_rate}
                format={pctEmo}
              />
              <EnvCard
                name="炸板家数"
                today={liveEmo?.zb_count}
                yesterday={ley.zb_count}
                format={intFmt}
                reversed
              />
            </EnvGroup>
            <EnvGroup label="情绪全景" hint="情绪阶段 · 龙头 · 主线" tone="qcj">
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
          </div>
        )}
      </GlassCard>

      {/* 2. 标签页：昨日短线情绪 / 成交额 / 板块资金 / 板块人气 / 资金轮动 */}
      <div className="mb-3 flex flex-wrap items-center gap-1 border-b border-border/50 pb-0">
        {tabs.map((tItem) => (
          <button
            key={tItem.key}
            onClick={() => setTab(tItem.key)}
            className={cn(
              "relative px-3 py-2 text-sm transition-colors",
              tab === tItem.key
                ? "font-semibold text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tItem.label}
            {tab === tItem.key && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />
            )}
          </button>
        ))}
        <button
          onClick={refreshTab}
          className="ml-auto mb-1 text-muted-foreground hover:text-primary"
          title="刷新当前标签"
        >
          {(busy.emotion || busy.turnover || busy.sectors || busy.mood)
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <RefreshCw className="h-3.5 w-3.5" />}
        </button>
      </div>

      {tab === "emotion" && (
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

      {tab === "turnover" && (
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

      {tab === "sectors" && (
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

      {tab === "mood" && (
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

      {tab === "rotation" && (
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

      <Disclaimer />
    </div>
    </BlockResolveScope>
  );
}
