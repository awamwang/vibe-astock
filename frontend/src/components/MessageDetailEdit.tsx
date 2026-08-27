import { useMemo, type ReactNode } from "react";
import { Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  type AnalyzedMessage,
  type EffectStatus,
  type Freshness,
  type ImpactLevel,
  type ImpactTarget,
  type TargetKind,
} from "@/lib/api";
import {
  EFFECT_LABEL,
  EFFECT_STATUS_OPTIONS,
  FRESHNESS_LABEL,
  IMPACT_LABEL,
  STATUS_LABEL,
  TARGET_KIND_LABEL,
  keywordHint,
} from "@/lib/messages";

const inputCls =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground";
const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const labelCls = "mb-1 block text-xs font-semibold text-muted-foreground";

const IMPACT_LEVELS: ImpactLevel[] = ["critical", "high", "medium", "low", "noise"];
const FRESHNESS_VALUES: Freshness[] = ["new", "follow_up", "duplicate", "rumor"];
const EFFECT_STATUSES: EffectStatus[] = [...EFFECT_STATUS_OPTIONS];
const STATUS_VALUES: Array<AnalyzedMessage["status"]> = ["draft", "confirmed", "archived"];
const TARGET_KINDS: TargetKind[] = ["stock", "sector", "theme", "market", "other"];

export interface DetailEditDraft {
  title: string;
  summary: string;
  detail: string;
  url: string;
  keywordsText: string;
  marksText: string;
  produced_at: string;
  effective_mode: "immediate" | "scheduled";
  effective_at: string;
  impact_level: ImpactLevel;
  freshness: Freshness;
  effect_status: EffectStatus;
  status: AnalyzedMessage["status"];
  targets: ImpactTarget[];
}

function splitTags(text: string): string[] {
  return text.split(/[,，\n]/).map((t) => t.trim()).filter(Boolean);
}

function joinTags(items: string[]): string {
  return items.join(", ");
}

/** 将存储时间转为 datetime-local 值 */
function toDatetimeLocal(value: string | null | undefined): string {
  if (!value) return "";
  const m = value.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
  return m ? `${m[1]}T${m[2]}` : "";
}

/** 将 datetime-local 值转为存储格式 */
function fromDatetimeLocal(value: string): string {
  if (!value) return "";
  const normalized = value.replace("T", " ");
  return normalized.length === 16 ? `${normalized}:00` : normalized;
}

export function draftFromMessage(item: AnalyzedMessage): DetailEditDraft {
  return {
    title: item.title || "",
    summary: item.summary || "",
    detail: item.detail || "",
    url: item.url || "",
    keywordsText: joinTags(item.keywords || []),
    marksText: joinTags(item.marks || []),
    produced_at: item.produced_at || "",
    effective_mode: item.effective_mode || "immediate",
    effective_at: item.effective_at || "",
    impact_level: item.impact_level,
    freshness: item.freshness,
    effect_status: item.effect_status,
    status: item.status,
    targets: (item.targets || []).map((t) => ({ ...t })),
  };
}

export function patchFromDraft(draft: DetailEditDraft): Partial<AnalyzedMessage> {
  return {
    title: draft.title.trim(),
    summary: draft.summary.trim(),
    detail: draft.detail,
    url: draft.url.trim(),
    keywords: splitTags(draft.keywordsText),
    marks: splitTags(draft.marksText),
    produced_at: draft.produced_at.trim(),
    effective_mode: draft.effective_mode,
    effective_at:
      draft.effective_mode === "scheduled" && draft.effective_at.trim()
        ? draft.effective_at.trim()
        : null,
    impact_level: draft.impact_level,
    freshness: draft.freshness,
    effect_status: draft.effect_status,
    status: draft.status,
    targets: draft.targets
      .filter((t) => t.name.trim() || t.code?.trim())
      .map((t) => ({
        kind: t.kind,
        name: t.name.trim() || t.code?.trim() || "",
        code: t.code?.trim() || null,
      })),
  };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label className={labelCls}>
        {label}
        {hint && <span className="ml-1 font-normal text-muted-foreground/80">({hint})</span>}
      </label>
      {children}
    </div>
  );
}

function TargetEditor({
  targets,
  onChange,
}: {
  targets: ImpactTarget[];
  onChange: (targets: ImpactTarget[]) => void;
}) {
  const rows = targets.length > 0 ? targets : [{ kind: "stock" as TargetKind, name: "", code: "" }];

  const updateRow = (index: number, patch: Partial<ImpactTarget>) => {
    const next = rows.map((t, i) => (i === index ? { ...t, ...patch } : t));
    onChange(next);
  };

  const removeRow = (index: number) => {
    onChange(rows.filter((_, i) => i !== index));
  };

  const addRow = () => {
    onChange([...rows, { kind: "stock", name: "", code: "" }]);
  };

  return (
    <div className="space-y-2">
      {rows.map((t, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <select
            className={cn(selectCls, "min-w-[88px]")}
            value={t.kind}
            onChange={(e) => updateRow(i, { kind: e.target.value as TargetKind })}
          >
            {TARGET_KINDS.map((k) => (
              <option key={k} value={k}>{TARGET_KIND_LABEL[k]}</option>
            ))}
          </select>
          <input
            className={cn(inputCls, "min-w-[100px] flex-1")}
            placeholder="名称"
            value={t.name}
            onChange={(e) => updateRow(i, { name: e.target.value })}
          />
          <input
            className={cn(inputCls, "min-w-[88px] w-28")}
            placeholder="代码"
            value={t.code || ""}
            onChange={(e) => updateRow(i, { code: e.target.value })}
          />
          <button
            type="button"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-danger disabled:opacity-40"
            onClick={() => removeRow(i)}
            disabled={rows.length <= 1}
            aria-label="删除标的"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground hover:bg-muted/50"
        onClick={addRow}
      >
        <Plus className="h-3.5 w-3.5" /> 添加标的
      </button>
    </div>
  );
}

export function MessageDetailEdit({
  sourceId,
  draft,
  onChange,
}: {
  sourceId: string;
  draft: DetailEditDraft;
  onChange: (draft: DetailEditDraft) => void;
}) {
  const keywordPlaceholder = useMemo(() => keywordHint(sourceId), [sourceId]);

  const set = <K extends keyof DetailEditDraft>(key: K, value: DetailEditDraft[K]) => {
    onChange({ ...draft, [key]: value });
  };

  return (
    <div className="space-y-4">
      <Field label="标题">
        <input className={inputCls} value={draft.title} onChange={(e) => set("title", e.target.value)} />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="状态">
          <select className={cn(selectCls, "w-full")} value={draft.status} onChange={(e) => set("status", e.target.value as DetailEditDraft["status"])}>
            {STATUS_VALUES.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
        </Field>
        <Field label="原文链接">
          <input className={inputCls} value={draft.url} onChange={(e) => set("url", e.target.value)} placeholder="https://…" />
        </Field>
      </div>

      <Field label="摘要" hint="建议 ≤120 字">
        <textarea
          className={cn(inputCls, "min-h-[72px] resize-y")}
          rows={3}
          value={draft.summary}
          onChange={(e) => set("summary", e.target.value)}
        />
      </Field>

      <Field label="详情" hint="支持 Markdown">
        <textarea
          className={cn(inputCls, "min-h-[120px] resize-y font-mono text-[13px]")}
          rows={6}
          value={draft.detail}
          onChange={(e) => set("detail", e.target.value)}
        />
      </Field>

      <Field label="关键词" hint={keywordPlaceholder}>
        <input
          className={inputCls}
          value={draft.keywordsText}
          onChange={(e) => set("keywordsText", e.target.value)}
          placeholder="逗号或换行分隔"
        />
      </Field>

      <Field label="标记" hint="如 highlight、impact:1">
        <input
          className={inputCls}
          value={draft.marksText}
          onChange={(e) => set("marksText", e.target.value)}
          placeholder="逗号或换行分隔"
        />
      </Field>

      <div className="glass rounded-xl bg-muted/20 p-4 space-y-3">
        <Field label="产生时间">
          <input
            type="datetime-local"
            className={inputCls}
            value={toDatetimeLocal(draft.produced_at)}
            onChange={(e) => set("produced_at", fromDatetimeLocal(e.target.value))}
          />
        </Field>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="生效方式">
            <select
              className={cn(selectCls, "w-full")}
              value={draft.effective_mode}
              onChange={(e) => set("effective_mode", e.target.value as DetailEditDraft["effective_mode"])}
            >
              <option value="immediate">立即（回测按产生时间）</option>
              <option value="scheduled">指定时间</option>
            </select>
          </Field>
          {draft.effective_mode === "scheduled" && (
            <Field label="生效时间">
              <input
                type="datetime-local"
                className={inputCls}
                value={toDatetimeLocal(draft.effective_at)}
                onChange={(e) => set("effective_at", fromDatetimeLocal(e.target.value))}
              />
            </Field>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="级别">
            <select className={cn(selectCls, "w-full")} value={draft.impact_level} onChange={(e) => set("impact_level", e.target.value as ImpactLevel)}>
              {IMPACT_LEVELS.map((l) => (
                <option key={l} value={l}>{IMPACT_LABEL[l]}</option>
              ))}
            </select>
          </Field>
          <Field label="新旧">
            <select className={cn(selectCls, "w-full")} value={draft.freshness} onChange={(e) => set("freshness", e.target.value as Freshness)}>
              {FRESHNESS_VALUES.map((f) => (
                <option key={f} value={f}>{FRESHNESS_LABEL[f]}</option>
              ))}
            </select>
          </Field>
          <Field label="炒作">
            <select className={cn(selectCls, "w-full")} value={draft.effect_status} onChange={(e) => set("effect_status", e.target.value as EffectStatus)}>
              {EFFECT_STATUSES.map((s) => (
                <option key={s} value={s}>{EFFECT_LABEL[s]}</option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <Field label="影响标的">
        <TargetEditor targets={draft.targets} onChange={(targets) => set("targets", targets)} />
      </Field>
    </div>
  );
}
