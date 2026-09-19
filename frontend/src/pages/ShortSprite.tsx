import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, RefreshCw, Zap } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Caliber } from "@/components/ui/Caliber";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SectionPopupButton } from "@/components/SectionPopupButton";
import { cn } from "@/lib/utils";
import { DOWN_TEXT, UP_TEXT } from "@/lib/colors";
import { keywordsSettingsTo } from "@/lib/settingsNav";
import { delayUntilNextUnixSlot } from "@/lib/wallClock";
import {
  fetchShortSprite,
  fmtSampleTs,
  fmtSpriteValue,
  setShortSpriteEnabled,
  type ShortSpriteSnapshot,
  type SpriteHit,
  type SpriteSequence,
} from "@/lib/shortSprite";
import { fetchMarketSession, type MarketSession } from "@/lib/liveBoard";

const CALIBER =
  "短线精灵只盯短线盘面、短线风格已有快照里单独列出的市场级序列：溢价、环境条上涨数/下跌数、情绪温度、情绪分、打板情绪共振默认分，以及配置页上的指定风格项当场涨幅。\n" +
  "打板、市值、短线属性、其他默认开监控；红利、宽基默认关。不把短线风格指数整组当一条监控指标。不盯个股，不盯人气榜/成交额榜/板块管理。命中是观察记录，不是买卖指令。\n" +
  "开盘记录 = 该场次 09:30 之后第一条非空随盘快照。涨速 = 当前值 − 约 5 分钟前的值（点不足则空）；涨速命中记下该窗两端读数。突破/跌破是相对开盘记录的差穿过阈值边沿，不记窗。\n" +
  "情绪温度、情绪分的突破/跌破按阈值整数倍继续报（15、30、45…），每档边沿一次，回差后可再报。\n" +
  "上涨数/下跌数用环境条随盘家数，不是市场整体卡片上的 overview 家数。下跌数升高为绿。";

function hitShowsUp(hit: Pick<SpriteHit, "direction" | "reversed">): boolean {
  const up = hit.direction === "up";
  return hit.reversed ? !up : up;
}

/** 数值涨跌色：红涨绿跌，reversed 序列取反。 */
export function hitDirClass(hit: Pick<SpriteHit, "direction" | "reversed">): string {
  return hitShowsUp(hit) ? UP_TEXT : DOWN_TEXT;
}

/** 卡片边框/底色：好坏。 */
export function hitToneClass(hit: Pick<SpriteHit, "direction" | "reversed">): string {
  return hitShowsUp(hit)
    ? "border-danger/45 bg-danger/10 border-l-danger"
    : "border-success/45 bg-success/10 border-l-success";
}

/** 类型文字色：涨速 / 突破 / 跌破。 */
export function hitEventClass(label: string): string {
  if (label === "涨速") return "text-primary";
  if (label === "突破") return "text-warning";
  return "text-muted-foreground";
}

export function speedWindowLabel(hit: Pick<SpriteHit, "event" | "from_value" | "to_value" | "from_ts" | "unit">): string | null {
  if (hit.event !== "speed_up" && hit.event !== "speed_down") return null;
  if (hit.from_value == null || hit.to_value == null) return null;
  const a = fmtSpriteValue(hit.from_value, hit.unit);
  const b = fmtSpriteValue(hit.to_value, hit.unit);
  const fromTs = hit.from_ts != null ? `${fmtSampleTs(hit.from_ts)} ` : "";
  return `${fromTs}${a} → ${b}`;
}

export function SpriteHitList({ hits, empty }: { hits: SpriteHit[]; empty?: string }) {
  if (!hits.length) {
    return <p className="text-sm text-muted-foreground">{empty || "本场次还没有命中。"}</p>;
  }
  return (
    <ul className="space-y-1.5">
      {hits.map((h) => {
        const window = speedWindowLabel(h);
        return (
        <li
          key={h.id}
          className={cn("rounded-md border border-l-4 px-3 py-2", hitToneClass(h))}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className={cn("text-sm", hitEventClass(h.event_label))}>
              {h.name}
              <span className="ml-2 text-[11px]">{h.event_label}</span>
            </span>
            <span className={cn("font-mono text-sm tabular-nums", hitDirClass(h))}>
              {fmtSpriteValue(h.value, h.unit)}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {h.ts.replace("T", " ")}
            {window ? ` · ${window}` : ""}
            {h.voice ? "" : " · 静音"}
          </div>
        </li>
        );
      })}
    </ul>
  );
}

function EnableButton({
  enabled, busy, onToggle,
}: {
  enabled: boolean;
  busy: boolean;
  onToggle: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onToggle(!enabled)}
      disabled={busy}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors disabled:opacity-50",
        enabled ? "bg-primary/15 text-primary hover:bg-primary/25" : "text-muted-foreground hover:text-primary",
      )}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
      {enabled ? "运行中" : "已停止"}
    </button>
  );
}

function groupByLabel<T extends { group?: string; group_label?: string; kind?: string }>(
  items: T[],
  fallbackKind?: (item: T) => { id: string; label: string },
): { id: string; label: string; items: T[] }[] {
  const groups: { id: string; label: string; items: T[] }[] = [];
  for (const item of items) {
    const id = item.group || fallbackKind?.(item).id || "other";
    const label = item.group_label || fallbackKind?.(item).label || "其他";
    const last = groups[groups.length - 1];
    if (last && last.id === id) last.items.push(item);
    else groups.push({ id, label, items: [item] });
  }
  return groups;
}

function SeqRow({ seq }: { seq: SpriteSequence }) {
  const outside = Object.values(seq.outside).some(Boolean);
  const lastWindow = seq.last_hit ? speedWindowLabel(seq.last_hit) : null;
  return (
    <details className="border-b border-border/40 py-2 last:border-0">
      <summary className="flex cursor-pointer list-none flex-wrap items-baseline justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <span className="text-sm">{seq.name}</span>
          {!seq.monitored && <span className="ml-1.5 text-[10px] text-muted-foreground">未监控</span>}
          {outside && <span className="ml-1.5 text-[10px] text-warning">阈外</span>}
        </div>
        <span className="font-mono text-sm tabular-nums">{fmtSpriteValue(seq.current, seq.unit)}</span>
      </summary>
      <div className="mt-2 grid gap-2 text-[12px] sm:grid-cols-2 lg:grid-cols-3">
        <div>开盘记录 {fmtSpriteValue(seq.open, seq.unit)}{seq.open_ts ? ` · ${seq.open_ts.replace("T", " ")}` : ""}</div>
        <div>相对开盘 {fmtSpriteValue(seq.vs_open, seq.unit)}</div>
        <div>5 分钟差 {fmtSpriteValue(seq.speed, seq.unit)}</div>
        <div>上速 / 下速 {fmtSpriteValue(seq.thresholds.speed_up, seq.unit)} / {fmtSpriteValue(seq.thresholds.speed_down, seq.unit)}</div>
        <div>突破 / 跌破 {fmtSpriteValue(seq.thresholds.break_up, seq.unit)} / {fmtSpriteValue(seq.thresholds.break_down, seq.unit)}</div>
        <div>回差 {fmtSpriteValue(seq.thresholds.hysteresis, seq.unit)}</div>
      </div>
      {seq.last_hit && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          最近命中：{seq.last_hit.event_label} {fmtSpriteValue(seq.last_hit.value, seq.last_hit.unit)}
          {lastWindow ? `（${lastWindow}）` : ""}
        </p>
      )}
      {seq.samples.length > 0 && (
        <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground/80">
          采样 {seq.samples.map((s) => `${fmtSampleTs(s.ts)} ${fmtSpriteValue(s.value, seq.unit)}`).join(" · ")}
        </p>
      )}
    </details>
  );
}

export function ShortSprite() {
  const [snap, setSnap] = useState<ShortSpriteSnapshot | null>(null);
  const [session, setSession] = useState<MarketSession | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [enabling, setEnabling] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setErr("");
    try {
      const [out, sess] = await Promise.all([
        fetchShortSprite(),
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
    if (!liveNow) return;
    let cancelled = false;
    let timer = 0;
    const arm = () => {
      timer = window.setTimeout(() => {
        if (cancelled) return;
        void load().finally(() => { if (!cancelled) arm(); });
      }, delayUntilNextUnixSlot());
    };
    arm();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [liveNow, load]);

  const toggle = async (next: boolean) => {
    setEnabling(true);
    try {
      const out = await setShortSpriteEnabled(next);
      setSnap(out);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "启停失败");
    } finally {
      setEnabling(false);
    }
  };

  const seqGroups = useMemo(
    () => groupByLabel(snap?.sequences ?? [], (s) => (
      s.kind === "board" ? { id: "market", label: "盘面" } : { id: "style", label: "短线风格" }
    )),
    [snap],
  );
  const hitsNewestFirst = useMemo(() => [...(snap?.hits ?? [])].reverse(), [snap]);

  return (
    <div>
      <PageHeader
        title="短线精灵"
        subtitle={`${session?.label ?? snap?.date ?? "—"} · 市场级涨速 / 突破 / 跌破，不是荐股`}
        actions={
          <div className="flex items-center gap-2">
            <EnableButton enabled={!!snap?.enabled} busy={enabling} onToggle={(v) => void toggle(v)} />
            <SectionPopupButton
              path="/popout/short-sprite"
              windowName="va-popout-short-sprite"
              label="命中弹窗"
              title="独立窗口看命中流水并语音"
            />
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-primary"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              刷新
            </button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-baseline gap-2 text-sm text-muted-foreground">
        <Zap className="h-4 w-4" />
        <span>
          {snap?.enabled ? (snap.can_detect ? "随盘检测" : "已开但非随盘，不检测") : "已停止（命中仍保留）"}
          {snap?.date ? ` · ${snap.date}` : ""}
        </span>
        <Link to={keywordsSettingsTo("short-sprite")} className="text-primary/80 hover:text-primary">
          自定义配置
        </Link>
        <Caliber text={CALIBER} />
      </div>

      {err && <p className="mb-4 text-sm text-warning">{err}</p>}

      <p className="mb-4 text-xs text-muted-foreground">{snap?.disclaimer}</p>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <GlassCard className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">序列</h3>
          {seqGroups.map((g, i) => (
            <div key={g.id}>
              <h4 className={cn("mb-1 text-[11px] text-muted-foreground", i > 0 && "mt-3")}>{g.label}</h4>
              {g.items.map((s) => <SeqRow key={s.id} seq={s} />)}
            </div>
          ))}
          {seqGroups.length === 0 && <p className="text-sm text-muted-foreground">暂无报价项</p>}
        </GlassCard>
        <GlassCard className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-muted-foreground">本场次命中</h3>
          <SpriteHitList hits={hitsNewestFirst} />
        </GlassCard>
      </div>

      <Disclaimer />
    </div>
  );
}
