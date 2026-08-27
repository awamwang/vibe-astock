import { useEffect, useState } from "react";
import { Plus, RotateCcw, Tags, Trash2, Lock, ArrowRight, GitMerge, SlidersHorizontal, Eye, ChevronRight, Save, AlertCircle, Pencil, Check, X } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import {
  addZtKeyword, removeZtKeyword, setZtKeywordsCache,
  LOCKED_ZT_KEYWORDS,
} from "@/lib/zt-keywords";
import {
  addMessageFollowKeyword,
  removeMessageFollowKeyword,
  setMessageFollowKeywordsCache,
} from "@/lib/message-follow-keywords";
import { api, type ThemeAliasEntry, type TradePhaseConfigRow, type SentimentSConfig, type TradeThresholdConfig, type BlockPendingItem } from "@/lib/api";

type ConfigSectionId =
  | "zt-keywords"
  | "message-follow"
  | "theme-aliases"
  | "sentiment-s"
  | "trade-thresholds"
  | "trade-phases";

const CONFIG_SECTIONS: {
  id: ConfigSectionId;
  label: string;
  icon: typeof Tags;
  hint: string;
}[] = [
  { id: "zt-keywords", label: "上涨关键词", icon: Tags, hint: "首板深入分析闭集标签" },
  { id: "message-follow", label: "消息关注词", icon: Eye, hint: "消息分析命中筛选" },
  { id: "theme-aliases", label: "板块别名", icon: GitMerge, hint: "统计时别名合并" },
  { id: "sentiment-s", label: "合成情绪分 S", icon: SlidersHorizontal, hint: "六档情绪算法" },
  { id: "trade-thresholds", label: "定档阈值", icon: SlidersHorizontal, hint: "退潮/过热/高潮等" },
  { id: "trade-phases", label: "仓位预算档位", icon: SlidersHorizontal, hint: "总仓/单票/提示词" },
];

function sortAliasEntries(entries: ThemeAliasEntry[]): ThemeAliasEntry[] {
  return [...entries].sort((a, b) => {
    const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
    if (byCanonical !== 0) return byCanonical;
    return a.alias.localeCompare(b.alias, "zh-CN");
  });
}

function normalizeAliasEntries(entries: ThemeAliasEntry[]): ThemeAliasEntry[] {
  return sortAliasEntries(
    entries.map((e) => ({
      alias: e.alias,
      canonical: e.canonical,
      type: (e.type ?? "").trim(),
    })),
  );
}

function entriesFromConfig(cfg: { entries?: ThemeAliasEntry[]; aliases?: Record<string, string>; types?: Record<string, string> }): ThemeAliasEntry[] {
  if (cfg.entries?.length) {
    return normalizeAliasEntries(cfg.entries);
  }
  const types = cfg.types || {};
  return normalizeAliasEntries(
    Object.entries(cfg.aliases || {}).map(([alias, canonical]) => ({
      alias,
      canonical,
      type: types[alias] ?? "",
    })),
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

/** 阈值在界面上的编辑值：ratio 用百分数，其余原样 */
function fieldToDraft(kind: string, value: number): string {
  if (kind === "ratio") {
    const n = Math.round(value * 10000) / 100;
    return String(n);
  }
  if (kind === "boards" || kind === "count") {
    return String(Math.round(value));
  }
  return String(value);
}

function draftToValue(kind: string, raw: string, label: string, min: number, max: number): number {
  const n = Number(String(raw).trim());
  if (!Number.isFinite(n)) throw new Error(`${label}须为数字`);
  let v = kind === "ratio" ? n / 100 : n;
  if (v < min || v > max) {
    const lo = kind === "ratio" ? min * 100 : min;
    const hi = kind === "ratio" ? max * 100 : max;
    const unit = kind === "ratio" ? "%" : "";
    throw new Error(`${label}须在 ${lo}${unit}–${hi}${unit}`);
  }
  return v;
}

function refForField(
  cfg: TradeThresholdConfig | null,
  refKey: string,
): string {
  if (!cfg?.reference?.display?.length) return "—";
  const hit = cfg.reference.display.find((d) => d.key === refKey);
  if (hit?.formatted != null && hit.formatted !== "") return hit.formatted;
  if (refKey === "highest_hist_peak") {
    const peak = cfg.reference.readings?.highest_hist_peak;
    return peak == null ? "—" : String(peak);
  }
  return "—";
}

export function ZtKeywordsSettings() {
  const [activeSection, setActiveSection] = useState<ConfigSectionId>("zt-keywords");

  const [tags, setTags] = useState<string[]>([]);
  const [tagsLoading, setTagsLoading] = useState(true);
  const [tagsSaving, setTagsSaving] = useState(false);
  const [draft, setDraft] = useState("");

  const [followTags, setFollowTags] = useState<string[]>([]);
  const [followLoading, setFollowLoading] = useState(true);
  const [followSaving, setFollowSaving] = useState(false);
  const [followDraft, setFollowDraft] = useState("");

  const [aliasEntries, setAliasEntries] = useState<ThemeAliasEntry[]>([]);
  const [aliasLoading, setAliasLoading] = useState(true);
  const [aliasDraft, setAliasDraft] = useState({ alias: "", canonical: "" });
  const [aliasSaving, setAliasSaving] = useState(false);
  const [aliasEditingKey, setAliasEditingKey] = useState<string | null>(null);
  const [aliasEditDraft, setAliasEditDraft] = useState({ alias: "", canonical: "", type: "" });

  const [pendingItems, setPendingItems] = useState<BlockPendingItem[]>([]);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingDrafts, setPendingDrafts] = useState<Record<string, string>>({});
  const [pendingSavingKey, setPendingSavingKey] = useState("");

  const [phaseDrafts, setPhaseDrafts] = useState<PhaseDraft[]>([]);
  const [phaseLoading, setPhaseLoading] = useState(true);
  const [phaseSaving, setPhaseSaving] = useState(false);

  const [sCfg, setSCfg] = useState<SentimentSConfig | null>(null);
  const [sMethod, setSMethod] = useState("hard_rules");
  const [sLoading, setSLoading] = useState(true);
  const [sSaving, setSSaving] = useState(false);
  const [sRefreshing, setSRefreshing] = useState(false);

  const [thCfg, setThCfg] = useState<TradeThresholdConfig | null>(null);
  const [thDrafts, setThDrafts] = useState<Record<string, string>>({});
  const [thLoading, setThLoading] = useState(true);
  const [thSaving, setThSaving] = useState(false);

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
        const cfg = await api.messageFollowKeywords();
        if (!cancelled) {
          const kw = setMessageFollowKeywordsCache(cfg.keywords || []);
          setFollowTags(kw);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取消息关注词失败");
        }
      } finally {
        if (!cancelled) setFollowLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.themeAliases();
        if (!cancelled) setAliasEntries(entriesFromConfig(cfg));
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取板块别名失败");
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
        const cfg = await api.blockPending();
        if (!cancelled) {
          const items = cfg.items || [];
          setPendingItems(items);
          const drafts: Record<string, string> = {};
          for (const row of items) {
            const key = row.mapped || row.raw;
            drafts[key] = row.suggested_canonical
              || row.candidates.map((c) => c.name).join(" ")
              || row.mapped
              || "";
          }
          setPendingDrafts(drafts);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取待匹配板块失败");
        }
      } finally {
        if (!cancelled) setPendingLoading(false);
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

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.tradeThresholdConfig();
        if (!cancelled) {
          setThCfg(cfg);
          const next: Record<string, string> = {};
          for (const g of cfg.groups || []) {
            for (const f of g.fields || []) {
              next[f.key] = fieldToDraft(f.value_kind, f.value);
            }
          }
          setThDrafts(next);
        }
      } catch (e) {
        if (!cancelled) {
          toast.error(e instanceof Error ? e.message : "读取定档阈值失败");
        }
      } finally {
        if (!cancelled) setThLoading(false);
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
        `序列已更新：${r.meta.days} 日`
        + (r.enriched_this_run ? `，本轮补最高板 ${r.enriched_this_run} 日` : "")
        + (r.qcj_highest_filled ? `，回补最高板 ${r.qcj_highest_filled} 日` : "")
        + (typeof r.xgb_broken_filled === "number"
          ? `，炸板率 ${r.xgb_broken_filled} 日`
          : "")
        + ` · ${marketHint}`,
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "刷新序列失败");
    } finally {
      setSRefreshing(false);
    }
  };

  const applyThresholdCfg = (cfg: TradeThresholdConfig) => {
    setThCfg(cfg);
    const next: Record<string, string> = {};
    for (const g of cfg.groups || []) {
      for (const f of g.fields || []) {
        next[f.key] = fieldToDraft(f.value_kind, f.value);
      }
    }
    setThDrafts(next);
  };

  const persistThresholds = async () => {
    if (!thCfg) return;
    let payload: Record<string, number>;
    try {
      payload = {};
      for (const g of thCfg.groups) {
        for (const f of g.fields) {
          payload[f.key] = draftToValue(
            f.value_kind,
            thDrafts[f.key] ?? "",
            f.label,
            f.min,
            f.max,
          );
        }
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "阈值不合法");
      return;
    }
    setThSaving(true);
    try {
      const cfg = await api.saveTradeThresholdConfig(payload);
      applyThresholdCfg(cfg);
      toast.success("定档阈值已保存；请到「持仓与预算」重算场次");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setThSaving(false);
    }
  };

  const resetThresholds = async () => {
    setThSaving(true);
    try {
      const cfg = await api.resetTradeThresholdConfig();
      applyThresholdCfg(cfg);
      toast.success("已恢复默认定档阈值");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setThSaving(false);
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
    setAliasSaving(true);
    try {
      const r = await api.saveThemeAliases(next);
      setAliasEntries(entriesFromConfig(r));
      toast.success("板块别名已保存");
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

  const persistFollowKeywords = async (next: string[]) => {
    setFollowSaving(true);
    try {
      const r = await api.saveMessageFollowKeywords(next);
      const kw = setMessageFollowKeywordsCache(r.keywords);
      setFollowTags(kw);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setFollowSaving(false);
    }
  };

  const addFollowKeyword = async () => {
    const label = followDraft.replace(/\s+/g, "").trim();
    const r = addMessageFollowKeyword(followTags, followDraft);
    if (!r.ok) {
      toast.error(r.reason || "添加失败");
      return;
    }
    setFollowDraft("");
    await persistFollowKeywords(r.next);
    toast.success(`已添加「${label}」`);
  };

  const removeFollowKeyword = async (tag: string) => {
    const r = removeMessageFollowKeyword(followTags, tag);
    if (!r.ok) {
      toast.error(r.reason || "删除失败");
      return;
    }
    await persistFollowKeywords(r.next);
    toast.success(`已移除「${tag}」`);
  };

  const resetFollowKeywords = async () => {
    setFollowSaving(true);
    try {
      const r = await api.resetMessageFollowKeywords();
      const kw = setMessageFollowKeywordsCache(r.keywords);
      setFollowTags(kw);
      toast.success("已清空消息关注词");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "清空失败");
    } finally {
      setFollowSaving(false);
    }
  };

  const addAlias = async () => {
    const alias = aliasDraft.alias.replace(/\s+/g, "").trim();
    const canonical = aliasDraft.canonical.replace(/\s+/g, "").trim();
    if (!alias || !canonical) {
      toast.error("请填写别名与标准板块");
      return;
    }
    if (alias.length > 20 || canonical.length > 20) {
      toast.error("板块名不超过 20 个字");
      return;
    }
    if (alias === canonical) {
      toast.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => e.alias === alias)) {
      toast.error("该别名已存在");
      return;
    }
    const next = sortAliasEntries([...aliasEntries, { alias, canonical, type: "" }]);
    setAliasDraft({ alias: "", canonical: "" });
    await persistAliases(next);
  };

  const removeAlias = async (alias: string) => {
    if (aliasEditingKey === alias) {
      setAliasEditingKey(null);
      setAliasEditDraft({ alias: "", canonical: "", type: "" });
    }
    const next = aliasEntries.filter((e) => e.alias !== alias);
    await persistAliases(next);
  };

  const startEditAlias = (row: ThemeAliasEntry) => {
    setAliasEditingKey(row.alias);
    setAliasEditDraft({
      alias: row.alias,
      canonical: row.canonical,
      type: row.type.trim(),
    });
  };

  const cancelEditAlias = () => {
    setAliasEditingKey(null);
    setAliasEditDraft({ alias: "", canonical: "", type: "" });
  };

  const saveEditAlias = async () => {
    if (!aliasEditingKey) return;
    const alias = aliasEditDraft.alias.replace(/\s+/g, "").trim();
    const canonical = aliasEditDraft.canonical.replace(/\s+/g, "").trim();
    const type = aliasEditDraft.type.replace(/\s+/g, "").trim();
    if (!alias || !canonical) {
      toast.error("请填写别名与标准板块");
      return;
    }
    if (alias.length > 20 || canonical.length > 20) {
      toast.error("板块名不超过 20 个字");
      return;
    }
    if (alias === canonical) {
      toast.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => e.alias === alias && e.alias !== aliasEditingKey)) {
      toast.error("该别名已存在");
      return;
    }
    const next = sortAliasEntries(
      aliasEntries.map((e) =>
        e.alias === aliasEditingKey ? { alias, canonical, type } : e,
      ),
    );
    setAliasEditingKey(null);
    setAliasEditDraft({ alias: "", canonical: "", type: "" });
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
      setAliasEntries(entriesFromConfig(r));
      toast.success("已恢复默认板块别名");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "恢复失败");
    } finally {
      setAliasSaving(false);
    }
  };

  const savePendingRow = async (row: BlockPendingItem) => {
    const key = row.mapped || row.raw;
    const alias = row.raw.replace(/\s+/g, "").trim();
    const draft = (pendingDrafts[key] || "").trim();
    const canonical = draft.split(/\s+/).filter(Boolean)[0] || "";
    if (!alias || !canonical) {
      toast.error("请填写标准板块");
      return;
    }
    if (alias.length > 20 || canonical.length > 20) {
      toast.error("板块名不超过 20 个字");
      return;
    }
    if (alias === canonical) {
      toast.error("别名与标准板块不能相同");
      return;
    }
    setPendingSavingKey(key);
    try {
      const r = await api.saveBlockPendingAlias(alias, canonical);
      setAliasEntries(entriesFromConfig(r));
      setPendingItems((items) => items.filter((it) => (it.mapped || it.raw) !== key));
      toast.success(`已保存「${alias} → ${canonical}」`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setPendingSavingKey("");
    }
  };

  return (
    <div>
      <PageHeader
        title="自定义配置"
        subtitle="上涨关键词、消息关注词、板块别名、定档阈值，以及仓位预算六档的总仓、单票与提示词"
      />

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <nav className="glass shrink-0 rounded-2xl p-2 lg:w-52">
          <p className="px-3 py-2 text-[11px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            配置项
          </p>
          <ul className="space-y-0.5">
            {CONFIG_SECTIONS.map((section) => {
              const Icon = section.icon;
              const active = activeSection === section.id;
              return (
                <li key={section.id}>
                  <button
                    type="button"
                    onClick={() => setActiveSection(section.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
                      active
                        ? "bg-primary/15 font-semibold text-primary"
                        : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{section.label}</span>
                    <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 opacity-60", active && "opacity-100")} />
                  </button>
                  {active && (
                    <p className="px-3 pb-1 text-[11px] leading-relaxed text-muted-foreground lg:hidden">
                      {section.hint}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="min-w-0 flex-1">
          {activeSection === "zt-keywords" && (
      <GlassCard className="mb-0">
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
          )}

          {activeSection === "message-follow" && (
      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Eye className="h-4 w-4 text-primary" /> 消息关注词
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          存于本机后端数据目录。消息分析列表会标记是否命中下列词（标题、摘要、详情、关键词字段），
          并支持按「已关注 / 未关注」筛选。无内置默认词，可随时增删。
        </p>

        {followLoading ? (
          <p className="text-xs text-muted-foreground">正在读取消息关注词…</p>
        ) : followTags.length === 0 ? (
          <p className="mb-4 text-xs text-muted-foreground">暂无关注词，可在下方添加。</p>
        ) : (
          <div className="mb-4 flex flex-wrap gap-2">
            {followTags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-medium text-primary"
              >
                {tag}
                <button
                  type="button"
                  disabled={followSaving}
                  onClick={() => void removeFollowKeyword(tag)}
                  className="rounded p-0.5 hover:bg-primary/20 hover:text-destructive disabled:opacity-50"
                  title={`删除「${tag}」`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <input
            value={followDraft}
            onChange={(e) => setFollowDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addFollowKeyword();
              }
            }}
            maxLength={20}
            placeholder="新关注词，最多 20 字"
            disabled={followSaving || followLoading}
            className="min-w-[10rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void addFollowKeyword()}
            disabled={followSaving || followLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
          <button
            type="button"
            onClick={() => void resetFollowKeywords()}
            disabled={followSaving || followLoading || followTags.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" /> 清空全部
          </button>
        </div>
      </GlassCard>
          )}

          {activeSection === "theme-aliases" && (
      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <GitMerge className="h-4 w-4 text-primary" /> 板块别名
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          存于本机后端数据目录。统计板块涨停数（题材事件树、多日情绪矩阵等）时，
          把左侧别名合并到右侧标准板块；只走显式映射，不做模糊或语义归类。
        </p>

        {aliasLoading ? (
          <p className="text-xs text-muted-foreground">正在读取板块别名…</p>
        ) : aliasEntries.length === 0 ? (
          <p className="mb-3 text-xs text-muted-foreground">暂无别名，可在下方添加。</p>
        ) : (
          <div className="mb-4 space-y-1.5">
            {aliasEntries.map((row) => {
              const editing = aliasEditingKey === row.alias;
              return (
                <div
                  key={row.alias}
                  className={cn(
                    "flex flex-wrap items-center gap-2 rounded-md border px-2 py-1.5 text-xs font-medium",
                    editing
                      ? "border-primary/50 bg-black/20"
                      : "border-primary/30 bg-primary/10",
                  )}
                >
                  {editing ? (
                    <>
                      <input
                        value={aliasEditDraft.alias}
                        onChange={(e) => setAliasEditDraft((d) => ({ ...d, alias: e.target.value }))}
                        maxLength={20}
                        disabled={aliasSaving}
                        placeholder="别名"
                        className="min-w-[5rem] flex-1 rounded border border-border bg-black/30 px-2 py-1 text-xs outline-none focus:border-primary/50 disabled:opacity-50"
                      />
                      <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <input
                        value={aliasEditDraft.canonical}
                        onChange={(e) => setAliasEditDraft((d) => ({ ...d, canonical: e.target.value }))}
                        maxLength={20}
                        disabled={aliasSaving}
                        placeholder="标准板块"
                        className="min-w-[5rem] flex-1 rounded border border-border bg-black/30 px-2 py-1 text-xs outline-none focus:border-primary/50 disabled:opacity-50"
                      />
                      <span className="text-muted-foreground">类型</span>
                      <input
                        value={aliasEditDraft.type}
                        onChange={(e) => setAliasEditDraft((d) => ({ ...d, type: e.target.value }))}
                        maxLength={10}
                        disabled={aliasSaving}
                        placeholder="可选"
                        className="w-16 rounded border border-border bg-black/30 px-2 py-1 text-[10px] font-normal outline-none focus:border-primary/50 disabled:opacity-50"
                      />
                      <div className="ml-auto flex items-center gap-0.5">
                        <button
                          type="button"
                          disabled={aliasSaving}
                          onClick={() => void saveEditAlias()}
                          className="rounded p-0.5 text-primary hover:bg-primary/20 disabled:opacity-50"
                          title="保存修改"
                        >
                          <Check className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          disabled={aliasSaving}
                          onClick={cancelEditAlias}
                          className="rounded p-0.5 text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                          title="取消编辑"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <span className="text-foreground">{row.alias}</span>
                      <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <span className="text-primary">{row.canonical}</span>
                      <span className="text-muted-foreground">类型</span>
                      <span
                        className="inline-block min-w-[2rem] rounded border border-dashed border-border/60 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground"
                        title="类型标记"
                      >
                        {row.type.trim() || "—"}
                      </span>
                      <div className="ml-auto flex items-center gap-0.5">
                        <button
                          type="button"
                          disabled={aliasSaving || aliasEditingKey != null}
                          onClick={() => startEditAlias(row)}
                          className="rounded p-0.5 text-muted-foreground hover:bg-primary/20 hover:text-primary disabled:opacity-50"
                          title={`编辑「${row.alias}」`}
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          disabled={aliasSaving || aliasEditingKey != null}
                          onClick={() => void removeAlias(row.alias)}
                          className="rounded p-0.5 text-muted-foreground hover:bg-primary/20 hover:text-destructive disabled:opacity-50"
                          title={`删除「${row.alias}」`}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
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
              disabled={aliasSaving || aliasEditingKey != null}
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
            />
          </div>
          <div className="min-w-[8rem] flex-1">
            <label className="mb-1 block text-[11px] text-muted-foreground">标准板块</label>
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
              disabled={aliasSaving || aliasEditingKey != null}
              className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
            />
          </div>
          <button
            type="button"
            onClick={() => void addAlias()}
            disabled={aliasSaving || aliasEditingKey != null}
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

        <div className="mt-6 border-t border-border/60 pt-4">
          <h4 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
            <AlertCircle className="h-4 w-4 text-amber-500" /> 待匹配板块
          </h4>
          <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
            各业务页加载时自动收集未能完全匹配同花顺板块的名称。完全匹配（含多命中取优先级最高）不会出现在此列表；
            部分匹配会将候选板块名以空格填入右侧输入框，保存后写入上方板块别名表。
          </p>

          {pendingLoading ? (
            <p className="text-xs text-muted-foreground">正在读取待匹配列表…</p>
          ) : pendingItems.length === 0 ? (
            <p className="text-xs text-muted-foreground">暂无待匹配项（请先访问短线盘面、涨停分析等页面以收集）。</p>
          ) : (
            <div className="space-y-2">
              {pendingItems.map((row) => {
                const key = row.mapped || row.raw;
                const saving = pendingSavingKey === key;
                return (
                  <div
                    key={key}
                    className="rounded-lg border border-border/50 bg-black/10 px-3 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-medium">
                        <span className="text-foreground">{row.raw}</span>
                        {row.mapped !== row.raw && (
                          <>
                            <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                            <span className="text-muted-foreground">{row.mapped}</span>
                          </>
                        )}
                      </span>
                      <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      <input
                        value={pendingDrafts[key] ?? ""}
                        onChange={(e) =>
                          setPendingDrafts((d) => ({ ...d, [key]: e.target.value }))
                        }
                        disabled={saving}
                        placeholder={row.status === "partial" ? "候选板块（空格分隔）" : "标准板块"}
                        className="min-w-[12rem] flex-1 rounded-lg border border-border bg-black/20 px-2 py-1 text-xs outline-none focus:border-primary/50 disabled:opacity-50"
                      />
                      <button
                        type="button"
                        onClick={() => void savePendingRow(row)}
                        disabled={saving || aliasSaving}
                        className="inline-flex items-center gap-1 rounded-lg bg-primary/15 px-2 py-1 text-xs font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
                      >
                        <Save className="h-3 w-3" /> 保存
                      </button>
                      <span className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-medium",
                        row.status === "partial"
                          ? "bg-amber-500/15 text-amber-600"
                          : "bg-muted/40 text-muted-foreground",
                      )}>
                        {row.status === "partial" ? "部分匹配" : "未匹配"}
                      </span>
                    </div>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      来源：{(row.source_labels || []).join("、") || "—"}
                      {row.hit_count > 1 ? ` · 命中 ${row.hit_count} 次` : ""}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </GlassCard>
          )}

          {activeSection === "sentiment-s" && (
      <GlassCard className="mb-0">
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
              {typeof sCfg.series_meta.highest_days === "number"
                ? ` · 最高板 ${sCfg.series_meta.highest_days} 日`
                : ""}
              {typeof sCfg.series_meta.broken_rate_days === "number"
                ? ` · 炸板率 ${sCfg.series_meta.broken_rate_days} 日`
                : ""}
              {(sCfg.series_meta.pending_days ?? 0) > 0
                ? ` · 待补最高板 ${sCfg.series_meta.pending_days} 日`
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
            {sRefreshing ? "刷新中…" : "刷新分位序列（每轮补 30 日）"}
          </button>
        </div>
      </GlassCard>
          )}

          {activeSection === "trade-thresholds" && (
      <GlassCard className="mb-0">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <SlidersHorizontal className="h-4 w-4 text-primary" /> 定档阈值
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          按情绪档位分组（退潮 → 过热 → 高潮 → 冰点 → S 区间），与定档判定顺序一致。
          炸板率、赚钱中位等共用读数只出现一次，说明里会注明兼用于哪一档。右侧为最近一场读数。
          {thCfg?.reference?.date ? `（对照日 ${thCfg.reference.date}` : ""}
          {thCfg?.reference?.reason ? ` · ${thCfg.reference.reason}` : ""}
          {thCfg?.reference?.date ? "）" : ""}
        </p>

        {thLoading || !thCfg ? (
          <p className="text-xs text-muted-foreground">正在读取定档阈值…</p>
        ) : (
          <div className="space-y-5">
            {thCfg.groups.map((g) => (
              <div key={g.id}>
                <div className="mb-1 text-sm font-semibold text-foreground">{g.label}</div>
                <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">{g.desc}</p>
                <div className="space-y-2">
                  {g.fields.map((f) => {
                    const unit =
                      f.value_kind === "ratio" ? "%"
                        : f.value_kind === "boards" ? "板"
                          : f.value_kind === "count" ? "家"
                            : f.value_kind === "score" ? "分"
                              : "";
                    return (
                      <div
                        key={f.key}
                        className="grid grid-cols-1 gap-2 rounded-lg border border-border/50 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_7rem_6.5rem] sm:items-center"
                      >
                        <div className="min-w-0">
                          <div className="text-sm text-foreground">
                            {f.label}
                            {unit ? <span className="ml-1 text-[11px] text-muted-foreground">({unit})</span> : null}
                          </div>
                          <div className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{f.desc}</div>
                        </div>
                        <input
                          type="number"
                          step={f.value_kind === "ratio" || f.value_kind === "score" || f.value_kind === "number" ? "0.1" : "1"}
                          value={thDrafts[f.key] ?? ""}
                          onChange={(e) =>
                            setThDrafts((d) => ({ ...d, [f.key]: e.target.value }))
                          }
                          disabled={thSaving}
                          className="w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm tabular-nums outline-none focus:border-primary/50 disabled:opacity-50"
                        />
                        <div className="text-[11px] tabular-nums text-muted-foreground sm:text-right">
                          最近：{refForField(thCfg, f.ref_key)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void persistThresholds()}
            disabled={thSaving || thLoading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50"
          >
            保存阈值
          </button>
          <button
            type="button"
            onClick={() => void resetThresholds()}
            disabled={thSaving || thLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:opacity-50"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>
          )}

          {activeSection === "trade-phases" && (
      <GlassCard className="mb-0">
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
          )}
        </div>
      </div>
    </div>
  );
}
