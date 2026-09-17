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
  "短线精灵只盯短线盘面、短线风格已有快照里的市场级序列：溢价、环境条上涨数/下跌数、情绪温度、情绪分、打板情绪共振默认分、短线风格指数当场涨幅。\n" +
  "不盯个股，不盯人气榜/成交额榜/板块管理。命中是观察记录，不是买卖指令。\n" +
  "开盘记录 = 该场次 09:30 之后第一条非空随盘快照。涨速 = 当前值 − 约 5 分钟前的值（点不足则空）。突破/跌破是相对开盘记录的差穿过阈值边沿。\n" +
  "上涨数/下跌数用环境条随盘家数，不是市场整体卡片上的 overview 家数。下跌数升高为绿。";

export function hitDirClass(hit: Pick<SpriteHit, "direction" | "reversed">): string {
  const up = hit.direction === "up";
  const showUp = hit.reversed ? !up : up;
  return showUp ? UP_TEXT : DOWN_TEXT;
}

export function hitEventClass(label: string): string {
  if (label === "涨速") return "border-l-primary bg-primary/5";
  if (label === "突破") return "border-l-warning bg-warning/5";
  return "border-l-muted-foreground bg-muted/30";
}

export function SpriteHitList({ hits, empty }: { hits: SpriteHit[]; empty?: string }) {
  if (!hits.length) {
    return <p className="text-sm text-muted-foreground">{empty || "本场次还没有命中。"}</p>;
  }
  return (
    <ul className="space-y-1.5">
      {hits.map((h) => (
        <li
          key={h.id}
          className={cn("rounded-md border border-border/50 border-l-4 px-3 py-2", hitEventClass(h.event_label))}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-sm">
              {h.name}
              <span className="ml-2 text-[11px] text-muted-foreground">{h.event_label}</span>
            </span>
            <span className={cn("font-mono text-sm tabular-nums", hitDirClass(h))}>
              {fmtSpriteValue(h.value, h.unit)}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {h.ts.replace("T", " ")}
            {h.voice ? "" : " · 静音"}
          </div>
        </li>
      ))}
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

function SeqRow({ seq }: { seq: SpriteSequence }) {
  const outside = Object.values(seq.outside).some(Boolean);
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

  const boardSeqs = useMemo(() => (snap?.sequences ?? []).filter((s) => s.kind === "board"), [snap]);
  const styleSeqs = useMemo(() => (snap?.sequences ?? []).filter((s) => s.kind === "style"), [snap]);
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
          <h4 className="mb-1 text-[11px] text-muted-foreground">盘面</h4>
          {boardSeqs.map((s) => <SeqRow key={s.id} seq={s} />)}
          <h4 className="mb-1 mt-3 text-[11px] text-muted-foreground">短线风格指数</h4>
          {styleSeqs.length === 0
            ? <p className="text-sm text-muted-foreground">暂无报价项</p>
            : styleSeqs.map((s) => <SeqRow key={s.id} seq={s} />)}
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
