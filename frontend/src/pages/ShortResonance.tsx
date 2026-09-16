import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { Loader2, RefreshCw, RotateCcw, Waves } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { TradeDatePicker } from "@/components/TradeDatePicker";
import { localDate } from "@/lib/agent";
import { cn } from "@/lib/utils";
import { pctColor } from "@/lib/colors";
import {
  fetchBoardEmotionResonance,
  formatLayerValue,
  formatResonanceScore,
  resonanceLabelClass,
  trialBoardEmotionResonance,
  type BoardEmotionLayer,
  type BoardEmotionResonanceSnapshot,
  type BoardEmotionScore,
} from "@/lib/boardEmotionResonance";

const CALIBER =
  "打板情绪共振：同一场次六层（最高连板、晋级率、炸板率、涨停相对跌停、赚钱效应均、深亏占比）相对十日基线的差，按该层自身波动压到 [-1, 1]，再按层权重合成为连续分数。\n" +
  "十日基线是近十个已定稿场次、不含本场的算术平均。缺位不补 0、不补均值；该层有效对照不足 5 天则该层不进合成。\n" +
  "炸板率与深亏占比越高，系数越负。封板率不另占一票。\n" +
  "有效层不足四层则整场为「不足」、不出分。弱标签：|分|≥0.25 偏多/偏空，否则混杂。\n" +
  "改基线只移动零点，不改该层对照窗波动；权重 0 的层不参加合成。试算不写归档，刷新或恢复默认回到等权 100。\n" +
  "东财四池混算 10cm / 20cm / 北交所 / ST，家数同向不是同一制度内的同向。";

function parseNum(raw: string): number | undefined {
  const t = raw.trim();
  if (!t) return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}

function toInputValue(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "";
  return String(Number(v.toFixed(6)));
}

function ScoreBlock({
  title, score, label, reason, marked,
}: {
  title: string;
  score: number | null;
  label: string;
  reason?: string | null;
  marked?: boolean;
}) {
  return (
    <div className={cn("rounded-xl border px-4 py-3", marked ? "border-warning/50 bg-warning/10" : "border-border/50 bg-card/60")}>
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        {title}
        {marked && (
          <span className="rounded bg-warning/20 px-1.5 py-0.5 text-[10px] font-semibold text-warning">试算</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-3">
        <span className={cn("text-3xl font-extrabold tabular-nums", pctColor(score))}>
          {formatResonanceScore(score)}
        </span>
        <span className={cn("text-base font-semibold", resonanceLabelClass(label))}>{label}</span>
      </div>
      {reason && <p className="mt-1 text-[11px] text-muted-foreground">{reason}</p>}
    </div>
  );
}

function layerInputStep(unit: string): string {
  if (unit === "板" || unit === "count") return "1";
  return "0.001";
}

export function ShortResonance() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const date = params.get("date") || "";
  const [snap, setSnap] = useState<BoardEmotionResonanceSnapshot | null>(null);
  const [trialSnap, setTrialSnap] = useState<BoardEmotionResonanceSnapshot | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [trialBusy, setTrialBusy] = useState(false);
  const [baselineEdits, setBaselineEdits] = useState<Record<string, string>>({});
  const [weightEdits, setWeightEdits] = useState<Record<string, string>>({});

  const dirty = Object.keys(baselineEdits).length > 0 || Object.keys(weightEdits).length > 0;

  const clearEdits = () => {
    setBaselineEdits({});
    setWeightEdits({});
    setTrialSnap(null);
  };

  const load = useCallback(async (d?: string, keepEdits = false) => {
    setBusy(true);
    setErr("");
    if (!keepEdits) {
      setBaselineEdits({});
      setWeightEdits({});
      setTrialSnap(null);
    }
    try {
      const out = await fetchBoardEmotionResonance(d || undefined);
      setSnap(out);
      if (out.date && out.date !== d) {
        setParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set("date", out.date);
          return next;
        }, { replace: true });
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, [setParams]);

  useEffect(() => {
    void load(date || undefined);
    // 首屏按 URL 场次拉一次；换场由选择器显式触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!snap) return;
    if (location.hash !== "#board-emotion") return;
    document.getElementById("board-emotion")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [snap, location.hash]);

  const overrides = useMemo(() => {
    const baselines: Record<string, number> = {};
    const weights: Record<string, number> = {};
    for (const [k, raw] of Object.entries(baselineEdits)) {
      const n = parseNum(raw);
      if (n !== undefined) baselines[k] = n;
    }
    for (const [k, raw] of Object.entries(weightEdits)) {
      const n = parseNum(raw);
      if (n !== undefined) weights[k] = n;
    }
    return { baselines, weights };
  }, [baselineEdits, weightEdits]);

  useEffect(() => {
    if (!dirty || !snap) {
      setTrialSnap(null);
      setTrialBusy(false);
      return;
    }
    const hasOverride =
      Object.keys(overrides.baselines).length > 0 || Object.keys(overrides.weights).length > 0;
    if (!hasOverride) {
      setTrialSnap(null);
      setTrialBusy(false);
      return;
    }
    let cancelled = false;
    const t = window.setTimeout(() => {
      setTrialBusy(true);
      void trialBoardEmotionResonance({
        date: snap.date,
        ...(Object.keys(overrides.baselines).length ? { baselines: overrides.baselines } : {}),
        ...(Object.keys(overrides.weights).length ? { weights: overrides.weights } : {}),
      })
        .then((out) => { if (!cancelled) setTrialSnap(out); })
        .catch((e) => { if (!cancelled) setErr(e instanceof Error ? e.message : "试算失败"); })
        .finally(() => { if (!cancelled) setTrialBusy(false); });
    }, 280);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [dirty, snap, overrides]);

  const selectDate = (iso: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("date", iso);
      return next;
    }, { replace: true });
    void load(iso);
  };

  const def: BoardEmotionScore | undefined = snap?.default;
  const trial: BoardEmotionScore | null | undefined = trialSnap?.trial;
  const layers: BoardEmotionLayer[] = def?.layers ?? [];

  return (
    <div>
      <PageHeader
        title="短线共振"
        subtitle="同一场次多层同向。本期只有打板情绪共振一块；不接情绪周期，不定仓位天花板。"
        actions={
          <div className="flex items-center gap-2">
            <TradeDatePicker
              value={date || snap?.date || ""}
              maxDate={localDate()}
              onChange={selectDate}
            />
            <button
              type="button"
              onClick={() => void load(date || snap?.date, false)}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-primary"
              title="刷新并丢掉试算"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              刷新
            </button>
          </div>
        }
      />

      {err && (
        <div className="mb-4 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{err}</div>
      )}

      <section id="board-emotion" className="scroll-mt-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
            <Waves className="h-4 w-4" /> 打板情绪共振
            <Caliber text={CALIBER} />
          </h2>
          <span className="text-[11px] text-muted-foreground/60">
            {snap?.date}
            {snap?.is_live ? " · 随盘" : snap ? " · 定稿" : ""}
            {snap?.phase ? ` · ${snap.phase}` : ""}
            {trialBusy && " · 试算中"}
          </span>
          {dirty && (
            <button
              type="button"
              onClick={clearEdits}
              className="ml-auto inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-[12px] text-muted-foreground hover:text-primary"
            >
              <RotateCcw className="h-3 w-3" /> 恢复默认
            </button>
          )}
        </div>

        <GlassCard className="mb-4 !p-4">
          {!snap && busy ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />加载打板情绪共振…
            </p>
          ) : !snap ? (
            <p className="py-8 text-center text-sm text-muted-foreground">暂无打板情绪共振</p>
          ) : (
            <>
              <div className="mb-4 grid gap-3 sm:grid-cols-2">
                <ScoreBlock
                  title="默认分（等权 100 · 未改基线）"
                  score={def?.score ?? null}
                  label={def?.label ?? "不足"}
                  reason={def?.reason}
                />
                {trial && (
                  <ScoreBlock
                    title="试算分"
                    score={trial.score}
                    label={trial.label}
                    reason={trial.reason}
                    marked
                  />
                )}
              </div>
              <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground">
                {snap.note}
                {snap.window_dates?.length ? (
                  <> 对照窗 {snap.window_dates[0]} … {snap.window_dates[snap.window_dates.length - 1]}（不含本场）。</>
                ) : null}
                {" "}默认有效 {def?.active_layers ?? 0}/6 层
                {trial ? ` · 试算有效 ${trial.active_layers}/6 层` : ""}。
                <Link to="/short-board" className="ml-2 text-primary/80 hover:text-primary">短线盘面只读默认分 →</Link>
              </p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[56rem] text-left text-[12px]">
                  <thead className="text-[11px] text-muted-foreground">
                    <tr>
                      <th className="py-1.5 pr-2">层</th>
                      <th className="pr-2">当场值</th>
                      <th className="pr-2">十日基线</th>
                      <th className="pr-2">差值</th>
                      <th className="pr-2">波动 σ</th>
                      <th className="pr-2">系数</th>
                      <th className="pr-2">权重</th>
                      <th className="pr-2">缺失</th>
                    </tr>
                  </thead>
                  <tbody>
                    {layers.map((ly) => {
                      const trialLayer = trial?.layers.find((x) => x.key === ly.key);
                      const shown = trialLayer ?? ly;
                      return (
                        <tr key={ly.key} className={cn("border-t border-border/40", !shown.included && "opacity-70")}>
                          <td className="py-2 pr-2">
                            <div className="font-medium text-foreground">{ly.label}</div>
                            {ly.invert && <div className="text-[10px] text-muted-foreground/70">越高越负</div>}
                          </td>
                          <td className="pr-2 font-mono tabular-nums">{formatLayerValue(ly.unit, ly.value)}</td>
                          <td className="pr-2">
                            <input
                              type="number"
                              step={layerInputStep(ly.unit)}
                              value={baselineEdits[ly.key] ?? toInputValue(ly.baseline_default)}
                              onChange={(e) => {
                                const v = e.target.value;
                                setBaselineEdits((prev) => {
                                  const next = { ...prev };
                                  if (v === toInputValue(ly.baseline_default)) delete next[ly.key];
                                  else next[ly.key] = v;
                                  return next;
                                });
                              }}
                              className="w-[6.5rem] rounded border border-border bg-background px-1.5 py-1 font-mono text-[12px] tabular-nums"
                              aria-label={`${ly.label}十日基线`}
                            />
                            <div className="mt-0.5 text-[10px] text-muted-foreground">
                              默认 {formatLayerValue(ly.unit, ly.baseline_default)}
                              {shown.baseline_overridden ? " · 已改" : ""}
                            </div>
                          </td>
                          <td className={cn("pr-2 font-mono tabular-nums", pctColor(shown.diff))}>
                            {formatLayerValue(ly.unit, shown.diff)}
                          </td>
                          <td className="pr-2 font-mono tabular-nums">{formatLayerValue(ly.unit, shown.sigma, 4)}</td>
                          <td className={cn("pr-2 font-mono tabular-nums", pctColor(shown.coefficient))}>
                            {shown.coefficient == null ? "—" : shown.coefficient.toFixed(3)}
                          </td>
                          <td className="pr-2">
                            <input
                              type="number"
                              step="1"
                              min="0"
                              value={weightEdits[ly.key] ?? toInputValue(ly.weight_default)}
                              onChange={(e) => {
                                const v = e.target.value;
                                setWeightEdits((prev) => {
                                  const next = { ...prev };
                                  if (v === toInputValue(ly.weight_default)) delete next[ly.key];
                                  else next[ly.key] = v;
                                  return next;
                                });
                              }}
                              className="w-16 rounded border border-border bg-background px-1.5 py-1 font-mono text-[12px] tabular-nums"
                              aria-label={`${ly.label}层权重`}
                            />
                          </td>
                          <td className="pr-2 text-[11px] leading-snug text-muted-foreground">
                            {shown.missing_reasons.length
                              ? shown.missing_reasons.join("；")
                              : (shown.included ? "计入" : "—")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </GlassCard>
      </section>

      <Disclaimer />
    </div>
  );
}
