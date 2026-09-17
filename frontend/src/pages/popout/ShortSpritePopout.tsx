import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Zap } from "lucide-react";
import { PopupShell } from "@/components/PopupShell";
import { cn } from "@/lib/utils";
import { keywordsSettingsTo } from "@/lib/settingsNav";
import { delayUntilNextUnixSlot } from "@/lib/wallClock";
import { speakTexts, stopSpeech } from "@/lib/speech";
import {
  fetchShortSprite,
  setShortSpriteEnabled,
  type ShortSpriteSnapshot,
} from "@/lib/shortSprite";
import { SpriteHitList } from "@/pages/ShortSprite";
import { fetchMarketSession, type MarketSession } from "@/lib/liveBoard";

/** 短线精灵命中弹窗：只有这里播报。 */
export function ShortSpritePopout() {
  const [snap, setSnap] = useState<ShortSpriteSnapshot | null>(null);
  const [session, setSession] = useState<MarketSession | null>(null);
  const [err, setErr] = useState("");
  const [enabling, setEnabling] = useState(false);
  const spokenRef = useRef<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const [out, sess] = await Promise.all([
        fetchShortSprite(),
        fetchMarketSession().catch(() => null),
      ]);
      setSnap(out);
      if (sess) setSession(sess);
      setErr("");
      const toSpeak = (out.new_hits || []).filter((h) => h.voice && h.speech && !spokenRef.current.has(h.id));
      for (const h of toSpeak) spokenRef.current.add(h.id);
      if (toSpeak.length) {
        speakTexts(toSpeak.map((h) => h.speech));
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
    return () => stopSpeech();
  }, [load]);

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

  const hitsNewestFirst = useMemo(() => [...(snap?.hits ?? [])].reverse(), [snap]);

  return (
    <PopupShell title="短线精灵" bodyClassName="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void toggle(!(snap?.enabled))}
          disabled={enabling}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm disabled:opacity-50",
            snap?.enabled ? "bg-primary/15 text-primary" : "text-muted-foreground",
          )}
        >
          {enabling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
          {snap?.enabled ? "运行中" : "已停止"}
        </button>
        <Link to="/short-sprite" target="_blank" rel="noreferrer" className="text-xs text-primary/80 hover:text-primary">
          详情
        </Link>
        <Link
          to={keywordsSettingsTo("short-sprite")}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-primary/80 hover:text-primary"
        >
          自定义配置
        </Link>
      </div>
      {err && <p className="mb-2 text-xs text-warning">{err}</p>}
      <p className="mb-2 text-[11px] text-muted-foreground">
        {snap?.disclaimer || "命中是观察记录，不是买卖指令。"}
      </p>
      <SpriteHitList hits={hitsNewestFirst} />
    </PopupShell>
  );
}
