import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
  formatRankDelta,
  formatStyleDelta,
  formatStylePct,
  formatZscore,
  type StyleIndexGroup,
  type StyleIndexItem,
  type StyleIndicesSnapshot,
  type StylePreference,
  type StyleRotation,
} from "@/lib/styleIndices";
import { delayUntilNextUnixSlot } from "@/lib/wallClock";
import { pingShortSprite } from "@/lib/shortSprite";
import { SectionPopupButton } from "@/components/SectionPopupButton";

const CUM_EXCESS_GROUPS = new Set([
  "board", "size", "attribute", "growth_value", "dividend", "finance", "sector", "other",
]);

const CALIBER =
  "当场涨幅，对比前一交易日收盘。风格/行业板块走东财概念与行业列表，宽基与外围走东财 ulist，缺了再用腾讯指数补。当场涨幅不是风格轮动。\n" +
  "「昨日涨停表现」对应东财「昨日涨停_含一字」，不是赚钱效应中位数，也不是打板情绪。\n" +
  "风格偏好是当场派生：超额 = 当场涨幅 − 中证全指。只钉中证全指；缺中证全指时不报超额、风格热点、打板风格组同号，组内涨幅排序、大小盘价差、组内领涨仍可报。\n" +
  "大小盘价差 = 东财小盘股 − 大盘股；国证2000 − 沪深300 只作对照，不叫大小盘价差。微盘不改写大小盘价差。\n" +
  "打板风格组均值只含昨日涨停/连板/首板/炸板及一字、打二板变体，不含高换手、高振幅、触板。有效项少于 4 条为不足；组均值或中证全指绝对值小于 0.1% 为近平。\n" +
  "风格热点来自打板风格、市值风格、短线属性、风格类型、红利、金融、行业指数、其他，按超额前 5 再滤上涨占比；宽基与外围不参赛。有涨跌家数且涨幅符号与上涨占比 0.5 反侧时标价升面窄或价跌面宽。\n" +
  "风格轮动是相邻已定稿场次之间风格偏好的排序或超额位次变化。本场未定稿时对照最近两场已定稿，对照日期写在摘要上，不拿随盘当本场。缺上场存档则为不足，缺日不插值，不跳过中间场次。\n" +
  "涨幅差 = 本场定稿涨幅 − 上场已定稿涨幅，这里的上场涨幅是昨场涨幅，不是相对昨收。超额位次只在风格热点同一套候选上排，名次上升为正。\n" +
  "Spearman 是这两场超额位次向量的相关，相关低只表示换得快。z-score 用该 key 近 N=10 个已定稿涨幅（不含本场）的均值与标准差；累计超额同窗、只在候选集上相对中证全指。收盘新高/新低相对近 N=20 个已定稿收盘价，只报宽基、红利官方指数、国证2000、国证成长/价值、行业指数；收盘新高不是突破。未定稿本场不进入 z 窗或这 20 场。\n" +
  "同花顺专有指数（情绪 / 全A / 热股 / 平均股价 / 短期期货恐慌 / 高贝塔 / 高股息精选）公开源没有，页底列出未接入。中证全指、东财热股、中证红利只是公开近似，名字没有写成同花顺那条。\n" +
  "报价是延时行情。随盘场次按 Unix 20 秒墙钟槽刷新缓存。";

function breadth(up: number | null, down: number | null): string | null {
  if (up == null || down == null) return null;
  if (up === 0 && down === 0) return null;
  return `↑${up} ↓${down}`;
}

function itemByKey(groups: StyleIndexGroup[]): Map<string, StyleIndexItem> {
  const map = new Map<string, StyleIndexItem>();
  for (const g of groups) {
    for (const it of g.items) map.set(it.key, it);
  }
  return map;
}

function Tag({ children, className }: { children: string; className: string }) {
  return (
    <span className={cn("ml-1.5 inline-flex shrink-0 rounded px-1 py-0.5 text-[10px] font-medium", className)}>
      {children}
    </span>
  );
}

function GroupCard({
  group, hotspotKeys, leadKey,
}: {
  group: StyleIndexGroup;
  hotspotKeys: Set<string>;
  leadKey: string | undefined;
}) {
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
              <div className="flex flex-wrap items-baseline">
                <span className="truncate text-sm">{it.name}</span>
                {hotspotKeys.has(it.key) && (
                  <Tag className="bg-danger/15 text-danger">热点</Tag>
                )}
                {!hotspotKeys.has(it.key) && leadKey === it.key && (
                  <Tag className="bg-primary/15 text-primary">组内领涨</Tag>
                )}
                {it.width_flag && (
                  <Tag className="bg-warning/15 text-warning">{it.width_flag}</Tag>
                )}
              </div>
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
              <div className="mt-0.5 max-w-[11rem] text-right text-[10px] leading-tight text-muted-foreground/70">
                <div>上场已定稿涨幅差 {formatStyleDelta(it.change_pct_delta)}</div>
                <div>超额位次 {formatRankDelta(it.excess_rank_delta)}</div>
                <div>z（N=10）{formatZscore(it.zscore)}</div>
                {CUM_EXCESS_GROUPS.has(it.group) && it.key !== "csi_all" && (
                  <div>累计超额（N=10）{it.cum_excess == null ? "不足" : formatStylePct(it.cum_excess)}</div>
                )}
                {it.close_extreme != null && (
                  <div>近 20 场收盘 {it.close_extreme}</div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function RotationSummary({
  rot, names,
}: {
  rot: StyleRotation;
  names: Map<string, StyleIndexItem>;
}) {
  const against = rot.against?.date;
  const thisDate = rot.this?.date;
  const label = (key: string) => names.get(key)?.name ?? key;

  return (
    <GlassCard className="mb-4 p-4">
      <h3 className="text-sm font-semibold text-muted-foreground">风格轮动</h3>
      {rot.live_deferred && thisDate && against && (
        <p className="mt-1 text-[12px] text-warning">
          本场尚未定稿。下面是 {thisDate} 相对 {against} 已定稿场次，对照日期已写明，不是本场随盘。
        </p>
      )}
      {rot.status === "absent" ? (
        <p className="mt-1 text-sm text-muted-foreground">不足：没有两场相邻已定稿存档可对。</p>
      ) : (
        <div className="mt-3 grid gap-4 sm:grid-cols-3">
          <div>
            <div className="text-[11px] text-muted-foreground">对照日期</div>
            <p className="mt-1 text-sm">{against ?? "不足"}</p>
            {thisDate && (
              <p className="text-[10px] text-muted-foreground/70">本场定稿 {thisDate}</p>
            )}
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">风格热点进入 / 离开</div>
            {rot.status === "partial" ? (
              <p className="mt-1 text-sm text-muted-foreground">热点不能比</p>
            ) : (
              <div className="mt-1 space-y-1 text-sm">
                <p>
                  进入：{rot.hotspot_enter.length ? rot.hotspot_enter.map(label).join("、") : "无"}
                </p>
                <p>
                  离开：{rot.hotspot_leave.length ? rot.hotspot_leave.map(label).join("、") : "无"}
                </p>
              </div>
            )}
          </div>
          <div>
            <div className="text-[11px] text-muted-foreground">Spearman</div>
            <div className="mt-1 text-lg font-semibold">
              {rot.spearman.status === "ok" && rot.spearman.value != null
                ? rot.spearman.value.toFixed(2)
                : "不足"}
            </div>
            <p className="text-[10px] text-muted-foreground/70">
              {rot.spearman.n} 项重叠 · 相关低只表示换得快
            </p>
          </div>
        </div>
      )}
    </GlassCard>
  );
}

function PreferenceSummary({
  pref, names,
}: {
  pref: StylePreference;
  names: Map<string, StyleIndexItem>;
}) {
  if (pref.status === "absent") {
    return (
      <GlassCard className="mb-4 p-4">
        <h3 className="text-sm font-semibold text-muted-foreground">风格偏好</h3>
        <p className="mt-1 text-sm text-muted-foreground">风格指数尚未取到，偏好不足。</p>
      </GlassCard>
    );
  }

  const hotspots = pref.status === "ok" ? pref.hotspots : [];
  const spreadOk = pref.size_spread.status === "ok";
  const cnSpread = pref.size_spread_cnindex.value;
  const board = pref.board_group;

  return (
    <GlassCard className="mb-4 p-4">
      <h3 className="mb-3 text-sm font-semibold text-muted-foreground">风格偏好</h3>
      {pref.status === "partial" && (
        <p className="mb-3 text-[12px] text-warning">
          中证全指缺报价：不报超额、风格热点、打板风格组同号。组内涨幅排序、大小盘价差、组内领涨仍可看。
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <div className="text-[11px] text-muted-foreground">风格热点</div>
          {pref.status !== "ok" ? (
            <p className="mt-1 text-sm text-muted-foreground">缺中证全指，不报</p>
          ) : hotspots.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">无</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-sm">
              {hotspots.map((h) => (
                <li key={h.key} className="flex items-baseline justify-between gap-2">
                  <span className="truncate">{names.get(h.key)?.name ?? h.key}</span>
                  <span className={cn("shrink-0 font-mono tabular-nums", pctColor(h.excess))}>
                    {formatStylePct(h.excess)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">大小盘价差</div>
          <div className={cn("mt-1 font-mono text-lg font-bold tabular-nums", spreadOk ? pctColor(pref.size_spread.value) : "text-muted-foreground")}>
            {spreadOk ? formatStylePct(pref.size_spread.value) : "不足"}
          </div>
          <p className="text-[10px] text-muted-foreground/70">东财小盘 − 大盘</p>
          {cnSpread != null && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              国证2000 − 沪深300
              <span className={cn("ml-1.5 font-mono tabular-nums", pctColor(cnSpread))}>{formatStylePct(cnSpread)}</span>
            </p>
          )}
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">打板风格组</div>
          <div className="mt-1 text-lg font-semibold">{board.vs}</div>
          {board.mean != null && (
            <p className={cn("font-mono text-sm tabular-nums", pctColor(board.mean))}>
              均值 {formatStylePct(board.mean)}
            </p>
          )}
          <p className="text-[10px] text-muted-foreground/70">有效 {board.n_valid} 项 · 相对中证全指</p>
        </div>
      </div>
    </GlassCard>
  );
}

function rotationContext(snap: StyleIndicesSnapshot): string {
  const rot = snap.rotation;
  const names = itemByKey(snap.groups);
  const label = (key: string) => names.get(key)?.name ?? key;
  const against = rot?.against?.date ?? "无";
  const thisDate = rot?.this?.date ?? "无";
  const deferred = rot?.live_deferred
    ? `本场未定稿，对照日期为 ${thisDate} 相对 ${against}，不是本场随盘。`
    : `对照日期 ${against}（本场定稿 ${thisDate}）。`;
  const statusLine = !rot || rot.status === "absent"
    ? "风格轮动：不足（没有两场相邻已定稿存档可对）。"
    : `风格轮动（${rot.status === "ok" ? "完整" : "部分不足"}）。`;
  const enter = rot?.status === "ok"
    ? (rot.hotspot_enter.length ? rot.hotspot_enter.map(label).join("，") : "无")
    : "不足";
  const leave = rot?.status === "ok"
    ? (rot.hotspot_leave.length ? rot.hotspot_leave.map(label).join("，") : "无")
    : "不足";
  const rho = rot?.spearman.status === "ok" && rot.spearman.value != null
    ? String(rot.spearman.value)
    : "不足";
  const nOverlap = rot?.spearman.n ?? 0;
  const ranked = snap.groups.flatMap((g) => g.items)
    .filter((it) => it.excess_rank_delta != null || it.change_pct_delta != null)
    .slice(0, 12)
    .map((it) => `${it.name} 涨幅差 ${formatStyleDelta(it.change_pct_delta)} 位次 ${formatRankDelta(it.excess_rank_delta)}`)
    .join("；") || "不足";
  const zBits = snap.groups.flatMap((g) => g.items)
    .filter((it) => it.zscore != null)
    .slice(0, 8)
    .map((it) => `${it.name} z=${formatZscore(it.zscore)}`)
    .join("，") || "不足";
  const hi = snap.groups.flatMap((g) => g.items)
    .filter((it) => it.close_extreme && it.close_extreme !== "都不是" && it.close_extreme !== "不足")
    .map((it) => `${it.name}${it.close_extreme}`)
    .join("，") || "不足";
  return [
    `${statusLine}${rot && rot.status !== "absent" ? deferred : `对照日期 ${against}。`}`,
    `风格热点进入：${enter}。离开：${leave}。`,
    `超额位次与涨幅差摘要：${ranked}。`,
    `Spearman：${rho}（${nOverlap} 项）。`,
    `z-score（N=10，不含本场）：${zBits}。`,
    `收盘新高/新低（N=20）：${hi}。`,
  ].join("\n");
}

function preferenceContext(snap: StyleIndicesSnapshot): string {
  const pref = snap.preference;
  const names = itemByKey(snap.groups);
  if (!pref || pref.status === "absent") {
    return "风格偏好：不足（风格指数尚未取到）。";
  }
  const hot = pref.status === "ok"
    ? (pref.hotspots.length
      ? pref.hotspots.map((h) => `${names.get(h.key)?.name ?? h.key} 超额 ${formatStylePct(h.excess)}`).join("，")
      : "无")
    : "缺中证全指，不报";
  const spread = pref.size_spread.status === "ok"
    ? formatStylePct(pref.size_spread.value)
    : "不足";
  const cn = pref.size_spread_cnindex.value;
  const cnLine = cn == null ? "不展示" : formatStylePct(cn);
  const board = pref.board_group;
  const mean = board.mean == null ? "" : `，均值 ${formatStylePct(board.mean)}`;
  return [
    `风格偏好（${pref.status === "ok" ? "完整" : "中证全指缺报价"}）。`,
    `风格热点：${hot}。`,
    `大小盘价差（东财小盘 − 大盘）：${spread}。`,
    `国证2000 − 沪深300 对照：${cnLine}。`,
    `打板风格组相对中证全指：${board.vs}${mean}，有效 ${board.n_valid} 项。`,
  ].join("\n");
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
      await pingShortSprite();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "加载失败");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const liveNow = session?.phase === "盘中" || session?.phase === "集合竞价";
  useEffect(() => {
    if (!autoRefresh) return;
    let cancelled = false;
    let timer = 0;
    const arm = () => {
      timer = window.setTimeout(() => {
        if (cancelled) return;
        // 盘前也要续问场次，否则凌晨打开会一直停在「非交易时段暂停」，开盘后不再刷。
        const task = liveNow
          ? load()
          : fetchMarketSession().then((s) => {
              if (!s) return;
              setSession(s);
              const live = s.phase === "盘中" || s.phase === "集合竞价";
              if (live) void load();
            }).catch(() => {});
        void Promise.resolve(task).finally(() => { if (!cancelled) arm(); });
      }, delayUntilNextUnixSlot());
    };
    arm();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [autoRefresh, liveNow, load]);

  const names = useMemo(() => itemByKey(snap?.groups ?? []), [snap]);
  const hotspotKeys = useMemo(
    () => new Set((snap?.preference?.status === "ok" ? snap.preference.hotspots : []).map((h) => h.key)),
    [snap],
  );
  const leadByGroup = useMemo(() => {
    const map = new Map<string, string>();
    for (const lead of snap?.preference?.group_leads ?? []) {
      map.set(lead.group, lead.key);
    }
    return map;
  }, [snap]);

  const context = useMemo(() => {
    if (!snap?.groups?.length) return "短线风格指数尚未取到。";
    const lines = snap.groups.map((g) => {
      const body = g.items
        .map((it) => `${it.name} ${formatStylePct(it.change_pct)}`)
        .join("，");
      return `${g.label}：${body}`;
    });
    return `${snap.date} 短线风格指数（${snap.is_live ? "随盘" : "定稿"}，${snap.hit}/${snap.total} 有报价）。\n${rotationContext(snap)}\n${preferenceContext(snap)}\n${lines.join("\n")}`;
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
              title={autoRefresh ? "已开：盘中按 20 秒墙钟槽刷新" : "开启后在交易时段自动刷新"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm transition-colors",
                autoRefresh
                  ? "bg-primary/15 text-primary hover:bg-primary/25"
                  : "text-muted-foreground hover:text-primary",
              )}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", autoRefresh && liveNow && "animate-spin")} />
              {autoRefresh ? (liveNow ? "每 20 秒" : "自动刷新（非交易时段暂停）") : "自动刷新"}
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
              suggestions={["风格热点是哪些", "大小盘价差怎么读", "打板风格组和中证全指是否同向", "风格热点谁进入谁离开"]}
            />
            <Link
              to="/short-sprite"
              target="_blank"
              rel="noreferrer"
              className="text-sm text-primary/80 hover:text-primary"
            >
              短线精灵
            </Link>
            <SectionPopupButton
              compact
              path="/popout/short-sprite"
              windowName="va-popout-short-sprite"
              title="短线精灵命中弹窗"
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
        <RotationSummary
          rot={snap.rotation ?? {
            status: "absent",
            this: null,
            against: null,
            live_deferred: Boolean(snap.is_live),
            hotspot_enter: [],
            hotspot_leave: [],
            spearman: { value: null, n: 0, status: "不足" },
            z_n: 10,
            close_n: 20,
          }}
          names={names}
        />
      )}

      {snap?.preference && (
        <PreferenceSummary pref={snap.preference} names={names} />
      )}

      {snap && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {snap.groups.map((g) => (
            <GroupCard
              key={g.id}
              group={g}
              hotspotKeys={hotspotKeys}
              leadKey={leadByGroup.get(g.id)}
            />
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
