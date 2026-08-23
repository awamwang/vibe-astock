import { useEffect, useState } from "react";
import { CalendarRange, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Caliber } from "@/components/ui/Caliber";
import { ThemeMatrixChart } from "@/components/charts/ThemeMatrixChart";
import { agentFetch, finite, pct, safeArray, type WeeklyData, type LineageLeader } from "@/lib/agent";
import { pctColor, UP_TEXT } from "@/lib/colors";
import { StockLabel } from "@/components/stock/StockLabel";

const WINDOW_MIN = 7;
const WINDOW_MAX = 15;
const WINDOW_DEFAULT = 10;

function Sparkline({ leader }: { leader: LineageLeader }) {
  const s = leader.series;
  if (!s || s.length < 2) {
    return <div className="mt-1 text-[13px] text-muted-foreground">
      {s && s.length === 1 ? "（当日登顶，暂无后续交易日）" : "（无后续行情，可能已退市/停牌）"}
    </div>;
  }
  const vals = s.map((x) => finite(x.cum_ret)).filter((v): v is number => v !== null);
  if (vals.length < 2) return <div className="text-[11px] text-muted-foreground/60">（有效点不足，无法绘制）</div>;
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals), rng = (max - min) || 1;
  const W = 200, H = 34, n = vals.length;
  const pts = vals.map((v, i) => `${(i / (n - 1) * W).toFixed(1)},${(H - (v - min) / rng * H).toFixed(1)}`).join(" ");
  const last = vals[vals.length - 1];
  const col = last >= 0 ? "hsl(var(--danger))" : "hsl(var(--success))";
  const zeroY = (H - (0 - min) / rng * H).toFixed(1);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="200" height="34" className="mt-1.5">
      <line x1="0" x2={W} y1={zeroY} y2={zeroY} stroke="hsl(var(--border))" strokeDasharray="2,2" />
      <polyline points={pts} fill="none" stroke={col} strokeWidth="2" />
    </svg>
  );
}

export function AgentWeekly() {
  const [data, setData] = useState<WeeklyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [windowDays, setWindowDays] = useState(WINDOW_DEFAULT);

  async function load(refresh: boolean) {
    setLoading(true); setErr("");
    const q = `?days=${windowDays}`;
    try {
      setData(refresh
        ? await agentFetch<WeeklyData>(`/api/weekly/refresh${q}`, "POST")
        : await agentFetch<WeeklyData>(`/api/weekly${q}`));
    }
    catch (e) { setErr(e instanceof Error ? e.message : "加载失败"); }
    setLoading(false);
  }
  useEffect(() => { load(false); }, [windowDays]);

  const maxLu = Math.max(1, ...(data?.days || []).map((d) => d.limit_up || 0));
  const activeDays = data?.window_days ?? windowDays;

  return (
    <div className="space-y-6 w-full min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <CalendarRange className="h-6 w-6 text-primary" /> 多日情绪
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            多日题材涨停矩阵 + 情绪趋势 + 龙头谱系
            {data?.generated_at && ` · 生成于 ${data.generated_at}`}
            {data?.stale && " · ⚠ 展示上一份有效数据"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>窗口</span>
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              className="rounded-lg border border-border bg-background px-2 py-1.5 text-sm font-medium text-foreground"
            >
              {Array.from({ length: WINDOW_MAX - WINDOW_MIN + 1 }, (_, i) => WINDOW_MIN + i).map((n) => (
                <option key={n} value={n}>{n} 个交易日</option>
              ))}
            </select>
          </label>
          <button onClick={() => load(true)} disabled={loading}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50">
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}{loading ? "计算中…" : "刷新"}
          </button>
        </div>
      </div>

      {err && <div className="glass rounded-xl px-4 py-3 text-sm text-danger">加载失败：{err}</div>}
      {loading && !data && (
        <div className="glass rounded-2xl py-16 text-center text-muted-foreground">
          <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />加载多日情绪…
        </div>
      )}

      {data && !data.error && (
        <>
          <section className="w-full min-w-0">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
                多日题材涨停 · Theme Matrix
              </span>
              <Caliber text={
                "**优先读复盘落盘** `reviews/{date}.json` 里的 `market_facts.theme_tree`（与复盘看板同一快照）；\n" +
                "该日没有复盘或树不可用时，才用题材串缓存现场重算。\n" +
                "左侧 3 日 / 窗口排名 = 各题材在对应天数内的涨停家数累计（有几天算几天）。\n" +
                "热力图颜色深浅 = 当日该题材涨停数；悬停可看阶段、最高连板、跌停数。"
              } />
            </div>
            <div className="glass w-full min-w-0 rounded-2xl p-4">
              <ThemeMatrixChart
                matrix={data.theme_matrix}
                windowDays={activeDays}
                fallbackDates={safeArray(data.days).map((d) => d.date).filter(Boolean)}
              />
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
                情绪趋势 · Sentiment
              </span>
              <Caliber text={
                `「${activeDays} 天」= 最近 ${activeDays} 个**交易日**，周末与休市不算。\n` +
                "涨停家数 = 当日最终封住涨停的家数；最高板 = 当日连板数最高那只的连板数。\n" +
                "炸板率 = 炸板家数 ÷（炸板 + 涨停），与其它几处同一个算法；\n" +
                "某天炸板池取数失败时那天留空，**不会当成 0**。\n" +
                "当日龙头 = 当日涨停池里连板数最高的那只；并列最高时取列表中的第一只，\n" +
                "不看成交额也不看封单 —— 所以它不等于市场公认的那只龙头。"
              } />
            </div>
            <div className="glass overflow-hidden rounded-2xl">
              <div className="grid grid-cols-[100px_1fr_56px_56px_56px_1.2fr] items-center gap-2 bg-muted/40 px-4 py-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground lg:px-5 lg:gap-3">
                <span>日期</span><span>涨停家数</span><span>最高板</span><span>炸板率</span><span>跌停</span><span>当日龙头</span>
              </div>
              {safeArray<WeeklyData["days"][number]>(data.days).map((d) => (
                <div key={d.date} className="grid grid-cols-[100px_1fr_56px_56px_56px_1.2fr] items-center gap-2 border-t border-border/60 px-4 py-3 text-sm lg:px-5 lg:gap-3">
                  <span className="text-muted-foreground tabular-nums">{d.date}</span>
                  <span>
                    <span className="flex h-5 items-center rounded bg-gradient-to-r from-primary/70 to-primary px-2 text-xs font-semibold text-primary-foreground"
                      style={{ width: `${Math.max(6, (d.limit_up || 0) / maxLu * 100)}%` }}>{d.limit_up ?? "—"}</span>
                  </span>
                  <span className="text-center font-extrabold text-primary">{d.highest_consec ?? "—"}板</span>
                  <span className="text-center tabular-nums">{d.broken_rate != null ? Math.round(d.broken_rate * 100) + "%" : "—"}</span>
                  <span className="text-center tabular-nums text-success">{d.limit_down ?? "—"}</span>
                  <span className="text-[13px]">{d.leader ? `${d.leader.name} ${d.leader.boards}板 · ${d.leader.sector || ""}` : "—"}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">龙头谱系 · Lineage</span>
              <Caliber text={
                "这里的大号百分比**不是当日跌幅**，是「距登顶后最高点的回撤」：\n" +
                "以登顶那天的收盘价为基准算每天累计涨跌，取这段里最高的那个当高点，再看现在距它跌了多少。\n" +
                "全部用收盘价，不看盘中最高最低；就在最高点时显示「在最高点」。\n" +
                "「登顶」= 那天它是全市场连板数最高的那只（同上，并列时按列表顺序取）；\n" +
                "一只票多次当过龙头只算**最早**那一天。「区间」= 登顶日到最近一个交易日。\n" +
                "「自登顶累计」= 登顶日收盘 → 最近交易日收盘；「最高到过」= 这段里累计涨跌的最高值。"
              } />
            </div>
            <h2 className="mb-3 text-lg font-bold">前几天的龙头 · 现在怎么样了</h2>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {safeArray<LineageLeader>(data.leader_lineage).map((l) => {
                const dd = finite(l.drawdown_from_peak);
                const atPeak = dd === 0;
                return (
                  <div key={l.code} className={cn("glass rounded-2xl border-l-4 p-4",
                    dd == null ? "border-l-border" : atPeak ? "border-l-danger" : "border-l-success")}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="flex items-baseline gap-1.5 text-[15px] font-bold">
                        <StockLabel
                          code={l.code}
                          name={l.name}
                          codeClassName="text-xs font-normal text-muted-foreground"
                        />
                        {l.is_current_top && (
                          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-bold text-primary">
                            当前最高标
                          </span>
                        )}
                      </span>
                      <span className={cn("text-xl font-extrabold",
                        dd == null ? "text-muted-foreground" : atPeak ? UP_TEXT : pctColor(dd))}>
                        {dd == null ? "—" : atPeak ? "在最高点" : pct(dd)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {l.appear_date} 登顶 · {l.sector || ""} · 距区间最高点（收盘价口径）
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground/70">
                      自登顶累计 {pct(l.cum_return_since)}
                      {finite(l.peak_cum_ret) != null && ` · 最高到过 ${pct(l.peak_cum_ret)}`}
                    </div>
                    <Sparkline leader={l} />
                  </div>
                );
              })}
            </div>
          </section>

          <p className="border-t border-border pt-4 text-xs text-muted-foreground/70">
            ⚠️ 本页由盘面公开数据（涨停池/行情）梳理生成，仅供参考，不构成投资建议；市场有风险，决策与盈亏自负。
          </p>
        </>
      )}
      {data?.error && <div className="glass rounded-2xl py-16 text-center text-muted-foreground">取数失败：{data.error}</div>}
    </div>
  );
}
