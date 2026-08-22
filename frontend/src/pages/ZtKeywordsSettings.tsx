import { useState } from "react";
import { Plus, RotateCcw, Tags, Trash2, Lock } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  loadZtKeywords, addZtKeyword, removeZtKeyword, resetZtKeywords,
  LOCKED_ZT_KEYWORDS,
} from "@/lib/zt-keywords";

export function ZtKeywordsSettings() {
  const [tags, setTags] = useState<string[]>(() => loadZtKeywords());
  const [draft, setDraft] = useState("");

  const add = () => {
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

  const remove = (tag: string) => {
    const r = removeZtKeyword(tags, tag);
    if (!r.ok) {
      toast.error(r.reason || "删除失败");
      return;
    }
    setTags(r.next);
    toast.success(`已移除「${tag}」`);
  };

  const reset = () => {
    setTags(resetZtKeywords());
    toast.success("已恢复默认上涨关键词列表");
  };

  return (
    <div>
      <PageHeader
        title="上涨关键词"
        subtitle="首板深入分析的涨停关键字只能从本列表中选；「无原因」「其他」为兜底，不可删"
      />

      <GlassCard>
        <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
          <Tags className="h-4 w-4 text-primary" /> 上涨关键词列表
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
                    onClick={() => remove(tag)}
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
                add();
              }
            }}
            maxLength={10}
            placeholder="新标签，最多 10 字"
            className="min-w-[10rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <button
            type="button"
            onClick={add}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-medium text-primary hover:bg-primary/25"
          >
            <Plus className="h-4 w-4" /> 添加
          </button>
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <RotateCcw className="h-4 w-4" /> 恢复默认
          </button>
        </div>
      </GlassCard>
    </div>
  );
}
