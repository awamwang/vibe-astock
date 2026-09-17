import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw, LayoutGrid } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { cn } from "@/lib/utils";
import { pctColor } from "@/lib/colors";
import { fetchMarketSession, type MarketSession } from "@/lib/liveBoard";
import {
  fetchStyleIndices,
  formatStylePct,
  type StyleIndexGroup,
  type StyleIndicesSnapshot,
} from "@/lib/styleIndices";

const CALIBER =
  "当场涨幅，对比前一交易日收盘。风格/行业板块走东财概念与行业列表，宽基与外围走东财 ulist，缺了再用腾讯指数补。\n" +
  "「昨日涨停表现」对应东财「昨日涨停_含一字」，不是赚钱效应中位数，也不是打板情绪。\n" +
  "同花顺专有指数（情绪 / 全A / 热股 / 平均股价 / 短期期货恐慌 / 高贝塔 / 高股息精选）公开源没有，页底列出未接入。中证全指、东财热股、中证红利只是公开近似，名字没有写成同花顺那条。\n" +
  "报价是延时行情。随盘场次约 20 秒刷新一次缓存。";

const LIVE_MS = 15_000;

function breadth(up: number | null, down: number | null): string | null {
  if (up == null || down == null) return null;
  if (up === 0 && down === 0) return null;
  return `↑${up} ↓${down}`;
}

function GroupCard({ group }: { group: StyleIndexGroup }) {
  return (
    <GlassCard className="p-4">
      <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{group.label}</h3>
      <div>
        {group.items.map((it) => (
          <div
            key={it.key}
            className="flex items-baseline justify-between gap-3 border-b border-border/40 py-1.5 last:border-0"
          >
            <div className="min-w-0">
              <div className="truncate text-sm">{it.name}</div>
              {it.note && (
                <div className="truncate text-[10px] leading-tight text-muted-foreground/70">{it.note}</div>
              )}
            </div>
            <div className="shrink-0 text-right">
              <div className={cn("font-mono text-base font-bold tabular-nums", pctColor(it.change_pct))}>
                {formatStylePct(it.change_pct)}
              </div>
              {breadth(it.up, it.down) && (
                <div className="font-mono text-[10px] text-muted-foreground/60">{breadth(it.up, it.down)}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

export function ShortStyle() {
  const [snap, setSnap] = useState<StyleIndicesSnapshot | null>(null);
  const [session, setSession] = useState<MarketSession | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const [out, sess] = await Promise.all([
        fetchStyleIndices(),
        fetchMarketSession().catch(() => null),
      ]);
      setSnap(out);
      if (sess) setSession(sess);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const liveNow = session?.phase === "盘中" || session?.phase === "集合竞价";
  useEffect(() => {
    if (!autoRefresh || !liveNow) return;
    const t = setInterval(() => { void load(); }, LIVE_MS);
    return () => clearInterval(t);
  }, [autoRefresh, liveNow, load]);

  const context = useMemo(() => {
    if (!snap?.groups?.length) return "短线风格指数尚未取到。";
    const lines = snap.groups.map((g) => {
      const body = g.items
        .map((it) => `${it.name} ${formatStylePct(it.change_pct)}`)
        .join("，");
      return `${g.label}：${body}`;
    });
    return `${snap.date} 短线风格指数（${snap.is_live ? "随盘" : "定稿"}，${snap.hit}/${snap.total} 有报价）。\n${lines.join("\n")}`;
  }, [snap]);

  return (
    <div>
      <PageHeader
        title="短线风格"
        subtitle={`${session?.label ?? snap?.date ?? "—"} · 风格板块与公开指数当场涨幅，不是打板情绪`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAutoRefresh((v) => !v)}
              title={autoRefresh ? "已开：盘中约 15 秒刷新" : "开启后在交易时段自动刷新"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors",
                autoRefresh
                  ? "bg-primary/15 text-primary hover:bg-primary/25"
                  : "text-muted-foreground hover:text-primary",
              )}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", autoRefresh && liveNow && "animate-spin")} />
              {autoRefresh ? (liveNow ? "每 15 秒" : "自动刷新（非交易时段暂停）") : "自动刷新"}
            </button>
            <button
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-primary"
              title="刷新"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              刷新
            </button>
            <AskAiButton
              context={context}
              label="问 AI"
              suggestions={["哪些风格在领涨", "大小盘怎么分", "打板风格和宽基是否同向"]}
            />
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-baseline gap-2">
        <LayoutGrid className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm text-muted-foreground">
          {snap ? `${snap.hit}/${snap.total} 有报价` : "加载中"}
          {snap?.updated ? ` · ${snap.updated}` : ""}
        </span>
        <Caliber text={CALIBER} />
      </div>

      {err && <p className="mb-4 text-sm text-warning">{err}</p>}

      {!snap && !err && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 正在取风格指数…
        </div>
      )}

      {snap && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {snap.groups.map((g) => (
            <GroupCard key={g.id} group={g} />
          ))}
        </div>
      )}

      {snap && snap.unavailable.length > 0 && (
        <GlassCard className="mt-4 p-4">
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">未接入（同花顺专有或公开源没有）</h3>
          <ul className="space-y-1.5 text-[12px] text-muted-foreground">
            {snap.unavailable.map((u) => (
              <li key={u.key}>
                <span className="text-foreground/80">{u.name}</span>
                <span className="mx-1.5 text-muted-foreground/40">·</span>
                {u.reason}
              </li>
            ))}
          </ul>
        </GlassCard>
      )}

      <Disclaimer />
    </div>
  );
}
