import { useEffect, useState } from "react";
import { Plus, RotateCcw, Tags, Trash2, Lock, ArrowRight, GitMerge } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  loadZtKeywords, addZtKeyword, removeZtKeyword, resetZtKeywords,
  LOCKED_ZT_KEYWORDS,
} from "@/lib/zt-keywords";
import { api, type ThemeAliasEntry } from "@/lib/api";

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

export function ZtKeywordsSettings() {
  const [tags, setTags] = useState<string[]>(() => loadZtKeywords());
  const [draft, setDraft] = useState("");

  const [aliasEntries, setAliasEntries] = useState<ThemeAliasEntry[]>([]);
  const [aliasLoading, setAliasLoading] = useState(true);
  const [aliasDraft, setAliasDraft] = useState({ alias: "", canonical: "" });
  const [aliasSaving, setAliasSaving] = useState(false);

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

  const addKeyword = () => {
    const label = draft.replace(/\s+/g, "").trim();
    const r = addZtKeyword(tags, draft);
    if (!r.ok) {
      toast.error(r.reason || "添加失败");
      return;
    }
    setTags(r.next);
    setDraft("");
    toast.success(`已添加「${label}」`);
  };

  const removeKeyword = (tag: string) => {
    const r = removeZtKeyword(tags, tag);
    if (!r.ok) {
      toast.error(r.reason || "删除失败");
      return;
    }
    setTags(r.next);
    toast.success(`已移除「${tag}」`);
  };

  const resetKeywords = () => {
    setTags(resetZtKeywords());
    toast.success("已恢复默认上涨关键词列表");
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
        subtitle="首板深入分析的上涨关键词，以及题材涨停统计时的等价别名"
      />

      <GlassCard className="mb-4">
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Tags className="h-4 w-4 text-primary" /> 上涨关键词
        </h3>
        <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
          只存本地浏览器。深入分析时模型必须原样抄写其中一个标签；
          看不出明显原因用「无原因」，都不属于用「其他」。
        </p>

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
                    onClick={() => removeKeyword(tag)}
                    className="rounded p-0.5 hover:bg-primary/20 hover:text-destructive"
                    title={`删除「${tag}」`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                )}
              </span>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addKeyword();
              }
            }}
            maxLength={10}
            placeholder="新标签，最多 10 字"
            className="min-w-[10rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            type="button"
            onClick={addKeyword}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
          <button
            type="button"
            onClick={resetKeywords}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>

      <GlassCard>
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
    </div>
  );
}
