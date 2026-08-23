import { useMemo } from "react";
import type { EChartsOption, LineSeriesOption, BarSeriesOption } from "echarts";
import { useEChart } from "@/hooks/useEChart";
import { cssVarHsl } from "@/lib/colors";
import { fmtCountPct, fmtCountPermille } from "@/lib/marketRatio";
import {
  finite, safeArray,
  type WeeklyMetricChart, type WeeklyMetricCharts, type WeeklyMetricSeries,
} from "@/lib/agent";

/** 各指标固定线条色：正面暖色，负面冷绿。key 与后端 series.key 对齐。 */
const METRIC_LINE_COLOR: Record<string, string> = {
  // 暖色 · 正面 / 偏多
  temperature: "--danger",
  qcj_temp: "--warning",
  activity_pct: "--primary",
  up: "--danger",
  deep_up_5: "--warning",
  limit_up: "--danger",
  lianban_count: "--warning",
  highest_board: "hsl(18 88% 56%)",
  never_broken_rate: "--warning",
  promotion_rate: "--danger",
  open_success_rate: "--warning",
  close_success_rate: "--danger",
  zt_premium_pct: "--primary",
  money_effect_median: "--danger",
  consec_premium_median: "--warning",
  amount_yi: "--warning",
  m_net_yi: "--primary",
  qcj_level_ord: "--warning",
  speculation_ord: "--danger",
  // 冷色 · 负面 / 偏空
  down: "--success",
  deep_down_5: "hsl(158 42% 40%)",
  limit_down: "--success",
  broken_rate: "--success",
  loss_effect_rate: "hsl(172 38% 36%)",
};

function resolveSeriesColor(key: string): string {
  const token = METRIC_LINE_COLOR[key];
  if (!token) return cssVarHsl("--muted-foreground");
  if (token.startsWith("hsl")) return token;
  return cssVarHsl(token);
}

function shortDate(d: string) {
  const p = d.split("-");
  return p.length === 3 ? `${p[1]}/${p[2]}` : d;
}

function plotScale(s: WeeklyMetricSeries): number {
  const sc = s.plot_scale;
  return sc != null && sc > 0 ? sc : 1;
}

function toPlotValue(v: number, s: WeeklyMetricSeries): number {
  if (s.kind === "rate") return Math.round(v * 1000) / 10;
  return Math.round(v * plotScale(s) * 1000) / 1000;
}

function fmtPlotValue(v: number | null, kind?: string): string {
  if (v == null) return "—";
  if (kind === "rate") return `${Math.round(v * 1000) / 10}%`;
  if (kind === "pct") return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
  if (kind === "permille") return `${v.toFixed(2)}‰`;
  if (kind === "count_pct") return `${v.toFixed(2)}%`;
  if (kind === "yi") return `${v.toFixed(v % 1 === 0 ? 0 : 2)}亿`;
  if (kind === "board") return `${Math.round(v)}板`;
  if (kind === "ordinal") return String(v);
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function fmtTooltipValue(meta: WeeklyMetricSeries, idx: number): string {
  const kind = meta.kind;
  const raw = finite(safeArray<number | null>(meta.values)[idx]);
  if (raw == null && kind !== "ordinal") return "—";

  if (kind === "permille" || kind === "count_pct") {
    const count = finite(safeArray<number | null>(meta.counts)[idx]);
    const total = finite(safeArray<number | null>(meta.totals)[idx]);
    if (count != null) {
      return kind === "permille" ? fmtCountPermille(count, total) : fmtCountPct(count, total);
    }
  }

  if (kind === "ordinal") {
    const label = meta.labels?.[idx];
    return label ? `${label}（${fmtPlotValue(raw, kind)}）` : fmtPlotValue(raw, kind);
  }

  return fmtPlotValue(raw, kind);
}

function yAxisDefs(chart: WeeklyMetricChart) {
  const raw = chart.y_axis;
  if (Array.isArray(raw)) return raw;
  return raw ? [raw] : [{ kind: "count" }];
}

function buildOption(chart: WeeklyMetricChart, days: string[]): EChartsOption | null {
  const seriesList = safeArray<WeeklyMetricSeries>(chart.series);
  if (!days.length || !seriesList.length) return null;

  const isLine = chart.chart_type === "line";
  const axes = yAxisDefs(chart);

  const eSeries: (LineSeriesOption | BarSeriesOption)[] = seriesList.map((s) => {
    const color = resolveSeriesColor(s.key);
    const vals = safeArray<number | null>(s.values).map((v) => finite(v));
    const data = vals.map((v) => (v == null ? null : toPlotValue(v, s)));
    const base = {
      name: s.label,
      connectNulls: false,
      yAxisIndex: s.y_axis_index ?? 0,
      itemStyle: { color },
      data,
    };
    if (isLine) {
      return {
        ...base,
        type: "line" as const,
        smooth: true,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { width: 2, color },
      };
    }
    return {
      ...base,
      type: "bar" as const,
      barMaxWidth: 14,
    };
  });

  const yAxisLabel = (kind?: string) => (v: number) => {
    if (kind === "rate" || kind === "count_pct" || kind === "pct") return `${v}%`;
    if (kind === "permille") return `${v}‰`;
    if (kind === "yi") return `${v}亿`;
    if (kind === "board") return `${v}板`;
    return String(v);
  };

  return {
    animation: false,
    grid: { left: 52, right: axes.length > 1 ? 48 : 16, top: 36, bottom: 28 },
    legend: {
      type: "scroll",
      top: 0,
      textStyle: { color: cssVarHsl("--muted-foreground"), fontSize: 11 },
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: cssVarHsl("--popover", 0.96),
      borderColor: cssVarHsl("--border"),
      textStyle: { color: cssVarHsl("--popover-foreground"), fontSize: 12 },
      axisPointer: { type: isLine ? "line" : "shadow" },
      formatter(params: unknown) {
        const items = safeArray<{ dataIndex?: number; seriesName?: string; seriesIndex?: number }>(params);
        if (!items.length) return "";
        const idx = items[0].dataIndex;
        if (idx == null || idx < 0 || idx >= days.length) return "";
        const fullDay = days[idx];
        const lines = [`<b>${fullDay}</b>`];
        items.forEach((p) => {
          const si = p.seriesIndex ?? 0;
          const meta = seriesList[si];
          if (!meta) return;
          lines.push(`${p.seriesName ?? meta.label}：${fmtTooltipValue(meta, idx)}`);
        });
        return lines.join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: days.map(shortDate),
      axisLabel: { color: cssVarHsl("--muted-foreground"), fontSize: 10 },
      axisLine: { lineStyle: { color: cssVarHsl("--border") } },
    },
    yAxis: axes.map((ax, i) => ({
      type: "value" as const,
      name: ax?.name,
      position: (i === 0 ? "left" : "right") as "left" | "right",
      nameTextStyle: { color: cssVarHsl("--muted-foreground"), fontSize: 10 },
      axisLabel: {
        color: cssVarHsl("--muted-foreground"),
        fontSize: 10,
        formatter: yAxisLabel(ax?.kind),
      },
      splitLine: { show: i === 0, lineStyle: { color: cssVarHsl("--border", 0.35) } },
    })),
    series: eSeries,
  };
}

function ChartCard({ chart, days }: { chart: WeeklyMetricChart; days: string[] }) {
  const option = useMemo(() => buildOption(chart, days), [chart, days]);
  const ref = useEChart(option, [option]);
  const hasData = safeArray<WeeklyMetricSeries>(chart.series).some((s) =>
    safeArray<number | null>(s.values).some((v) => finite(v) != null),
  );

  return (
    <div className="rounded-xl border border-border/60 bg-card/30 p-3">
      <div className="mb-1 text-xs font-bold text-foreground">{chart.title}</div>
      {chart.note && (
        <p className="mb-2 text-[10px] leading-relaxed text-muted-foreground/80">{chart.note}</p>
      )}
      {hasData ? (
        <div ref={ref} className="h-[220px] w-full min-w-0" />
      ) : (
        <p className="flex h-[220px] items-center justify-center text-[12px] text-muted-foreground/70">
          暂无可用数据
        </p>
      )}
    </div>
  );
}

export function WeeklyMetricsCharts({ data }: { data?: WeeklyMetricCharts }) {
  if (!data?.available) {
    return (
      <p className="text-[13px] text-muted-foreground">
        指标趋势暂不可用{data?.reason ? `：${data.reason}` : ""}
      </p>
    );
  }
  const days = safeArray<string>(data.days);
  const charts = safeArray<WeeklyMetricChart>(data.charts);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {charts.map((c) => (
        <ChartCard key={c.id} chart={c} days={days} />
      ))}
    </div>
  );
}
