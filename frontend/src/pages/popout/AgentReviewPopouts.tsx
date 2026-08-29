import { useEffect, useState } from "react";
import { CheckSquare } from "lucide-react";
import { PopupShell } from "@/components/PopupShell";
import { TradeBudgetCard } from "@/components/TradeBudgetCard";
import { cn } from "@/lib/utils";
import {
  agentFetch, finite, localDate, safeArray,
  type ReviewData, type VerificationItem,
} from "@/lib/agent";
import { api, type TradeBudget } from "@/lib/api";

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
  if (!v.unit) return `${Math.round(e * 100)} 个百分点`;
  if (v.unit === "%") return `${e} 个百分点`;
  return `${e}${v.unit}`;
}

function hasReviewPayload(r: ReviewData | null | undefined): boolean {
  return !!(r && (r.target_date || r.trade_date || r.focus || r.market_facts));
}

/** 明日验证条件列表（复盘看板与弹窗共用） */
export function TomorrowVerificationPanel({
  items,
  showHeader = true,
}: {
  items: VerificationItem[];
  showHeader?: boolean;
}) {
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">暂无明日验证条件</p>;
  }
  return (
    <div>
      {showHeader && (
        <h4 className="mb-2 flex items-center gap-1.5 text-sm font-bold">
          <CheckSquare className="h-4 w-4 text-info" /> 明日验证条件
          <span className="text-[11px] font-normal text-muted-foreground">
            明天用这几个读数检验今晚的判断
          </span>
        </h4>
      )}
      <div className="flex flex-wrap gap-2">
        {items.map((v, i) => (
          <div key={i} className="flex-1 basis-[240px] rounded-lg border border-border bg-muted/20 px-3 py-2">
            <div className="text-[13px] font-semibold">
              {v.label || METRIC_LABEL[v.metric] || v.metric}
              <span className={cn(
                "ml-1.5 rounded px-1.5 py-0.5 text-[11px] font-bold",
                v.direction === "上升" ? "bg-danger/15 text-danger"
                  : v.direction === "下降" ? "bg-success/15 text-success"
                    : "bg-muted text-muted-foreground",
              )}>
                预期{v.direction}
              </span>
            </div>
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
    </div>
  );
}

/** 仓位预算独立弹窗页 */
export function TradeBudgetPopout() {
  const [date, setDate] = useState(localDate());
  const [budget, setBudget] = useState<TradeBudget | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const r = await agentFetch<ReviewData>("/api/review/latest");
        const day = (hasReviewPayload(r) && (r.target_date || r.trade_date)) || localDate();
        if (cancelled) return;
        setDate(day);
        const b = await api.tradeBudget(day);
        if (!cancelled) setBudget(b);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <PopupShell title="仓位预算" subtitle={date ? `交易日 ${date}` : undefined}>
      {loading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {err && <p className="text-sm text-danger">{err}</p>}
      {!loading && !err && <TradeBudgetCard b={budget} date={date} />}
    </PopupShell>
  );
}

/** 明日验证条件独立弹窗页 */
export function VerificationPopout() {
  const [date, setDate] = useState("");
  const [items, setItems] = useState<VerificationItem[]>([]);
  const [oneliner, setOneliner] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const r = await agentFetch<ReviewData>("/api/review/latest");
        if (cancelled) return;
        if (!hasReviewPayload(r)) {
          setErr("暂无复盘数据");
          return;
        }
        const day = r.target_date || r.trade_date || "";
        setDate(day);
        setOneliner(r.focus?.market_oneliner || "");
        setItems(safeArray<VerificationItem>(r.focus?.verification_items));
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <PopupShell
      title="明日验证条件"
      subtitle={date ? `交易日 ${date}${oneliner ? ` · ${oneliner}` : ""}` : undefined}
    >
      {loading && <p className="text-sm text-muted-foreground">加载中…</p>}
      {err && <p className="text-sm text-danger">{err}</p>}
      {!loading && !err && <TomorrowVerificationPanel items={items} />}
    </PopupShell>
  );
}
