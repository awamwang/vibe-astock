import { useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import { cn } from "@/lib/utils";
import { useEChart } from "@/hooks/useEChart";
import { cssVarHsl } from "@/lib/colors";
import { safeArray, type ThemeMatrix, type ThemeMatrixDay, type ThemeMatrixRank, type ThemeMatrixRow } from "@/lib/agent";

const STATE_TONE: Record<string, string> = {
  延续: "bg-success/15 text-success",
  扩散中: "bg-primary/15 text-primary",
  高标独活: "bg-warning/15 text-warning",
  分歧加大: "bg-danger/15 text-danger",
  接力断档: "bg-danger/20 text-danger",
  今日新出现: "bg-info/15 text-info",
  维持: "bg-muted text-muted-foreground",
  无昨日题材数据: "bg-muted text-muted-foreground/70",
};

const TAG_ACTIVE = "ring-2 ring-primary/70 bg-primary/15 border-primary/40 shadow-sm";
const TAG_DIM = "opacity-45";

function shortDate(d: string) {
  const p = d.split("-");
  return p.length === 3 ? `${p[1]}-${p[2]}` : d;
}

function ranksFromByDay(byDay: Record<string, ThemeMatrixDay>, dates: string[], limit = 12): ThemeMatrixRank[] {
  const scores: Record<string, number> = {};
  for (const d of dates) {
    const day = byDay[d];
    if (!day?.available) continue;
    for (const row of safeArray<ThemeMatrixRow>(day.themes)) {
      if (row.tag) scores[row.tag] = (scores[row.tag] || 0) + (row.limit_up || 0);
    }
  }
  return Object.entries(scores)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([tag, score]) => ({ tag, score }));
}

function RankTable({
  title,
  rows,
  activeTag,
  hoverTag,
  onSelectTag,
  onHoverTag,
}: {
  title: string;
  rows: ThemeMatrixRank[];
  activeTag: string | null;
  hoverTag: string | null;
  onSelectTag: (tag: string) => void;
  onHoverTag: (tag: string | null) => void;
}) {
  const list = safeArray<ThemeMatrixRank>(rows);
  const lit = activeTag || hoverTag;
  return (
    <div className="rounded-xl border border-border/60 bg-card/40 p-3">
      <div className="mb-2 text-xs font-bold text-muted-foreground">{title}</div>
      {list.length === 0 ? (
        <p className="text-[11px] text-muted-foreground/70">暂无数据</p>
      ) : (
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-[10px] text-muted-foreground">
              <th className="pb-1 text-left font-medium">题材</th>
              <th className="pb-1 text-right font-medium">涨停</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => {
              const isActive = r.tag === activeTag;
              const isLit = r.tag === lit;
              return (
                <tr
                  key={r.tag}
                  className={cn(
                    "border-t border-border/40 cursor-pointer transition-all rounded-md",
                    isLit && TAG_ACTIVE,
                    lit && !isLit && TAG_DIM,
                  )}
                  onClick={() => onSelectTag(r.tag)}
                  onMouseEnter={() => onHoverTag(r.tag)}
                  onMouseLeave={() => onHoverTag(null)}
                >
                  <td className="py-1 pr-2">
                    <span className="mr-1 text-[10px] text-muted-foreground">{i + 1}</span>
                    <span className={cn("font-medium", isActive && "text-primary")}>{r.tag}</span>
                  </td>
                  <td className={cn("py-1 text-right tabular-nums font-bold", isLit ? "text-primary" : "text-primary/80")}>
                    {r.score}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function DayColumn({
  date,
  day,
  activeTag,
  hoverTag,
  onSelectTag,
  onHoverTag,
}: {
  date: string;
  day?: ThemeMatrixDay;
  activeTag: string | null;
  hoverTag: string | null;
  onSelectTag: (tag: string) => void;
  onHoverTag: (tag: string | null) => void;
}) {
  const themes = safeArray<ThemeMatrixRow>(day?.themes);
  const maxLu = Math.max(1, ...themes.map((t) => t.limit_up || 0));
  const lit = activeTag || hoverTag;
  return (
    <div className="flex min-w-[148px] shrink-0 flex-col rounded-xl border border-border/60 bg-card/30">
      <div className="border-b border-border/50 bg-muted/30 px-2 py-2 text-center text-xs font-bold tabular-nums">
        {shortDate(date)}
        {day?.source === "review" && (
          <span className="ml-1 text-[9px] font-normal text-primary/80">复盘</span>
        )}
      </div>
      {!day?.available ? (
        <div className="px-2 py-4 text-center text-[11px] text-muted-foreground/80">
          {day?.reason || "无复盘题材树"}
        </div>
      ) : themes.length === 0 ? (
        <div className="px-2 py-4 text-center text-[11px] text-muted-foreground/70">无题材</div>
      ) : (
        <div className="flex-1 space-y-1 p-1.5">
          {themes.map((t) => {
            const isActive = t.tag === activeTag;
            const isLit = t.tag === lit;
            return (
              <div
                key={`${date}-${t.tag}`}
                role="button"
                tabIndex={0}
                className={cn(
                  "rounded-lg border border-transparent bg-background/60 px-2 py-1.5 cursor-pointer transition-all",
                  isLit && TAG_ACTIVE,
                  lit && !isLit && TAG_DIM,
                )}
                onClick={() => onSelectTag(t.tag)}
                onMouseEnter={() => onHoverTag(t.tag)}
                onMouseLeave={() => onHoverTag(null)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectTag(t.tag);
                  }
                }}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className={cn("truncate text-[12px] font-bold leading-tight", isLit && "text-primary")}>
                    {t.tag}
                  </span>
                  <span className="shrink-0 text-sm font-extrabold tabular-nums text-primary">{t.limit_up}</span>
                </div>
                <div
                  className={cn("mt-1 h-1.5 rounded-full", isLit ? "bg-primary" : "bg-primary/80")}
                  style={{ width: `${Math.max(12, (t.limit_up / maxLu) * 100)}%` }}
                />
                <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
                  {t.state && (
                    <span className={cn("rounded px-1 py-0.5 font-bold", STATE_TONE[t.state] || "bg-muted")}>
                      {t.state}
                    </span>
                  )}
                  <span>最高{t.highest}板</span>
                  {t.limit_down > 0 && <span className="text-success">跌{t.limit_down}</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ThemeMatrixChart({
  matrix,
  windowDays,
  fallbackDates = [],
}: {
  matrix?: ThemeMatrix;
  windowDays: number;
  fallbackDates?: string[];
}) {
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [hoverTag, setHoverTag] = useState<string | null>(null);

  const toggleTag = (tag: string) => {
    setActiveTag((cur) => (cur === tag ? null : tag));
  };

  const byDay = matrix?.by_day || {};
  const dates = useMemo(() => {
    const fromMatrix = safeArray<string>(matrix?.days);
    if (fromMatrix.length) return fromMatrix;
    return safeArray<string>(fallbackDates);
  }, [matrix?.days, fallbackDates]);

  const rankWindow = useMemo(() => {
    const stored = safeArray<ThemeMatrixRank>(matrix?.rank_window);
    if (stored.length) return stored;
    return ranksFromByDay(byDay, dates);
  }, [matrix?.rank_window, byDay, dates]);

  const rank3d = useMemo(() => {
    const stored = safeArray<ThemeMatrixRank>(matrix?.rank_3d);
    if (stored.length) return stored;
    const last3 = dates.slice(-3);
    return ranksFromByDay(byDay, last3);
  }, [matrix?.rank_3d, byDay, dates]);

  const avail = matrix?.available_days ?? dates.filter((d) => byDay[d]?.available).length;
  const total = matrix?.total_days ?? dates.length;
  const reviewDays = matrix?.review_days ?? dates.filter((d) => byDay[d]?.source === "review").length;

  const heatmapOption = useMemo((): EChartsOption | null => {
    if (!dates.length || !rankWindow.length) return null;
    const tags = rankWindow.slice(0, 16).map((r) => r.tag);
    const xLabels = dates.map(shortDate);
    const data: [number, number, number][] = [];
    let vmax = 1;
    tags.forEach((tag, yi) => {
      dates.forEach((d, xi) => {
        const day = byDay[d];
        const row = safeArray<ThemeMatrixRow>(day?.themes).find((t) => t.tag === tag);
        const v = row?.limit_up ?? 0;
        if (v > vmax) vmax = v;
        data.push([xi, yi, v]);
      });
    });
    const cMuted = cssVarHsl("--muted");
    const cPrimary = cssVarHsl("--primary");
    const cPrimaryMid = cssVarHsl("--primary", 0.45);
    const cMutedFg = cssVarHsl("--muted-foreground");
    const cFg = cssVarHsl("--foreground");
    const cBorder = cssVarHsl("--border");

    return {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 88, right: 16, top: 28, bottom: 56 },
      tooltip: {
        formatter: (p) => {
          const pt = p as unknown as { data?: [number, number, number] };
          const [xi, yi, v] = pt.data || [0, 0, 0];
          const tag = tags[yi] || "";
          const d = dates[xi] || "";
          const day = byDay[d];
          const row = safeArray<ThemeMatrixRow>(day?.themes).find((t) => t.tag === tag);
          const extra = row
            ? `阶段 ${row.state} · 最高${row.highest}板 · 跌停${row.limit_down}`
            : "";
          return `<b>${tag}</b><br/>${d} 涨停 <b>${v}</b>${extra ? `<br/>${extra}` : ""}`;
        },
      },
      xAxis: {
        type: "category",
        data: xLabels,
        axisLabel: { fontSize: 11, color: cMutedFg },
        axisLine: { lineStyle: { color: cBorder } },
      },
      yAxis: {
        type: "category",
        data: tags,
        axisLabel: { fontSize: 11, color: cFg, width: 72, overflow: "truncate" },
        axisLine: { show: false },
        splitLine: { show: false },
      },
      visualMap: {
        min: 0,
        max: vmax,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 4,
        itemWidth: 12,
        itemHeight: 64,
        inRange: { color: [cMuted, cPrimaryMid, cPrimary] },
        textStyle: { color: cMutedFg, fontSize: 10 },
      },
      series: [{
        type: "heatmap",
        data,
        label: {
          show: true,
          formatter: (p) => {
            const raw = p as unknown as { data?: [number, number, number] };
            const v = raw.data?.[2] ?? 0;
            return v > 0 ? String(v) : "";
          },
          fontSize: 10,
          color: cFg,
        },
        emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.2)" } },
      }],
    };
  }, [dates, byDay, rankWindow]);

  const heatRef = useEChart(heatmapOption, [heatmapOption]);
  const heatHeight = Math.max(220, Math.min(420, (rankWindow.length || 8) * 22 + 64));

  const tagProps = {
    activeTag,
    hoverTag,
    onSelectTag: toggleTag,
    onHoverTag: setHoverTag,
  };

  return (
    <div className="flex w-full min-w-0 flex-col gap-4 lg:flex-row">
      <div className="flex shrink-0 flex-col gap-3 lg:w-44">
        <RankTable title="3日排名" rows={rank3d} {...tagProps} />
        <RankTable title={`${windowDays}日排名`} rows={rankWindow} {...tagProps} />
      </div>
      <div className="min-w-0 flex-1 space-y-4">
        {activeTag && (
          <p className="text-[12px] text-muted-foreground">
            已选中题材 <b className="text-primary">{activeTag}</b> — 同名项已联动高亮，再次点击取消
          </p>
        )}
        {total > 0 && avail < total && (
          <p className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-[12px] text-muted-foreground">
            共 {avail}/{total} 天有题材数据（{reviewDays} 天来自复盘落盘）。
            缺数据的日期需跑复盘或在首板分析导入涨停原因；有数据的日期会照常展示。
          </p>
        )}
        <div className="rounded-2xl border border-border/60 bg-card/20 p-3">
          <div className="mb-2 text-xs font-semibold text-muted-foreground">
            题材涨停热力（优先读 reviews 里的 theme_tree，按涨停数着色）
          </div>
          {heatmapOption ? (
            <div ref={heatRef} style={{ width: "100%", height: heatHeight }} />
          ) : (
            <p className="py-8 text-center text-sm text-muted-foreground">
              窗口内暂无可用题材树 —— 请先对对应日期跑复盘（落盘 market_facts.theme_tree），或导入涨停原因后刷新
            </p>
          )}
        </div>
        <div className="rounded-2xl border border-border/60 bg-card/20 p-3">
          <div className="mb-2 text-xs font-semibold text-muted-foreground">
            多日涨停分布（按涨停数排名 · 点击题材联动高亮）
          </div>
          {dates.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">暂无交易日</p>
          ) : (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {dates.map((d) => (
                <DayColumn key={d} date={d} day={byDay[d]} {...tagProps} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
