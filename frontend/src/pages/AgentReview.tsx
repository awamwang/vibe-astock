import { apiUrl } from "@/lib/base";
import { useEffect, useRef, useState } from "react";
import {
  Swords, Loader2, AlertTriangle, Target, CheckSquare, Check, X, Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { AgentChat } from "@/components/AgentChat";
import {
  ConsecPremiumCard, CycleCard, LadderCard, MoneyEffectCard, PromotionCard, splitMetrics,
} from "@/components/EmotionMetricsPanel";
import {
  BoardSystemSection, DiffView, Ledger, LossEffectSection, Matrix, SealQualitySection,
  StatsView, Themes, ThemeTreeView,
} from "@/components/MarketFactsPanel";
import { BreadthPanel } from "@/components/BreadthPanel";
import { TrendPanel } from "@/components/TrendPanel";
import { TradeBudgetCard } from "@/components/TradeBudgetCard";
import {
  agentFetch, agentPost, finite, localDate, phaseTone, safeArray,
  type FocusDirection, type Reflection, type ReviewData, type VerificationItem,
  type VerificationResult, type JobStatus,
} from "@/lib/agent";
import { fmtCountPermille, marketTotal } from "@/lib/marketRatio";
import { api, type TradeBudget } from "@/lib/api";


/** 验证条件里的读数与阈值怎么显示。
 *
 *  三种单位混在一起：家 / 板 是计数，`%` 是已经是百分数的值（赚钱效应中位数 +0.42%），
 *  空单位是 0~1 的比率（晋级率 0.13 = 13%）。混着直接印就会出现「0.13」这种读者
 *  得自己换算的数 —— 与「历史统计位置」那一列犯过的是同一个错。
 */
function formatMetricValue(n: number | null | undefined, unit?: string | null): string {
  const v = finite(n);
  if (v == null) return "—";
  if (unit === "%") return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
  if (!unit) return `${Math.round(v * 100)}%`;
  return `${v}${unit}`;
}

function statText(v: VerificationItem): string {
  return formatMetricValue(v.base_value, v.unit);
}

function epsText(v: VerificationItem): string {
  const e = finite(v.eps);
  if (e == null) return "";
  // 比率与百分数都按"个百分点"说，别写成「超过 0.05」
  if (!v.unit) return `${Math.round(e * 100)} 个百分点`;
  if (v.unit === "%") return `${e} 个百分点`;
  return `${e}${v.unit}`;
}

function pctText(n: number | null | undefined): string {
  const v = finite(n);
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

function shortDate(d?: string | null): string {
  if (!d || d.length < 10) return d || "—";
  return d.slice(5);
}

const METRIC_LABEL: Record<string, string> = {
  limit_up_count: "涨停家数",
  highest_board: "最高连板高度",
  promotion_1to2: "1进2 晋级率",
  money_effect_median: "赚钱效应中位数",
  broken_rate: "炸板率",
  never_broken_rate: "涨停未炸板比例",
  deep_loss_count: "跌超5%家数",
  theme_concentration: "头部题材集中度",
  market_limit_down: "全市场跌停家数",
};

/** 上期验证结果：昨晚立的条件，今天对过账了没有。 */
function VerificationResults({ reflection }: { reflection?: Reflection | null }) {
  const items = safeArray<VerificationResult>(reflection?.verification);
  if (!reflection || items.length === 0) return null;

  const s = reflection.verification_summary;
  const decided = s?.decided ?? 0;
  const hit = s?.hit ?? 0;
  const rate = finite(s?.rate);
  const edge = finite(s?.edge);

  return (
    <div className="mt-5 border-t-2 border-foreground pt-2.5">
      <h4 className="mb-2 flex flex-wrap items-center gap-1.5 text-sm font-bold">
        <CheckSquare className="h-4 w-4 text-primary" /> 上期验证结果
        <span className="text-[11px] font-normal text-muted-foreground">
          {shortDate(reflection.prediction_date)} 立的条件 · {shortDate(reflection.eval_date)} 核验
          {decided > 0 && (
            <> · 命中 {hit}/{decided}{rate != null ? `（${pctText(rate)}）` : ""}</>
          )}
          {edge != null && (
            <> · 超额 {edge > 0 ? "+" : ""}{Math.round(edge * 100)}pp</>
          )}
        </span>
      </h4>
      {s?.edge_note && decided > 0 && (
        <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">{s.edge_note}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {items.map((v, i) => {
          const ok = v.verified;
          const badge = ok === true
            ? { cls: "bg-primary/15 text-primary", icon: Check, text: "成立" }
            : ok === false
              ? { cls: "bg-warning/15 text-warning", icon: X, text: "未成立" }
              : { cls: "bg-muted text-muted-foreground", icon: Minus, text: "不足判定" };
          const Icon = badge.icon;
          return (
            <div key={i} className="flex-1 basis-[240px] rounded-lg border border-border bg-muted/20 px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="text-[13px] font-semibold">
                  {v.label || METRIC_LABEL[v.metric] || v.metric}
                </div>
                <span className={cn("inline-flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] font-bold", badge.cls)}>
                  <Icon className="h-3 w-3" /> {badge.text}
                </span>
              </div>
              <div className="mt-1 text-[11px] tabular-nums text-foreground/70">
                预期{v.expect || "—"}
                <span className="mx-1 text-muted-foreground">·</span>
                实际{v.actual ?? "—"}
              </div>
              <div className="mt-0.5 text-[11px] tabular-nums text-foreground/70">
                {formatMetricValue(v.prev_value, v.unit)}
                <span className="mx-1 text-muted-foreground">→</span>
                {formatMetricValue(v.cur_value, v.unit)}
              </div>
              {v.baseline_note && (
                <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{v.baseline_note}</div>
              )}
              {!v.baseline_note && v.reason && (
                <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{v.reason}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const DISCLAIMER =
  "本页由多 agent AI 基于公开盘面数据（涨跌停/龙虎榜/资金流/题材）现场生成，结论为 AI 判断，仅供参考，不构成投资建议；市场有风险，决策与盈亏自负。";

interface MetricOption {
  key: string; label: string; hint: string; unit: string; higher_is_hotter: boolean;
}

/** 用户自设验证条件 —— AI 挑的是它的判断，自己写下的才会想回来看对没对。
 *  同一指标以用户的为准（后端 merged_items）。*/
function UserConditions({ date }: { date: string }) {
  const [menu, setMenu] = useState<{ metrics: MetricOption[]; directions: string[] } | null>(null);
  const [items, setItems] = useState<VerificationItem[]>([]);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!open || !date) return;
    (async () => {
      try {
        const [m, cur] = await Promise.all([
          agentFetch<{ metrics: MetricOption[]; directions: string[] }>("/api/verification/menu"),
          agentFetch<{ items: VerificationItem[] }>(`/api/verification/items?date=${date}`),
        ]);
        setMenu(m);
        setItems(safeArray<VerificationItem>(cur?.items));
      } catch { setMsg("读取失败"); }
    })();
  }, [open, date]);

  async function save() {
    try {
      const r = await agentPost<{ ok?: boolean; error?: string }>(
        `/api/verification/items?date=${date}`, { items });
      setMsg(r?.error ? r.error : r?.ok ? "已保存，次日自动核验" : "保存失败");
    } catch (e) {
      setMsg(e instanceof Error ? `保存失败：${e.message}` : "保存失败");
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="mt-2 text-[11px] text-primary underline-offset-2 hover:underline">
        + 自己加一条验证条件（自己写下的，明天才会想回来看对没对）
      </button>
    );
  }
  return (
    <div className="mt-3 rounded-lg border border-dashed border-primary/40 p-3">
      <div className="mb-2 text-[12px] font-semibold">
        我自己的验证条件
        <span className="ml-1.5 font-normal text-muted-foreground">
          同一指标以你写的为准，次日与 AI 的一起核验
        </span>
      </div>
      {items.map((it, i) => (
        <div key={i} className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <select value={it.metric}
            onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, metric: e.target.value } : x))}
            className="rounded border border-border bg-card px-2 py-1 text-[12px]">
            {safeArray<MetricOption>(menu?.metrics).map((m) => (
              <option key={m.key} value={m.key} title={m.hint}>{m.label}</option>
            ))}
          </select>
          <select value={it.direction}
            onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, direction: e.target.value } : x))}
            className="rounded border border-border bg-card px-2 py-1 text-[12px]">
            {safeArray<string>(menu?.directions).map((d) => <option key={d} value={d}>预期{d}</option>)}
          </select>
          <input value={it.reason} placeholder="为什么（可选）"
            onChange={(e) => setItems(items.map((x, j) => j === i ? { ...x, reason: e.target.value } : x))}
            className="min-w-[160px] flex-1 rounded border border-border bg-card px-2 py-1 text-[12px]" />
          <button onClick={() => setItems(items.filter((_, j) => j !== i))}
            className="text-muted-foreground/50 hover:text-danger text-[12px]">×</button>
        </div>
      ))}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setItems([...items, {
            metric: safeArray<MetricOption>(menu?.metrics)[0]?.key || "limit_up_count",
            direction: "上升", reason: "",
          }])}
          disabled={items.length >= 8}
          className="rounded border border-border px-2 py-1 text-[11px] hover:bg-muted disabled:opacity-40">
          + 加一条
        </button>
        <button onClick={save}
          className="rounded bg-primary px-3 py-1 text-[11px] font-semibold text-primary-foreground hover:opacity-90">
          保存
        </button>
        {msg && <span className="text-[11px] text-muted-foreground">{msg}</span>}
      </div>
    </div>
  );
}

export function AgentReview() {
  const [data, setData] = useState<ReviewData | null>(null);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [date, setDate] = useState<string>(localDate());
  const [dates, setDates] = useState<string[]>([]);   // 跑过复盘的交易日（历史入口）
  const [missing, setMissing] = useState<string>("");  // 选了某天但那天没跑过
  const [err, setErr] = useState("");
  // 「已复盘/还没收盘」这类不是错误、是正常告知，跟 err 分开显示
  const [notice, setNotice] = useState("");
  const [tradeBudget, setTradeBudget] = useState<TradeBudget | null>(null);
  // polling: 防重入（React state 在同一轮渲染里读到的是旧值，双击能穿过去）
  // timer / alive: 卸载后停掉轮询，别再 setState
  // reqId: 只接受最后一次请求的响应，防止慢的旧响应覆盖新结果
  const polling = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const reqId = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function loadTradeBudget(d?: string) {
    if (!d) { setTradeBudget(null); return; }
    try {
      const b = await api.tradeBudget(d);
      if (alive.current) setTradeBudget(b);
    } catch {
      if (alive.current) setTradeBudget(null);
    }
  }

  /** 读复盘：不传 d 读最近一份；传 d 读那天的历史存档。 */
  async function loadLatest(d?: string) {
    const my = ++reqId.current;
    try {
      const r = await agentFetch<ReviewData>(`/api/review/latest${d ? `?date=${d}` : ""}`);
      if (!alive.current || my !== reqId.current) return;   // 已卸载 / 有更新的请求 → 丢弃
      if (r && (r.target_date || r.trade_date)) {
        setData(r); setMissing("");
        // 没指定日期时（首次加载）把日期框对到真正载入的那一场 ——
        // 默认值是本机今天，而复盘的对象是「最近已收盘那一场」，盘前会差一天
        const day = r.target_date || r.trade_date || "";
        if (!d) setDate(day);
        void loadTradeBudget(day);
      }
      else if (d) { setData(null); setMissing(d); setTradeBudget(null); }         // 这天没跑过 —— 要说出来，不能默默留着上一天的
    } catch {
      if (alive.current && my === reqId.current) setErr("读取历史复盘失败，仍可尝试重新生成");
    }
  }

  // 哪些交易日跑过（历史入口）；日期框旁边列出来，免得靠猜
  async function loadDates() {
    try {
      const r = await agentFetch<{ dates: string[]; today?: string; prev_trade_date?: string | null }>("/api/review/dates");
      if (alive.current) setDates(r.dates || []);
    } catch { /* 拿不到就不显示历史列表，不影响主流程 */ }
  }

  // 首次进入：并行拉最近复盘 + 历史日期；上一交易日已有复盘则日期框推到今天
  useEffect(() => {
    async function bootstrap() {
      const my = ++reqId.current;
      try {
        const [r, datesR] = await Promise.all([
          agentFetch<ReviewData>("/api/review/latest"),
          agentFetch<{ dates: string[]; today?: string; prev_trade_date?: string | null }>("/api/review/dates"),
        ]);
        if (!alive.current || my !== reqId.current) return;

        const archived = datesR.dates || [];
        setDates(archived);

        const today = datesR.today || localDate();
        const prev = datesR.prev_trade_date || "";
        const prevDone = Boolean(prev && archived.includes(prev));

        if (r && (r.target_date || r.trade_date)) {
          setData(r); setMissing("");
          const day = r.target_date || r.trade_date || "";
          // 上一交易日已落盘 → 日期框推到今天，方便接着跑本场；内容仍展示最近一份
          setDate(prevDone ? today : day);
          void loadTradeBudget(prevDone ? today : day);
        }
      } catch {
        if (alive.current && my === reqId.current) {
          setErr("读取历史复盘失败，仍可尝试重新生成");
          void loadDates();
        }
      }
    }
    bootstrap();
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, []);

  function stopPolling() {
    polling.current = false;
    if (alive.current) setRunning(false);
  }

  // 选中日是否已有复盘：历史列表命中，或当前展示正是该日且非 missing
  const reviewExists = Boolean(date) && (
    dates.includes(date)
    || (!missing && Boolean(data) && (data?.target_date || data?.trade_date) === date)
  );

  async function pollOnce() {
    if (!alive.current) return;
    try {
      const st = await agentFetch<JobStatus>("/api/review/status");
      if (!alive.current) return;
      setElapsed(st.elapsed || 0);
      if (st.running) { timer.current = setTimeout(pollOnce, 3000); return; }
      stopPolling();
      if (st.error) setErr(st.error);
      else { loadLatest(date || undefined); void loadDates(); }
    } catch { stopPolling(); if (alive.current) setErr("状态查询失败"); }
  }

  async function generate() {
    if (running || polling.current) return;
    polling.current = true;
    setRunning(true); setErr(""); setNotice(""); setElapsed(0);
    // 这里不用 agentFetch：它只抛 `HTTP 4xx`，会把「已复盘」「还没收盘」
    // 这些**需要原样告诉用户**的信息丢掉。
    // 选中日已有复盘时带 force=1，否则后端会直接 already_done 不重跑。
    const qs = new URLSearchParams();
    if (date) qs.set("date", date);
    if (reviewExists) qs.set("force", "1");
    const q = qs.toString();
    let resp: Response;
    try {
      resp = await fetch(apiUrl(`/api/review/run${q ? `?${q}` : ""}`), { method: "POST" });
    } catch { stopPolling(); if (alive.current) setErr("启动失败"); return; }
    const body = await resp.json().catch(() => null);
    if (!alive.current) return;
    if (resp.status === 409) {
      // 目标日还没收盘 —— 复盘只能用收盘数据，指回最近那一场
      stopPolling();
      const s = body?.suggest_date;
      setNotice(body?.error || "这一天还没收盘");
      if (s) { setDate(s); loadLatest(s); }
      return;
    }
    if (!resp.ok) { stopPolling(); setErr(body?.error || "启动失败"); return; }
    if (body?.already_done) {
      stopPolling();
      setNotice(`${body.date} 已复盘，下面就是那天的结果`);
      setDate(body.date); loadLatest(body.date); void loadDates();
      return;
    }
    pollOnce();
  }

  const focus = data?.focus;
  // 页面按"用户复盘的顺序"重排后，各卡片散在不同区块里，这里统一取一次
  const facts = data?.market_facts;
  const em = splitMetrics(data?.emotion_metrics);
  const breadth = facts?.breadth;
  const marketTot = marketTotal(
    breadth?.universe,
    breadth?.up,
    breadth?.down,
    breadth?.flat,
  );
  // 下部快捷日期：选中日（含推进后的今天）置顶，高亮跟日历 date 走，不跟已展示那份复盘走
  const chipDates = (date
    ? [date, ...dates.filter((d) => d !== date)]
    : dates
  ).slice(0, 5);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Swords className="h-6 w-6 text-primary" /> 短线复盘看板
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            情绪温度 · 上期验证 · 明日验证条件
            {data && ` · 交易日 ${data.target_date || data.trade_date} · 生成于 ${data.generated_at}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex flex-col items-start">
            <input type="date" value={date} list="review-dates"
              onChange={(e) => { const v = e.target.value; setDate(v); setErr(""); if (v) loadLatest(v); }}
              className="rounded-lg border border-border bg-card px-3 py-2 text-sm" />
            {/* 跑过的日子直接列出来 —— 不然用户只能靠猜哪天有存档 */}
            <datalist id="review-dates">
              {dates.map((d) => <option key={d} value={d} />)}
            </datalist>
            {chipDates.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
                {chipDates.map((d) => (
                  <button key={d} onClick={() => { setDate(d); setErr(""); loadLatest(d); }}
                    className={`rounded px-1.5 py-0.5 transition-colors hover:text-primary ${
                      date === d ? "bg-primary/15 text-primary" : "bg-muted/40"
                    }`}>{d.slice(5)}</button>
                ))}
              </div>
            )}
          </div>
          <button onClick={generate} disabled={running}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50">
            {running && <Loader2 className="h-4 w-4 animate-spin" />}
            {running ? `复盘中 ${elapsed}s` : reviewExists ? "重新复盘" : "生成复盘"}
          </button>
        </div>
      </div>

      {err && <div className="glass rounded-xl border-danger/30 px-4 py-3 text-sm text-danger">出错：{err}</div>}
      {notice && <div className="glass rounded-xl border-primary/30 px-4 py-3 text-sm text-muted-foreground">{notice}</div>}
      {data?.warnings?.length ? (
        <div className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-2.5 text-[13px] text-warning">
          ⚠ 部分数据降级：{data.warnings.join("；")}
        </div>
      ) : null}

      {!data && !running && (
        <div className="glass rounded-2xl py-16 text-center text-muted-foreground">
          {missing
            ? <>{missing} 这天还没跑过复盘。<div className="mt-1 text-xs">点「生成复盘」补跑，或换一个日期</div></>
            : <>还没有复盘。选个交易日，点「生成复盘」。<div className="mt-1 text-xs">多 agent 全链约 3 分钟</div></>}
        </div>
      )}

      {}

      {/* ① 今天好不好做 */}
      {}
      <BreadthPanel b={facts?.breadth} limitDown={facts?.loss_effect?.market_limit_down} />
      <TradeBudgetCard
        b={tradeBudget}
        date={data?.target_date || data?.trade_date || date}
      />

      {/* ② 昨天进去的人今天赚不赚钱 —— 用户说这是全页最有用的一块，所以提到第二位 */}
      <section className="space-y-4">
        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
          昨天进去的人赚不赚钱 · Feedback
        </div>
        <Matrix fm={facts?.feedback_matrix} />
        <div className="grid gap-4 md:grid-cols-2">
          <MoneyEffectCard me={em.me} />
          <LossEffectSection le={facts?.loss_effect} />
        </div>
      </section>

      {/* ③ 接力生态 —— 原来散在四处的四张卡合成一块 */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">接力生态 · Ladder</span>
          {em.prevDate && em.zt != null && em.ztPrev != null && (
            <span className="text-[11px] text-muted-foreground">
              对照 {em.prevDate} · 涨停家数 {fmtCountPermille(em.ztPrev, marketTot)} →{" "}
              <b className="tabular-nums text-foreground">{fmtCountPermille(em.zt, marketTot)}</b>
            </span>
          )}
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <PromotionCard pr={em.pr} />
          <LadderCard lg={em.lg} marketTotal={marketTot} />
          <ConsecPremiumCard cp={em.cp} />
        </div>
        <SealQualitySection sq={facts?.seal_quality} />
      </section>

      {/* ④ 钱往哪去 —— 题材事件树（明细）+ 题材结构（汇总）合并成一块，
          用户说这两块"在讲相近的事"，分开看要来回找 */}
      <section className="space-y-4">
        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">钱往哪去 · Themes</div>
        <ThemeTreeView t={facts?.theme_tree} />
        <Themes ts={facts?.theme_structure} />
      </section>

      {/* ⑤ 今天风险在哪 —— 事件账本按方向拆开，亏钱那堆在前 */}
      <section className="space-y-4">
        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">今天风险在哪 · Risk</div>
        <Ledger el={facts?.event_ledger} />
        <BoardSystemSection bb={facts?.by_board} />
      </section>

      {/* ⑥ 跟前几天比在什么位置 */}
      <section className="space-y-4">
        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">跟前几天比 · Trend</div>
        <TrendPanel t={facts?.trend} />
        <div className="grid gap-4 lg:grid-cols-2">
          <StatsView c={facts?.stats_context} />
          <DiffView d={facts?.day_diff} />
        </div>
        <CycleCard cy={em.cy} />
      </section>

      {/* AI 研判（放在事实之后）*/}
      {focus && (
        <section>
          <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.2em] text-primary">明天关注点 · Tomorrow</div>
          <div className="glass rounded-2xl p-6 shadow-glow">
            <div className="mb-3 flex flex-wrap items-center gap-4">
              <span className={cn("rounded-full px-4 py-1.5 text-sm font-bold tracking-wider", phaseTone(focus.emotion_phase))}>
                {focus.emotion_phase}
              </span>
              <span className="flex-1 text-lg font-semibold">{focus.market_oneliner}</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {safeArray<FocusDirection>(focus.focus_directions).map((d, i) => (
                <div key={i} className="rounded-xl border border-border border-l-4 border-l-primary bg-card/50 p-4">
                  <h3 className="mb-1.5 text-base font-bold">{d.direction}</h3>
                  <p className="mb-3 text-sm text-muted-foreground">{d.logic}</p>
                  {safeArray<string>(d.leader_candidates).length > 0 && (
                    <div className="mb-2.5 flex flex-wrap gap-1.5">
                      {safeArray<string>(d.leader_candidates).map((l, j) => (
                        <span key={j} className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">{l}</span>
                      ))}
                    </div>
                  )}
                  <div className="border-t border-dashed border-border pt-2 text-xs text-muted-foreground">
                    <span className="font-semibold text-danger">风险</span> {d.risk}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <div className="border-t-2 border-foreground pt-2.5">
                <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-bold"><AlertTriangle className="h-4 w-4 text-warning" /> 风险提示</h4>
                <ul className="ml-4 list-disc space-y-1 text-[13px] text-muted-foreground">
                  {safeArray<string>(focus.risk_alerts).map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            </div>

            <VerificationResults reflection={data?.reflection} />

            {safeArray<VerificationItem>(focus.verification_items).length > 0 && (
              <div className="mt-5 border-t-2 border-foreground pt-2.5">
                <h4 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
                  <CheckSquare className="h-4 w-4 text-info" /> 明日验证条件
                  <span className="text-[11px] font-normal text-muted-foreground">
                    明天用这几个读数检验今晚的判断；结果会出现在下一场复盘的「上期验证结果」里
                  </span>
                </h4>
                <div className="flex flex-wrap gap-2">
                  {safeArray<VerificationItem>(focus.verification_items).map((v, i) => (
                    <div key={i} className="flex-1 basis-[240px] rounded-lg border border-border bg-muted/20 px-3 py-2">
                      <div className="text-[13px] font-semibold">
                        {v.label || METRIC_LABEL[v.metric] || v.metric}
                        {}
                        <span className={cn("ml-1.5 rounded px-1.5 py-0.5 text-[11px] font-bold",
                          v.direction === "上升" ? "bg-danger/15 text-danger"
                            : v.direction === "下降" ? "bg-success/15 text-success"
                            : "bg-muted text-muted-foreground")}>预期{v.direction}</span>
                      </div>
                      {/* 今日基准 + 阈值：只写"预期下降"的话，明天从多少降到多少才算降？
                          没有这两个数，第二天只能凭感觉，而凭感觉怎么变都能自圆其说。 */}
                      {finite(v.base_value) != null && (
                        <div className="mt-1 text-[11px] tabular-nums text-foreground/70">
                          今日 <b className="text-foreground">{statText(v)}</b>
                          {epsText(v) && <> · 明天变动超过 {epsText(v)} 才算数</>}
                        </div>
                      )}
                      <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{v.reason}</div>
                    </div>
                  ))}
                </div>
                <UserConditions date={data?.target_date || data?.trade_date || ""} />
              </div>
            )}
          </div>
        </section>
      )}

      {}

      {data && (
        <AgentChat
          // 换交易日即重建组件，避免旧对话串到新复盘
          key={data.target_date || data.trade_date}
          endpoint="/api/review/chat"
          placeholder="就今天的复盘追问，如：展开电网设备的接力逻辑"
          suggestions={["最强主线今天的梯队结构是怎样的", "当前情绪处在周期哪个阶段", "各方向的龙头晋级还是断板了", "判断退潮要盯哪些数据信号"]}
        />
      )}

      {data && <p className="border-t border-border pt-4 text-xs text-muted-foreground/70"><Target className="mr-1 inline h-3 w-3" /> {DISCLAIMER}</p>}
    </div>
  );
}
