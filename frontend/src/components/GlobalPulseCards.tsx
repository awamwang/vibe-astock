import { useEffect, useRef, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { request, ApiError } from "@/lib/api";

/** 短线盘面「市场整体」内嵌的全球事件概率条：独立请求，骨架占位，不挡主盘面。 */

export interface PulseHighlight {
  key: string;
  topic: string;
  title: string | null;
  title_en?: string | null;
  pick_label?: string | null;
  prob_yes: number | null;
  change_24h?: number | null;
  volume_24h?: number | null;
  source?: string;
}

export interface PulseOverview {
  as_of?: string | null;
  summary?: string;
  highlights?: PulseHighlight[];
  updating?: boolean;
}

function shortLabel(h: PulseHighlight): string {
  const q = (h.title_en || h.title || "").toLowerCase();
  if (h.topic === "货币政策") {
    if (q.includes("no change") || q.includes("unchanged")) return "Fed不变";
    if (q.includes("decrease") || q.includes("cut")) return "Fed降息";
    if (q.includes("increase") || q.includes("hike")) return "Fed加息";
    return "货币政策";
  }
  if (h.topic === "地缘政治") {
    if (q.includes("hormuz")) return "霍尔木兹";
    if (q.includes("iran")) return "伊朗相关";
    return "地缘热门";
  }
  if (h.topic === "AI科技") return "AI热门";
  if (h.topic === "加密") {
    if (q.includes("bitcoin") || q.includes("btc")) return "BTC事件";
    if (q.includes("ethereum") || q.includes("eth")) return "ETH事件";
    return "加密热门";
  }
  return h.topic;
}

function fmtPct(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(1)}%`;
}

function fmtChg(c: number | null | undefined): string {
  if (c == null || Number.isNaN(c) || c === 0) return "";
  const s = c > 0 ? "+" : "";
  return `${s}${(c * 100).toFixed(1)}pt`;
}

function PulseCard({
  name, value, sub, title,
}: {
  name: string;
  value: string;
  sub?: string;
  title?: string;
}) {
  return (
    <div
      className="min-w-[5.5rem] max-w-[9rem] rounded-lg border border-border/50 bg-card/60 px-2.5 py-2 shadow-sm"
      title={title}
    >
      <p className="truncate text-[11px] font-semibold text-foreground/80">{name}</p>
      <div className="mt-1 border-t border-border/40 pt-1 font-mono text-sm">
        <span className="font-bold text-foreground">{value}</span>
        {sub ? <span className="ml-1 text-[10px] text-muted-foreground">{sub}</span> : null}
      </div>
    </div>
  );
}

function SkeletonCards() {
  return (
    <div className="flex flex-wrap items-stretch gap-2">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="min-w-[5.5rem] h-[3.25rem] rounded-lg border border-border/40 bg-muted/30 animate-pulse"
        />
      ))}
    </div>
  );
}

const POLL_MS = 20_000;
const POLL_MAX = 24;

export function GlobalPulseCards() {
  const [data, setData] = useState<PulseOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const apply = (res: PulseOverview) => {
    if (!alive.current) return;
    setData(res);
    setErr(null);
  };

  const pollUntilFresh = async (prevAsOf: string | null | undefined) => {
    for (let i = 0; i < POLL_MAX; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (!alive.current) return;
      try {
        const fresh = await request<PulseOverview>("/pulse/overview");
        if (!alive.current) return;
        apply(fresh);
        if (fresh.as_of && fresh.as_of !== prevAsOf && !fresh.updating) return;
        if (fresh.as_of && !fresh.updating) return;
      } catch {
        /* 轮询容错 */
      }
    }
  };

  const load = async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    const prevAsOf = data?.as_of;
    try {
      const path = refresh ? "/pulse/overview?refresh=true" : "/pulse/overview";
      const res = await request<PulseOverview>(path);
      apply(res);
      if (res.updating || !res.as_of) {
        void pollUntilFresh(prevAsOf ?? res.as_of);
      }
    } catch (e) {
      if (!alive.current) return;
      setErr(e instanceof ApiError ? e.message : "事件概率加载失败");
    } finally {
      if (alive.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  };

  useEffect(() => {
    void load(false);
    // 仅挂载时拉一次，不跟短线盘面主刷新绑死
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const highlights = data?.highlights ?? [];
  const showSkeleton = loading && !data?.as_of;
  const updating = Boolean(data?.updating) || refreshing;

  return (
    <div
      className={cn(
        "rounded-lg border border-sky-500/30 bg-sky-500/[0.06] p-2.5",
      )}
    >
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className="text-[11px] font-semibold tracking-wide text-sky-700 dark:text-sky-400">
          全球事件概率
        </span>
        <span className="text-[10px] text-muted-foreground/55">
          Polymarket + Kalshi · 价格即概率 · 非交易信号
        </span>
        <span className="ml-auto flex items-center gap-2">
          {data?.as_of && (
            <span className="text-[10px] text-muted-foreground/50">
              {data.as_of.replace("T", " ")}
              {updating ? " · 更新中" : ""}
            </span>
          )}
          <button
            type="button"
            onClick={() => void load(true)}
            className="text-muted-foreground hover:text-primary"
            title="重新拉取双源（后台重建，不阻塞本页）"
            disabled={refreshing}
          >
            {updating
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <RefreshCw className="h-3.5 w-3.5" />}
          </button>
        </span>
      </div>

      {err && !showSkeleton && (
        <p className="mb-2 text-[11px] text-danger/90">{err}</p>
      )}

      {showSkeleton ? (
        <>
          <SkeletonCards />
          <p className="mt-2 text-[11px] text-muted-foreground/70 animate-pulse">
            外围概率拉取中（首次可能需数分钟，不影响上方盘面）…
          </p>
        </>
      ) : highlights.length === 0 ? (
        <p className="text-[11px] text-muted-foreground/60">
          {data?.summary || "暂无核心模块数据"}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-stretch gap-2">
            {highlights.map((h) => (
              <PulseCard
                key={h.key}
                name={shortLabel(h)}
                value={fmtPct(h.prob_yes)}
                sub={fmtChg(h.change_24h)}
                title={[h.title || h.title_en, h.pick_label ? `档位 ${h.pick_label}` : null]
                  .filter(Boolean)
                  .join(" · ")}
              />
            ))}
          </div>
          {data?.summary && (
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground/80">
              {data.summary}
            </p>
          )}
        </>
      )}
    </div>
  );
}
