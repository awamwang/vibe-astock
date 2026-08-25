import { useEffect, useState } from "react";
import { Plus, RotateCcw, Tags, Trash2, Lock, ArrowRight, GitMerge, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  addZtKeyword, removeZtKeyword, setZtKeywordsCache,
  LOCKED_ZT_KEYWORDS,
} from "@/lib/zt-keywords";
import { api, type ThemeAliasEntry, type TradePhaseConfigRow, type SentimentSConfig } from "@/lib/api";

function sortAliasEntries(entries: ThemeAliasEntry[]): ThemeAliasEntry[] {
  return [...entries].sort((a, b) => {
    const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
    if (byCanonical !== 0) return byCanonical;
    return a.alias.localeCompare(b.alias, "zh-CN");
  });
}

function entriesFromAliases(aliases: Record<string, string>): ThemeAliasEntry[] {
  return sortAliasEntries(
    Object.entries(aliases).map(([alias, canonical]) => ({ alias, canonical })),
  );
}

type PhaseDraft = {
  phase: string;
  capTotalPct: string;
  capSinglePct: string;
  prompt: string;
};

function ratioToPctStr(v: number): string {
  const n = Math.round((Number(v) || 0) * 10000) / 100;
  return String(n);
}

function draftsFromRows(rows: TradePhaseConfigRow[]): PhaseDraft[] {
  return rows.map((row) => ({
    phase: row.phase,
    capTotalPct: ratioToPctStr(row.cap_total),
    capSinglePct: ratioToPctStr(row.cap_single),
    prompt: row.prompt || "",
  }));
}

function parsePct(raw: string, label: string): number {
  const n = Number(String(raw).trim());
  if (!Number.isFinite(n) || n < 0 || n > 100) {
    throw new Error(`${label}须为 0–100 的数字`);
  }
  return Math.round(n * 100) / 10000;
}

export function ZtKeywordsSettings() {
  const [tags, setTags] = useState<string[]>([]);
  const [tagsLoading, setTagsLoading] = useState(true);
  const [tagsSaving, setTagsSaving] = useState(false);
  const [draft, setDraft] = useState("");

  const [aliasEntries, setAliasEntries] = useState<ThemeAliasEntry[]>([]);
  const [aliasLoading, setAliasLoading] = useState(true);
  const [aliasDraft, setAliasDraft] = useState({ alias: "", canonical: "" });
  const [aliasSaving, setAliasSaving] = useState(false);

  const [phaseDrafts, setPhaseDrafts] = useState<PhaseDraft[]>([]);
  const [phaseLoading, setPhaseLoading] = useState(true);
  const [phaseSaving, setPhaseSaving] = useState(false);

  const [sCfg, setSCfg] = useState<SentimentSConfig | null>(null);
  const [sMethod, setSMethod] = useState("hard_rules");
  const [sLoading, setSLoading] = useState(true);
  const [sSaving, setSSaving] = useState(false);
  const [sRefreshing, setSRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.ztKeywords();
        if (!cancelled) {
          const kw = setZtKeywordsCache(cfg.keywords || []);
          setTags(kw);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取上涨关键词失败");
        }
      } finally {
        if (!cancelled) setTagsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.themeAliases();
        if (!cancelled) setAliasEntries(entriesFromAliases(cfg.aliases || {}));
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取题材别名失败");
        }
      } finally {
        if (!cancelled) setAliasLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.tradePhaseConfig();
        if (!cancelled) setPhaseDrafts(draftsFromRows(cfg.phases || []));
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取仓位档位配置失败");
        }
      } finally {
        if (!cancelled) setPhaseLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.sentimentSConfig();
        if (!cancelled) {
          setSCfg(cfg);
          // 界面已隐藏 FusionIntel，若历史配置仍是该算法则回落到硬规则供重选
          const method = cfg.method || "hard_rules";
          setSMethod(method === "fusionintel" ? "hard_rules" : method);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取情绪分 S 配置失败");
        }
      } finally {
        if (!cancelled) setSLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const persistSentimentS = async () => {
    setSSaving(true);
    try {
      const cfg = await api.saveSentimentSConfig(sMethod);
      setSCfg(cfg);
      setSMethod(cfg.method === "fusionintel" ? "hard_rules" : cfg.method);
      toast.success("情绪分算法已保存；请到「持仓与预算」重算场次");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSSaving(false);
    }
  };

  const refreshSentimentSeries = async () => {
    setSRefreshing(true);
    try {
      const r = await api.refreshSentimentSSeries(30);
      const cfg = await api.sentimentSConfig();
      setSCfg(cfg);
      const mr = r.market_refresh;
      const marketHint = mr?.skipped
        ? "两融/指数已是最新"
        : mr?.ok
          ? `两融/指数已更新（两融 ${mr.margin?.days ?? "?"} 日）`
          : "两融/指数未更新（可稍后重试）";
      toast.success(
        `序列已更新：${r.meta.days} 日，本轮补东财 ${r.enriched_this_run} 日`
        + (r.missed_this_run ? `（窗口外跳过 ${r.missed_this_run}）` : "")
        + (r.qcj_highest_filled ? `，趣财经补高度 ${r.qcj_highest_filled} 日` : "")
        + `（已补全 ${r.meta.enriched_days}） · ${marketHint}`,
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "刷新序列失败");
    } finally {
      setSRefreshing(false);
    }
  };

  const persistKeywords = async (next: string[]) => {
    setTagsSaving(true);
    try {
      const r = await api.saveZtKeywords(next);
      const kw = setZtKeywordsCache(r.keywords);
      setTags(kw);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setTagsSaving(false);
    }
  };

  const persistAliases = async (next: ThemeAliasEntry[]) => {
    const aliases = Object.fromEntries(next.map((e) => [e.alias, e.canonical]));
    setAliasSaving(true);
    try {
      const r = await api.saveThemeAliases(aliases);
      setAliasEntries(entriesFromAliases(r.aliases));
      toast.success("题材别名已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setAliasSaving(false);
    }
  };

  const addKeyword = async () => {
    const label = draft.replace(/\s+/g, "").trim();
    const r = addZtKeyword(tags, draft);
    if (!r.ok) {
      toast.error(r.reason || "添加失败");
      return;
    }
    setDraft("");
    await persistKeywords(r.next);
    toast.success(`已添加「${label}」`);
  };

  const removeKeyword = async (tag: string) => {
    const r = removeZtKeyword(tags, tag);
    if (!r.ok) {
      toast.error(r.reason || "删除失败");
      return;
    }
    await persistKeywords(r.next);
    toast.success(`已移除「${tag}」`);
  };

  const resetKeywords = async () => {
    setTagsSaving(true);
    try {
      const r = await api.resetZtKeywords();
      const kw = setZtKeywordsCache(r.keywords);
      setTags(kw);
      toast.success("已恢复默认上涨关键词列表");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setTagsSaving(false);
    }
  };

  const addAlias = async () => {
    const alias = aliasDraft.alias.replace(/\s+/g, "").trim();
    const canonical = aliasDraft.canonical.replace(/\s+/g, "").trim();
    if (!alias || !canonical) {
      toast.error("请填写别名与标准题材");
      return;
    }
    if (alias.length > 20 || canonical.length > 20) {
      toast.error("题材名不超过 20 个字");
      return;
    }
    if (alias === canonical) {
      toast.error("别名与标准题材不能相同");
      return;
    }
    if (aliasEntries.some((e) => e.alias === alias)) {
      toast.error("该别名已存在");
      return;
    }
    const next = sortAliasEntries([...aliasEntries, { alias, canonical }]);
    setAliasDraft({ alias: "", canonical: "" });
    await persistAliases(next);
  };

  const removeAlias = async (alias: string) => {
    const next = aliasEntries.filter((e) => e.alias !== alias);
    await persistAliases(next);
  };

  const updatePhaseDraft = (phase: string, patch: Partial<PhaseDraft>) => {
    setPhaseDrafts((rows) => rows.map((row) => (row.phase === phase ? { ...row, ...patch } : row)));
  };

  const persistPhases = async () => {
    let payload: TradePhaseConfigRow[];
    try {
      payload = phaseDrafts.map((row) => ({
        phase: row.phase,
        cap_total: parsePct(row.capTotalPct, `${row.phase} 整体仓位`),
        cap_single: parsePct(row.capSinglePct, `${row.phase} 单独仓位`),
        prompt: row.prompt.trim(),
      }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "仓位数字不合法");
      return;
    }
    setPhaseSaving(true);
    try {
      const r = await api.saveTradePhaseConfig(payload);
      setPhaseDrafts(draftsFromRows(r.phases || payload));
      toast.success("仓位档位已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setPhaseSaving(false);
    }
  };

  const resetPhases = async () => {
    setPhaseSaving(true);
    try {
      const r = await api.resetTradePhaseConfig();
      setPhaseDrafts(draftsFromRows(r.phases || []));
      toast.success("已恢复默认仓位档位");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setPhaseSaving(false);
    }
  };

  const resetAliases = async () => {
    setAliasSaving(true);
    try {
      const r = await api.resetThemeAliases();
      setAliasEntries(entriesFromAliases(r.aliases));
      toast.success("已恢复默认题材别名");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setAliasSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="自定义配置"
        subtitle="上涨关键词、题材别名，以及仓位预算六档的总仓、单票与提示词"
      />

      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Tags className="h-4 w-4 text-primary" /> 上涨关键词
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          存于本机后端数据目录。深入分析时模型必须原样抄写其中一个标签；
          看不出明显原因用「无原因」，都不属于用「其他」。
        </p>

        {tagsLoading ? (
          <p className="text-xs text-muted-foreground">正在读取上涨关键词…</p>
        ) : (
          <div className="mb-4 flex flex-wrap gap-2">
            {tags.map((tag) => {
              const locked = LOCKED_ZT_KEYWORDS.includes(tag);
              return (
                <span
                  key={tag}
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium ${
                    locked
                      ? "border-border/60 bg-muted/40 text-muted-foreground"
                      : "border-primary/30 bg-primary/10 text-primary"
                  }`}
                >
                  {locked && <Lock className="h-3 w-3 opacity-70" />}
                  {tag}
                  {!locked && (
                    <button
                      type="button"
                      disabled={tagsSaving}
                      onClick={() => void removeKeyword(tag)}
                      className="rounded p-0.5 hover:bg-primary/20 hover:text-destructive disabled:opacity-50"
                      title={`删除「${tag}」`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addKeyword();
              }
            }}
            maxLength={10}
            placeholder="新标签，最多 10 字"
            disabled={tagsSaving || tagsLoading}
            className="min-w-[10rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void addKeyword()}
            disabled={tagsSaving || tagsLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
          <button
            type="button"
            onClick={() => void resetKeywords()}
            disabled={tagsSaving || tagsLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>

      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <GitMerge className="h-4 w-4 text-primary" /> 题材别名
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          存于本机后端数据目录。统计题材涨停数（题材事件树、多日情绪矩阵等）时，
          把左侧别名合并到右侧标准题材；只走显式映射，不做模糊或语义归类。
        </p>

        {aliasLoading ? (
          <p className="text-xs text-muted-foreground">正在读取题材别名…</p>
        ) : aliasEntries.length === 0 ? (
          <p className="mb-3 text-xs text-muted-foreground">暂无别名，可在下方添加。</p>
        ) : (
          <div className="mb-4 flex flex-wrap gap-2">
            {aliasEntries.map((row) => (
              <span
                key={row.alias}
                className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium"
              >
                <span className="text-foreground">{row.alias}</span>
                <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                <span className="text-primary">{row.canonical}</span>
                <button
                  type="button"
                  disabled={aliasSaving}
                  onClick={() => void removeAlias(row.alias)}
                  className="rounded p-0.5 text-muted-foreground hover:bg-primary/20 hover:text-destructive disabled:opacity-50"
                  title={`删除「${row.alias}」`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[8rem] flex-1">
            <label className="mb-1 block text-[11px] text-muted-foreground">别名（原始写法）</label>
            <input
              value={aliasDraft.alias}
              onChange={(e) => setAliasDraft((d) => ({ ...d, alias: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void addAlias();
                }
              }}
              maxLength={20}
              placeholder="如：中报预增"
              disabled={aliasSaving}
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
            />
          </div>
          <div className="min-w-[8rem] flex-1">
            <label className="mb-1 block text-[11px] text-muted-foreground">标准题材</label>
            <input
              value={aliasDraft.canonical}
              onChange={(e) => setAliasDraft((d) => ({ ...d, canonical: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void addAlias();
                }
              }}
              maxLength={20}
              placeholder="如：中报增长"
              disabled={aliasSaving}
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
            />
          </div>
          <button
            type="button"
            onClick={() => void addAlias()}
            disabled={aliasSaving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
          <button
            type="button"
            onClick={() => void resetAliases()}
            disabled={aliasSaving}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>

      <GlassCard>
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <SlidersHorizontal className="h-4 w-4 text-primary" /> 合成情绪分 S
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          使用什么数据作为六档情绪周期中的合成情绪指标
        </p>

        {sLoading || !sCfg ? (
          <p className="text-xs text-muted-foreground">正在读取情绪分配置…</p>
        ) : (
          <div className="space-y-3">
            <div className="space-y-2">
              {sCfg.methods
                .filter((m) => m.id !== "fusionintel")
                .map((m) => (
                <label
                  key={m.id}
                  className="flex cursor-pointer items-start gap-2 rounded-lg border border-border/60 px-3 py-2.5 hover:bg-muted/30"
                >
                  <input
                    type="radio"
                    name="sentiment-s-method"
                    className="mt-1"
                    checked={sMethod === m.id}
                    onChange={() => setSMethod(m.id)}
                    disabled={sSaving || sRefreshing}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-foreground">{m.label}</span>
                    <span className="mt-1 block text-[11px] leading-relaxed text-muted-foreground">
                      {m.desc}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">
              分位序列：{sCfg.series_meta.days} 日
              {sCfg.series_meta.first && sCfg.series_meta.last
                ? `（${sCfg.series_meta.first} → ${sCfg.series_meta.last}）`
                : ""}
              ，东财已补 {sCfg.series_meta.enriched_days} 日
              {typeof sCfg.series_meta.highest_days === "number"
                ? ` · 最高板 ${sCfg.series_meta.highest_days} 日`
                : ""}
              {typeof sCfg.series_meta.broken_rate_days === "number"
                ? ` · 炸板率 ${sCfg.series_meta.broken_rate_days} 日`
                : ""}
              {(sCfg.series_meta.miss_days ?? 0) > 0
                ? `（东财窗口外 ${sCfg.series_meta.miss_days} 日）`
                : ""}
              {(sCfg.series_meta.pending_days ?? 0) > 0
                ? `，待补 ${sCfg.series_meta.pending_days} 日`
                : ""}
              {sCfg.series_meta.updated_at ? ` · 更新于 ${sCfg.series_meta.updated_at}` : ""}
            </p>
            {sCfg.market_series && (
              <p className="text-[11px] text-muted-foreground">
                两融 {sCfg.market_series.margin.days} 日
                {sCfg.market_series.margin.last ? `（至 ${sCfg.market_series.margin.last}）` : ""}
                {" · "}
                上证 {sCfg.market_series.index.days} 日
                {sCfg.market_series.index.last ? `（至 ${sCfg.market_series.index.last}）` : ""}
                {sCfg.market_series.needs_refresh
                  ? ` · 启动后将自动补：${sCfg.market_series.needs_refresh}`
                  : " · 两融/指数缓存已就绪"}
              </p>
            )}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void persistSentimentS()}
            disabled={sSaving || sLoading || sRefreshing}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            保存算法
          </button>
          <button
            type="button"
            onClick={() => void refreshSentimentSeries()}
            disabled={sSaving || sLoading || sRefreshing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className={`h-4 w-4 ${sRefreshing ? "animate-spin" : ""}`} />
            {sRefreshing ? "刷新中…" : "刷新分位序列（每轮补 30 日东财）"}
          </button>
        </div>
      </GlassCard>

      <GlassCard>
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <SlidersHorizontal className="h-4 w-4 text-primary" /> 仓位预算档位
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          总仓、单票、提示词可分别改。未改时总仓用内置默认，单票为总仓一半。
          保存后对新计算的预算生效；已落盘场次请在「持仓与预算」刷新。
        </p>

        {phaseLoading ? (
          <p className="text-xs text-muted-foreground">正在读取仓位档位…</p>
        ) : (
          <div className="divide-y divide-border/60">
            {phaseDrafts.map((row) => (
              <div key={row.phase} className="py-3 first:pt-0 last:pb-0">
                <div className="mb-2 text-sm font-bold text-foreground">{row.phase}</div>
                <div className="mb-2 grid grid-cols-2 gap-2">
                  <label className="block text-[11px] text-muted-foreground">
                    整体仓位 %
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={row.capTotalPct}
                      onChange={(e) => updatePhaseDraft(row.phase, { capTotalPct: e.target.value })}
                      disabled={phaseSaving}
                      className="mt-1 w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm tabular-nums outline-none focus:border-primary/50 disabled:opacity-50"
                    />
                  </label>
                  <label className="block text-[11px] text-muted-foreground">
                    单独仓位 %
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={row.capSinglePct}
                      onChange={(e) => updatePhaseDraft(row.phase, { capSinglePct: e.target.value })}
                      disabled={phaseSaving}
                      className="mt-1 w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm tabular-nums outline-none focus:border-primary/50 disabled:opacity-50"
                    />
                  </label>
                </div>
                <label className="block text-[11px] text-muted-foreground">
                  提示词
                  <textarea
                    value={row.prompt}
                    onChange={(e) => updatePhaseDraft(row.phase, { prompt: e.target.value })}
                    maxLength={500}
                    rows={2}
                    disabled={phaseSaving}
                    className="mt-1 w-full resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm leading-relaxed outline-none focus:border-primary/50 disabled:opacity-50"
                  />
                </label>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void persistPhases()}
            disabled={phaseSaving || phaseLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            保存
          </button>
          <button
            type="button"
            onClick={() => void resetPhases()}
            disabled={phaseSaving || phaseLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
