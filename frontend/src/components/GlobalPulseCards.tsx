import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Loader2, Network, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { request, ApiError } from "@/lib/api";
import { systemSettingsTo } from "@/lib/settingsNav";

/**
 * 短线盘面「市场整体」内嵌的全球事件概率条。
 * - 挂载时只读快照一次；不跟盘面「自动刷新」、也不跟「市场整体」区刷新按钮。
 * - 仅本组件右上角手动刷新会 refresh=true 并轮询至完成（主页与弹窗同一组件）。
 */

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
  stale?: boolean;
  fresh?: boolean;
  stale_reason?: string | null;
  age_hours?: number | null;
  proxy_configured?: boolean;
  last_refresh_ok?: boolean | null;
  last_refresh_error?: string | null;
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

function ProxyHintBanner({ reason }: { reason?: string | null }) {
  return (
    <div className="mt-2 rounded-md border border-amber-500/35 bg-amber-500/10 px-2.5 py-2">
      <div className="flex flex-wrap items-start gap-2">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-[11px] font-medium text-amber-800 dark:text-amber-200">
            未拉到最新数据
            {reason ? ` · ${reason}` : ""}
          </p>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            本功能需本机可访问 Polymarket / Kalshi 公开接口；网络受限时通常要配置代理后再手动刷新。
          </p>
        </div>
        <Link
          to={systemSettingsTo("proxy")}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-amber-500/40 bg-background/60 px-2 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-500/15 dark:text-amber-200"
        >
          <Network className="h-3 w-3" />
          代理设置
        </Link>
      </div>
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
  const [refreshStale, setRefreshStale] = useState(false);
  const alive = useRef(true);
  const pollGen = useRef(0);
  const dataRef = useRef<PulseOverview | null>(null);
  dataRef.current = data;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      pollGen.current += 1; // 取消进行中的手动刷新轮询
    };
  }, []);

  const apply = (res: PulseOverview) => {
    if (!alive.current) return;
    setData(res);
    setErr(null);
  };

  /** 仅手动 refresh 后轮询，直到 as_of 前进或 updating 结束 */
  const pollUntilFresh = async (prevAsOf: string | null | undefined, gen: number) => {
    let advanced = false;
    for (let i = 0; i < POLL_MAX; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      if (!alive.current || pollGen.current !== gen) return;
      try {
        const fresh = await request<PulseOverview>("/pulse/overview");
        if (!alive.current || pollGen.current !== gen) return;
        apply(fresh);
        if (fresh.as_of && fresh.as_of !== prevAsOf && !fresh.updating) {
          advanced = true;
          setRefreshStale(Boolean(fresh.stale));
          return;
        }
        if (fresh.as_of && !fresh.updating) {
          advanced = fresh.as_of !== prevAsOf;
          setRefreshStale(Boolean(fresh.stale) || !advanced);
          return;
        }
      } catch {
        /* 轮询容错 */
      }
    }
    if (!advanced) setRefreshStale(true);
  };

  const loadSnapshotOnce = useCallback(async () => {
    setLoading(true);
    try {
      // 只读快照，绝不带 refresh=true，也不因 updating 自动轮询
      const res = await request<PulseOverview>("/pulse/overview");
      apply(res);
      setRefreshStale(false);
    } catch (e) {
      if (!alive.current) return;
      setErr(e instanceof ApiError ? e.message : "事件概率加载失败");
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  const manualRefresh = useCallback(async () => {
    const gen = ++pollGen.current;
    setRefreshing(true);
    setRefreshStale(false);
    const prevAsOf = dataRef.current?.as_of;
    try {
      const res = await request<PulseOverview>("/pulse/overview?refresh=true");
      if (!alive.current || pollGen.current !== gen) return;
      apply(res);
      if (res.updating || !res.as_of) {
        await pollUntilFresh(prevAsOf ?? res.as_of, gen);
      } else {
        setRefreshStale(Boolean(res.stale));
      }
    } catch (e) {
      if (!alive.current || pollGen.current !== gen) return;
      setErr(e instanceof ApiError ? e.message : "事件概率刷新失败");
      setRefreshStale(true);
    } finally {
      if (alive.current && pollGen.current === gen) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadSnapshotOnce();
  }, [loadSnapshotOnce]);

  const highlights = data?.highlights ?? [];
  const showSkeleton = loading && !data?.as_of && !(data?.highlights?.length);
  const updating = refreshing;
  const notLatest = Boolean(
    err
    || refreshStale
    || data?.stale
    || data?.last_refresh_ok === false
    || (!loading && !updating && (!data?.as_of || highlights.length === 0)),
  );
  const staleReason =
    err
    || data?.stale_reason
    || data?.last_refresh_error
    || (refreshStale ? "本次刷新未能更新快照（网络不通或需代理）" : null)
    || (!data?.as_of || highlights.length === 0 ? "暂无可用数据" : null);

  return (
    <div className={cn(
      "rounded-lg border p-2.5",
      notLatest
        ? "border-amber-500/40 bg-amber-500/[0.06]"
        : "border-sky-500/30 bg-sky-500/[0.06]",
    )}>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <span className={cn(
          "text-[11px] font-semibold tracking-wide",
          notLatest ? "text-amber-700 dark:text-amber-400" : "text-sky-700 dark:text-sky-400",
        )}>
          全球事件概率
        </span>
        {notLatest && (
          <span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:text-amber-200">
            非最新
          </span>
        )}
        <span className="text-[10px] text-muted-foreground/55">
          Polymarket + Kalshi · 仅手动刷新 · 不跟盘面自动刷新
        </span>
        <span className="ml-auto flex items-center gap-2">
          {data?.as_of && (
            <span className="text-[10px] text-muted-foreground/50">
              {data.as_of.replace("T", " ")}
              {updating ? " · 更新中" : ""}
              {typeof data.age_hours === "number" && data.age_hours >= 1
                ? ` · ${data.age_hours.toFixed(0)}h 前`
                : ""}
            </span>
          )}
          <button
            type="button"
            onClick={() => void manualRefresh()}
            className="text-muted-foreground hover:text-primary"
            title="手动重新拉取双源（不跟短线盘面自动刷新）"
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
          <p className="mt-2 text-[11px] text-muted-foreground/70">
            暂无快照。点右上角手动刷新拉取（首次可能较慢）；不跟盘面自动刷新。
          </p>
          <ProxyHintBanner reason="首次拉取需要访问境外源站" />
        </>
      ) : highlights.length === 0 ? (
        <>
          <p className="text-[11px] text-muted-foreground/60">
            {data?.summary || "暂无核心模块数据"}
            {" · "}
            点右上角手动刷新。
          </p>
          <ProxyHintBanner reason={staleReason} />
        </>
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
          {notLatest && <ProxyHintBanner reason={staleReason} />}
        </>
      )}
    </div>
  );
}
