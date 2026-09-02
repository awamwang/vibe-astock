import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Globe2, Loader2, Network, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { request, ApiError } from "@/lib/api";
import { systemSettingsTo } from "@/lib/settingsNav";
import { Caliber } from "@/components/ui/Caliber";

/**
 * 复盘看板「全球事件概率」：Polymarket + Kalshi 公开价作外围情绪对照。
 * - 挂载只读快照；`refreshToken` 变化（如复盘生成完成）时强制重拉一次。
 * - 另有独立手动刷新按钮；不跟盘面其他区块联动。
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

function fmtPct(p: number | null | undefined): string {
  if (p == null || Number.isNaN(p)) return "—";
  return `${(p * 100).toFixed(1)}%`;
}

function fmtChg(c: number | null | undefined): string {
  if (c == null || Number.isNaN(c) || c === 0) return "—";
  const s = c > 0 ? "+" : "";
  return `${s}${(c * 100).toFixed(1)}pt`;
}

/** 短标签 + 一句话含义，方便复盘时扫读 */
function describeHighlight(h: PulseHighlight): { label: string; meaning: string } {
  const q = (h.title_en || h.title || "").trim();
  const ql = q.toLowerCase();
  const pick = h.pick_label ? `（档位：${h.pick_label}）` : "";

  if (h.topic === "货币政策") {
    if (ql.includes("no change") || ql.includes("unchanged")) {
      return {
        label: "Fed 利率不变",
        meaning: "市场押注下次美联储议息维持利率不变的概率；越高表示越不指望降息/加息。",
      };
    }
    if (ql.includes("decrease") || ql.includes("cut")) {
      const big = ql.includes("50") || ql.includes("50+");
      return {
        label: big ? "Fed 大幅降息" : "Fed 降息 25bp",
        meaning: big
          ? "市场押注下次议息一次降息 50 个基点及以上的概率。"
          : "市场押注下次议息降息 25 个基点的概率；升高通常对应全球风险偏好改善预期。",
      };
    }
    if (ql.includes("increase") || ql.includes("hike")) {
      return {
        label: "Fed 加息 25bp",
        meaning: "市场押注下次议息加息 25 个基点的概率；升高往往对应美元/美债偏强、成长估值承压预期。",
      };
    }
    return {
      label: "货币政策",
      meaning: `美联储相关事件合约：${q || "（无标题）"}${pick}`,
    };
  }

  if (h.topic === "地缘政治") {
    if (ql.includes("invade") && ql.includes("iran")) {
      return {
        label: "美方对伊军事升级",
        meaning: "市场押注美国在指定时点前对伊朗采取入侵/大规模军事行动的概率；属尾部风险溢价。",
      };
    }
    if (ql.includes("ceasefire") || ql.includes("cease fire")) {
      return {
        label: "以伊停火延续",
        meaning: "市场押注以色列与伊朗相关停火在约定期限内继续有效的概率；越高表示近月热战降温预期更强。",
      };
    }
    if (ql.includes("hormuz")) {
      return {
        label: "霍尔木兹航运恢复",
        meaning: "市场押注霍尔木兹海峡交通在约定期限前恢复正常的概率；偏低常对应油运/油价溢价。",
      };
    }
    if (ql.includes("iran")) {
      return {
        label: "伊朗相关地缘",
        meaning: `伊朗相关事件合约：${q || "（无标题）"}${pick}`,
      };
    }
    return {
      label: "地缘热门",
      meaning: `成交靠前的地缘事件：${q || "（无标题）"}${pick}`,
    };
  }

  if (h.topic === "AI科技") {
    if (ql.includes("anthropic")) {
      return {
        label: "Anthropic 模型领先",
        meaning: "市场押注约定期限末 Anthropic 拥有「最佳」AI 模型的概率；反映海外前沿大模型格局预期。",
      };
    }
    if (ql.includes("openai")) {
      return {
        label: "OpenAI 相关里程碑",
        meaning: `OpenAI 相关事件合约：${q || "（无标题）"}${pick}`,
      };
    }
    return {
      label: "AI 热门",
      meaning: `成交靠前的 AI/科技事件：${q || "（无标题）"}${pick}`,
    };
  }

  if (h.topic === "加密") {
    if (ql.includes("bitcoin") || ql.includes("btc")) {
      return {
        label: "比特币价位事件",
        meaning: "比特币是否触及某价位/日期的赌约；临近结算且概率贴边时，宏观参考价值较弱。",
      };
    }
    if (ql.includes("ethereum") || ql.includes("eth")) {
      return {
        label: "以太坊价位事件",
        meaning: "以太坊相关价位/日期赌约；更多反映加密风险偏好，与 A 股短线相关度有限。",
      };
    }
    return {
      label: "加密热门",
      meaning: `成交靠前的加密事件：${q || "（无标题）"}${pick}`,
    };
  }

  return {
    label: h.topic,
    meaning: `${q || "（无标题）"}${pick}`,
  };
}

function ProxyHintBanner({ reason }: { reason?: string | null }) {
  return (
    <div className="mt-3 rounded-md border border-amber-500/35 bg-amber-500/10 px-3 py-2.5">
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

export function GlobalPulseCards({
  refreshToken = 0,
}: {
  /** 复盘生成完成时递增，触发一次强制重拉 */
  refreshToken?: number;
}) {
  const [data, setData] = useState<PulseOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshStale, setRefreshStale] = useState(false);
  const alive = useRef(true);
  const pollGen = useRef(0);
  const dataRef = useRef<PulseOverview | null>(null);
  const skipTokenEffect = useRef(true);
  dataRef.current = data;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      pollGen.current += 1;
    };
  }, []);

  const apply = (res: PulseOverview) => {
    if (!alive.current) return;
    setData(res);
    setErr(null);
  };

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

  // 复盘生成完成后由父组件递增 refreshToken → 强制重拉
  useEffect(() => {
    if (skipTokenEffect.current) {
      skipTokenEffect.current = false;
      return;
    }
    if (refreshToken > 0) void manualRefresh();
  }, [refreshToken, manualRefresh]);

  const highlights = data?.highlights ?? [];
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
      "glass rounded-2xl p-5",
      notLatest && "ring-1 ring-amber-500/35",
    )}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <Globe2 className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-bold">全球事件概率</h3>
        <Caliber text={
          "价格即集体下注概率（$0.62≈62%），作外围宏观情绪对照，非买卖信号。\n" +
          "数据来自 Polymarket + Kalshi 公开接口；复盘生成完成会自动重拉一次，也可点本区块刷新。\n" +
          "直连失败时可在系统设置 → 代理设置中配置 SOCKS/HTTP。"
        } />
        {notLatest && (
          <span className="rounded border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:text-amber-200">
            非最新
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {data?.as_of && (
            <span className="text-[10px] text-muted-foreground/60">
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
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted/50 hover:text-primary disabled:opacity-50"
            title="单独刷新全球事件概率（不跟复盘其他区块）"
            disabled={refreshing}
          >
            {updating
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <RefreshCw className="h-3.5 w-3.5" />}
            刷新
          </button>
        </span>
      </div>

      <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground/80">
        外围预测市场温度计：看美联储、地缘、AI 等「市场在赌什么」。随复盘生成刷新一次，也可单独点刷新。
      </p>

      {err && (
        <p className="mb-2 text-[11px] text-danger/90">{err}</p>
      )}

      {loading && !data?.as_of && highlights.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">正在读取快照…</p>
      ) : highlights.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {data?.summary || "暂无核心模块数据"} · 可点右上角刷新。
        </p>
      ) : (
        <>
          {data?.summary && (
            <p className="mb-3 rounded-lg border border-border/40 bg-muted/20 px-3 py-2 text-[12px] leading-relaxed text-foreground/85">
              {data.summary}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-left text-[12px]">
              <thead>
                <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="py-1.5 pr-3 font-semibold">事件</th>
                  <th className="py-1.5 pr-3 font-semibold tabular-nums">概率</th>
                  <th className="py-1.5 pr-3 font-semibold tabular-nums">24h</th>
                  <th className="py-1.5 font-semibold">含义</th>
                </tr>
              </thead>
              <tbody>
                {highlights.map((h) => {
                  const { label, meaning } = describeHighlight(h);
                  const title = h.title_en || h.title || "";
                  return (
                    <tr key={h.key} className="border-b border-border/30 align-top last:border-0">
                      <td className="py-2.5 pr-3">
                        <div className="font-semibold text-foreground">{label}</div>
                        <div className="mt-0.5 text-[10px] text-muted-foreground">
                          {h.topic}
                          {h.source ? ` · ${h.source}` : ""}
                        </div>
                        {title && (
                          <div className="mt-0.5 max-w-[16rem] text-[10px] leading-snug text-muted-foreground/70" title={title}>
                            {title}
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-sm font-bold tabular-nums text-foreground">
                        {fmtPct(h.prob_yes)}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] tabular-nums text-muted-foreground">
                        {fmtChg(h.change_24h)}
                      </td>
                      <td className="py-2.5 text-[11px] leading-relaxed text-muted-foreground">
                        {meaning}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {(notLatest || (!loading && highlights.length === 0)) && (
        <ProxyHintBanner reason={staleReason} />
      )}
    </div>
  );
}
