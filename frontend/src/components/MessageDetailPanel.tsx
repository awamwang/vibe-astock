import {
  useCallback, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import {
  Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp,
  ExternalLink, Loader2, Pencil, Sparkles, Star, Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  MessageDetailEdit,
  draftFromMessage,
  patchFromDraft,
  type DetailEditDraft,
} from "@/components/MessageDetailEdit";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { StockLabel } from "@/components/stock/StockLabel";
import { StockResolveScope, useStockResolve, useStockResolveOptional } from "@/components/stock/StockResolveContext";
import { BlockLabel } from "@/components/block/BlockLabel";
import { BlockResolveScope, useBlockResolveOptional } from "@/components/block/BlockResolveContext";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type AnalyzedMessage, type BlockResolveItem, type EffectStatus, type Freshness,
  type ImpactLevel, type ImpactTarget, type RawMessage, type StockResolveItem,
} from "@/lib/api";
import {
  EFFECT_LABEL, EFFECT_STATUS_OPTIONS, FRESHNESS_LABEL, IMPACT_LABEL, STATUS_LABEL,
  TARGET_KIND_LABEL, buildMessageAiContext, endAt, formatMarkLabel, hasExplicitEndAt,
  keywordHint, targetHint, targetTitle,
} from "@/lib/messages";
import { hasLlm, messageAnalyzeRun } from "@/lib/messageAnalyze";
import { keywordsSettingsTo } from "@/lib/settingsNav";
import { openSectionPopup } from "@/lib/sectionPopup";
import { isStockMatched } from "@/lib/stocks";
import { isBlockMatched } from "@/lib/thsBlocks";

const IMPACT_LEVELS: ImpactLevel[] = ["critical", "high", "medium", "low", "noise"];
const FRESHNESS_VALUES: Freshness[] = ["new", "follow_up", "duplicate", "rumor"];
const EFFECT_STATUSES: EffectStatus[] = [...EFFECT_STATUS_OPTIONS];

const quickSelectCls =
  "h-8 max-w-[7.5rem] rounded-lg border border-border bg-background px-2 text-xs font-semibold text-foreground disabled:opacity-40";

const IMPACT_BADGE: Record<string, string> = {
  critical: "bg-danger/15 text-danger border-danger/30",
  high: "bg-primary/15 text-primary border-primary/30",
  medium: "bg-muted text-foreground border-border",
  low: "bg-muted/60 text-muted-foreground border-border/60",
  noise: "bg-muted/40 text-muted-foreground border-border/40",
};

const IMPACT_TITLE: Record<string, string> = {
  critical: "text-danger",
  high: "text-primary",
};

const EFFECT_BADGE: Record<string, string> = {
  not_erupted: "bg-sky-500/12 text-sky-800 border-sky-500/35 dark:text-sky-200",
  pending_verify: "bg-amber-500/12 text-amber-800 border-amber-500/35 dark:text-amber-200",
  ongoing_hype: "bg-primary/15 text-primary border-primary/30",
  already_hyped: "bg-muted/60 text-muted-foreground border-border/60",
  invalid: "bg-muted/40 text-muted-foreground/80 border-border/40 line-through",
  early_hype: "bg-orange-500/12 text-orange-800 border-orange-500/35 dark:text-orange-200",
  faded: "bg-muted/50 text-muted-foreground border-border/50",
};

const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  info: (msg: string) => toast.info(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

export const MESSAGE_DETAIL_PATH = (id: string) => `/messages/${encodeURIComponent(id)}`;
export const MESSAGE_DETAIL_POPUP_NAME = "va-message-detail";

/** 独立窗口打开单条消息详情 */
export function openMessageDetailPopup(id: string): Window | null {
  return openSectionPopup(
    MESSAGE_DETAIL_PATH(id),
    MESSAGE_DETAIL_POPUP_NAME,
    "popup=yes,resizable=yes,scrollbars=yes,width=720,height=900,left=120,top=60",
  );
}

function Badge({
  children,
  className,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
}

function EffectBadge({ status }: { status: string }) {
  return (
    <Badge className={EFFECT_BADGE[status] || EFFECT_BADGE.not_erupted}>
      {EFFECT_LABEL[status] || status}
    </Badge>
  );
}

function DetailSection({ label, action, children }: { label: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
        {action}
      </div>
      {children}
    </div>
  );
}

function CollapsibleRawSection({
  rawMessages,
  loading,
}: {
  rawMessages: RawMessage[];
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-t border-border/60 pt-4">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">原始消息</span>
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {!loading && rawMessages.length > 0 && (
            <span>{rawMessages.length} 条</span>
          )}
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>
      {open && (
        <div className="mt-3">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : rawMessages.length === 0 ? (
            <p className="text-sm text-muted-foreground">未找到关联的原始消息</p>
          ) : (
            <div className="space-y-3">
              {rawMessages.map((raw, i) => (
                <div
                  key={raw.id}
                  className="rounded-xl border border-border/60 bg-muted/15 p-3"
                >
                  {rawMessages.length > 1 && (
                    <p className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                      原始 #{i + 1}
                      {raw.title ? ` · ${raw.title}` : ""}
                    </p>
                  )}
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                    {raw.content || "—"}
                  </p>
                  <p className="mt-2 text-[11px] tabular-nums text-muted-foreground">
                    来源 {raw.source_label || raw.source_id} · {raw.produced_at}
                    {raw.external_ref ? ` · ref ${raw.external_ref}` : ""}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function messageTargetSortTier(
  t: ImpactTarget,
  stockGet: (q: { code?: string | null; name?: string }) => StockResolveItem | undefined,
  blockGet: (name: string) => BlockResolveItem | undefined,
): number {
  if (isStockMatched(stockGet({ code: t.code, name: t.name }))) return 1;
  if (t.kind === "market") return 2;
  const showsAsBlock = t.kind === "sector" || t.kind === "theme" || !!t.name;
  if (showsAsBlock && isBlockMatched(blockGet(t.name))) return 0;
  return 2;
}

function normTargetName(name: string | null | undefined): string {
  return (name || "").replace(/\s+/g, "").trim();
}

function sortMessageTargets(
  targets: AnalyzedMessage["targets"],
  stockGet?: (q: { code?: string | null; name?: string }) => StockResolveItem | undefined,
  blockGet?: (name: string) => BlockResolveItem | undefined,
  stockHitBlockNames?: string[],
) {
  const getStock = stockGet ?? (() => undefined);
  const getBlock = blockGet ?? (() => undefined);
  const hitOrder = new Map(
    (stockHitBlockNames ?? []).map((n, i) => [normTargetName(n), i]),
  );
  return [...targets].sort((a, b) => {
    const tierDiff =
      messageTargetSortTier(a, getStock, getBlock) - messageTargetSortTier(b, getStock, getBlock);
    if (tierDiff !== 0) return tierDiff;
    if (hitOrder.size === 0) return 0;
    const aHit = hitOrder.get(normTargetName(a.name));
    const bHit = hitOrder.get(normTargetName(b.name));
    if (aHit !== undefined && bHit !== undefined) return aHit - bHit;
    if (aHit !== undefined) return -1;
    if (bHit !== undefined) return 1;
    return 0;
  });
}

function useSortMessageTargets(stockHitBlockNames?: string[]) {
  const stockCtx = useStockResolveOptional();
  const blockCtx = useBlockResolveOptional();
  return useCallback(
    (targets: AnalyzedMessage["targets"]) => sortMessageTargets(
      targets,
      stockCtx ? (q) => stockCtx.get(q) : undefined,
      blockCtx ? (n) => blockCtx.get(n) : undefined,
      stockHitBlockNames,
    ),
    [stockCtx, blockCtx, stockHitBlockNames],
  );
}

function MessageTargetBadge({
  t,
  stockHitBlockNames,
}: {
  t: AnalyzedMessage["targets"][number];
  stockHitBlockNames?: string[];
}) {
  const stockResolved = useStockResolve({ code: t.code, name: t.name });
  const stockMatched = isStockMatched(stockResolved);
  const blockName = (t.name || "").replace(/\s+/g, "").trim();
  const isStockHitBlock = (t.kind === "sector" || t.kind === "theme")
    && !!blockName
    && (stockHitBlockNames?.some((n) => (n || "").replace(/\s+/g, "").trim() === blockName) ?? false);

  if (stockMatched) {
    const stock = stockResolved!.stock!;
    return (
      <Badge
        className="border-sky-500/30 bg-sky-500/10 p-0 text-foreground"
        title={`${TARGET_KIND_LABEL.stock} · 代码 ${stock.code}`}
        data-stock-code={stock.code}
      >
        <StockLabel
          code={stock.code}
          name={stock.name}
          resolved={stockResolved}
          variant="nameOnly"
          className="border-0 bg-transparent px-1.5 py-0.5"
        />
      </Badge>
    );
  }
  if (t.kind === "market") {
    return (
      <Badge className="border-border bg-background text-foreground" title={targetHint(t)}>
        {targetTitle(t)}
      </Badge>
    );
  }
  if (t.kind === "sector" || t.kind === "theme" || t.name) {
    return (
      <Badge
        className={cn(
          "border-amber-500/30 bg-amber-500/10 p-0 text-foreground",
          isStockHitBlock && "ring-2 ring-danger/70 border-danger/60",
        )}
        title={isStockHitBlock ? `${targetHint(t)} · 成分股含当前股票` : targetHint(t)}
      >
        <BlockLabel name={targetTitle(t)} variant="tag" className="border-0 bg-transparent" />
      </Badge>
    );
  }
  if (t.kind === "stock" && (t.name || t.code)) {
    return (
      <Badge
        className="border-primary/30 bg-primary/10 p-0 text-foreground"
        title={targetHint(t)}
        data-stock-code={t.code || undefined}
      >
        <StockLabel
          code={t.code || ""}
          name={t.name}
          resolved={stockResolved}
          variant="nameOnly"
          className="border-0 bg-transparent px-1.5 py-0.5"
        />
      </Badge>
    );
  }
  return (
    <Badge className="border-border bg-background text-foreground" title={targetHint(t)}>
      {targetTitle(t)}
    </Badge>
  );
}

function MessageDetailTargets({
  targets,
  stockHitBlockNames,
}: {
  targets: AnalyzedMessage["targets"];
  stockHitBlockNames?: string[];
}) {
  const sortTargets = useSortMessageTargets(stockHitBlockNames);
  return (
    <div className="flex flex-wrap gap-2">
      {sortTargets(targets).map((t, i) => (
        <MessageTargetBadge key={i} t={t} stockHitBlockNames={stockHitBlockNames} />
      ))}
    </div>
  );
}

export type MessageDetailNav = {
  index: number;
  total: number;
  canPrev: boolean;
  canNext: boolean;
  onPrev: () => void;
  onNext: () => void;
};

type MessageDetailPanelProps = {
  /** 消息 ID；为空时显示占位 */
  messageId: string | null;
  /** 列表侧已有摘要，用于首屏立即展示 */
  seed?: AnalyzedMessage | null;
  defaultEndDays: number;
  /** 是否按当前股高亮命中板块 */
  followStockChange?: boolean;
  emptyText?: string;
  nav?: MessageDetailNav | null;
  onUpdated?: (msg: AnalyzedMessage) => void;
  onDeleted?: (id: string) => void;
  onEditingChange?: (editing: boolean) => void;
  className?: string;
};

/** 单条消息详情：加载 / 编辑 / 收藏 / 删除 / AI，可嵌列表或独立页 */
export function MessageDetailPanel({
  messageId,
  seed = null,
  defaultEndDays,
  followStockChange = false,
  emptyText = "选择消息查看详情",
  nav = null,
  onUpdated,
  onDeleted,
  onEditingChange,
  className,
}: MessageDetailPanelProps) {
  const [selected, setSelected] = useState<AnalyzedMessage | null>(seed);
  const [rawMessages, setRawMessages] = useState<RawMessage[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState<DetailEditDraft | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [quickPatching, setQuickPatching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const detailReqId = useRef(0);

  useEffect(() => {
    onEditingChange?.(editing);
  }, [editing, onEditingChange]);

  const applyUpdated = useCallback((msg: AnalyzedMessage) => {
    setSelected(msg);
    onUpdated?.(msg);
  }, [onUpdated]);

  const loadDetail = useCallback(async (id: string, softSeed?: AnalyzedMessage | null) => {
    const reqId = ++detailReqId.current;
    if (softSeed && softSeed.id === id) setSelected(softSeed);
    setRawMessages([]);
    setDetailLoading(true);
    try {
      const detail = await api.messageAnalyzedDetail(id);
      if (reqId !== detailReqId.current) return;
      setSelected(detail);
      setRawMessages(detail.raw_messages || []);
      onUpdated?.(detail);
    } catch (e) {
      if (reqId !== detailReqId.current) return;
      notify.error(e instanceof ApiError ? e.message : "加载详情失败");
      if (!softSeed || softSeed.id !== id) setSelected(null);
    } finally {
      if (reqId === detailReqId.current) setDetailLoading(false);
    }
  }, [onUpdated]);

  useEffect(() => {
    setEditing(false);
    setEditDraft(null);
    if (!messageId) {
      detailReqId.current += 1;
      setSelected(null);
      setRawMessages([]);
      setDetailLoading(false);
      return;
    }
    const soft = seed && seed.id === messageId ? seed : null;
    void loadDetail(messageId, soft);
  }, [messageId]); // eslint-disable-line react-hooks/exhaustive-deps -- 仅随 ID 切换重载；seed 仅作首屏

  // 列表侧批量操作等推送的更新（同 ID）合并进详情，不覆盖原始消息加载态
  useEffect(() => {
    if (!seed || !messageId || seed.id !== messageId || editing) return;
    setSelected((cur) => {
      if (!cur || cur.id !== seed.id) return seed;
      return { ...cur, ...seed };
    });
  }, [seed, messageId, editing]);

  const startEdit = () => {
    if (!selected) return;
    setEditDraft(draftFromMessage(selected));
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setEditDraft(null);
  };

  const saveEdit = async () => {
    if (!selected || !editDraft) return;
    setSaveLoading(true);
    try {
      const updated = await api.messageAnalyzedPatch(selected.id, patchFromDraft(editDraft));
      applyUpdated(updated);
      setEditing(false);
      setEditDraft(null);
      notify.success("已保存人工修正");
      await loadDetail(updated.id, updated);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaveLoading(false);
    }
  };

  const quickPatchField = async (
    item: AnalyzedMessage,
    patch: Partial<Pick<AnalyzedMessage, "impact_level" | "freshness" | "effect_status">>,
  ) => {
    const key = Object.keys(patch)[0] as keyof typeof patch | undefined;
    if (!key || patch[key] === item[key]) return;
    setQuickPatching(true);
    try {
      const updated = await api.messageAnalyzedPatch(item.id, patch);
      applyUpdated(updated);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "更新失败");
    } finally {
      setQuickPatching(false);
    }
  };

  const runFavorite = async (favorited: boolean) => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.messageAnalyzedFavorite([selected.id], favorited);
      notify.success(favorited ? "已收藏 1 条" : "已取消收藏 1 条");
      applyUpdated({ ...selected, favorited });
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : favorited ? "收藏失败" : "取消收藏失败");
    } finally {
      setBusy(false);
    }
  };

  const runDelete = async () => {
    if (!selected) return;
    if (!window.confirm("确定删除该消息？此操作不可恢复。")) return;
    setBusy(true);
    try {
      const id = selected.id;
      await api.messageAnalyzedDelete([id]);
      notify.success("已删除 1 条");
      setSelected(null);
      setRawMessages([]);
      onDeleted?.(id);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  const runAnalyze = async () => {
    if (!selected) return;
    if (!hasLlm()) {
      notify.error("请先在「接入 AI」配置模型后再分析");
      return;
    }
    setAnalyzing(true);
    try {
      await messageAnalyzeRun([selected.id], [], {
        onItem: (item) => {
          applyUpdated(item);
          void loadDetail(item.id, item);
        },
      });
      notify.success("AI 分析完成");
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  const messageAiContext = useMemo(() => {
    if (!selected) return "";
    return buildMessageAiContext(selected, { defaultEndDays, rawMessages });
  }, [selected, defaultEndDays, rawMessages]);

  const stockQueries = useMemo(() => {
    const out: { code?: string | null; name?: string | null }[] = [];
    if (!selected) return out;
    for (const t of selected.targets) {
      if (t.name || t.code) out.push({ code: t.code, name: t.name });
    }
    return out;
  }, [selected]);

  const blockNames = useMemo(() => {
    const names: string[] = [];
    if (!selected) return names;
    for (const t of selected.targets) {
      if (t.kind === "market" || !t.name) continue;
      names.push(t.name);
    }
    return names;
  }, [selected]);

  const body = !selected ? (
    <p className="py-12 text-center text-sm text-muted-foreground">
      {messageId && detailLoading ? (
        <span className="inline-flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
        </span>
      ) : (
        emptyText
      )}
    </p>
  ) : (
    <div className={cn("space-y-4", className)}>
      <div className="space-y-3 border-b border-border/60 pb-4">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2
              className={cn(
                "text-base font-bold leading-snug",
                IMPACT_TITLE[selected.impact_level] || "text-foreground",
              )}
            >
              {selected.title || "—"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {selected.source_label} · {STATUS_LABEL[selected.status] || selected.status}
            </p>
          </div>
          {nav && nav.total > 0 && nav.index >= 0 && (
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                aria-label="上一条"
                title="上一条（←）"
                disabled={!nav.canPrev}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-foreground transition-colors hover:bg-muted/50 disabled:opacity-40"
                onClick={nav.onPrev}
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="min-w-[3.25rem] text-center text-[11px] tabular-nums text-muted-foreground">
                {nav.index + 1}/{nav.total}
              </span>
              <button
                type="button"
                aria-label="下一条"
                title="下一条（→）"
                disabled={!nav.canNext}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-foreground transition-colors hover:bg-muted/50 disabled:opacity-40"
                onClick={nav.onNext}
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              aria-label="级别"
              title={selected.impact_manual ? "已手动指定；修改将同步初始档与工作档" : "修改将同步初始档与工作档"}
              disabled={editing || quickPatching}
              className={cn(quickSelectCls, IMPACT_BADGE[selected.impact_level] || IMPACT_BADGE.medium)}
              value={selected.impact_level}
              onChange={(e) => void quickPatchField(selected, { impact_level: e.target.value as ImpactLevel })}
            >
              {IMPACT_LEVELS.map((l) => (
                <option key={l} value={l}>{IMPACT_LABEL[l]}</option>
              ))}
            </select>
            {selected.impact_manual ? (
              <span className="text-[11px] text-muted-foreground" title="优先级已手动指定">手动</span>
            ) : null}
            {selected.initial_impact_level && selected.initial_impact_level !== selected.impact_level ? (
              <span className="text-[11px] text-muted-foreground" title="进入系统时的初始优先级">
                初:{IMPACT_LABEL[selected.initial_impact_level] || selected.initial_impact_level}
              </span>
            ) : null}
            <select
              aria-label="新旧"
              title="新旧"
              disabled={editing || quickPatching}
              className={quickSelectCls}
              value={selected.freshness}
              onChange={(e) => void quickPatchField(selected, { freshness: e.target.value as Freshness })}
            >
              {FRESHNESS_VALUES.map((f) => (
                <option key={f} value={f}>{FRESHNESS_LABEL[f]}</option>
              ))}
            </select>
            <select
              aria-label="炒作阶段"
              title="炒作阶段"
              disabled={editing || quickPatching}
              className={cn(quickSelectCls, "max-w-[8.5rem]", EFFECT_BADGE[selected.effect_status] || EFFECT_BADGE.not_erupted)}
              value={selected.effect_status}
              onChange={(e) => void quickPatchField(selected, { effect_status: e.target.value as EffectStatus })}
            >
              {!EFFECT_STATUSES.includes(selected.effect_status as EffectStatus) && (
                <option value={selected.effect_status}>
                  {EFFECT_LABEL[selected.effect_status] || selected.effect_status}
                </option>
              )}
              {EFFECT_STATUSES.map((s) => (
                <option key={s} value={s}>{EFFECT_LABEL[s]}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              className={cn(
                "inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-40",
                selected.favorited
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200"
                  : "border-border bg-background text-foreground",
              )}
              onClick={() => void runFavorite(!selected.favorited)}
            >
              <Star className={cn("h-3.5 w-3.5", selected.favorited && "fill-current")} />
              {selected.favorited ? "取消收藏" : "收藏"}
            </button>
            <button
              type="button"
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs font-semibold text-danger disabled:opacity-40"
              onClick={() => void runDelete()}
            >
              <Trash2 className="h-3.5 w-3.5" /> 删除
            </button>
            <button
              type="button"
              disabled={analyzing || !hasLlm() || editing}
              className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground disabled:opacity-40"
              onClick={() => void runAnalyze()}
            >
              {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              AI 分析
            </button>
            <AskAiButton
              context={messageAiContext}
              label="问 AI"
              suggestions={[
                "这条消息对相关标的有什么影响",
                "炒作阶段和级别怎么理解",
                "有什么风险或需要注意的点",
              ]}
            />
            {!editing ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground"
                onClick={startEdit}
              >
                <Pencil className="h-3.5 w-3.5" /> 编辑
              </button>
            ) : (
              <>
                <button
                  type="button"
                  disabled={saveLoading}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-40"
                  onClick={() => void saveEdit()}
                >
                  {saveLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  保存
                </button>
                <button
                  type="button"
                  disabled={saveLoading}
                  className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-muted-foreground disabled:opacity-40"
                  onClick={cancelEdit}
                >
                  取消
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {editing && editDraft ? (
        <MessageDetailEdit
          sourceId={selected.source_id}
          draft={editDraft}
          onChange={setEditDraft}
        />
      ) : (
        <>
          {selected.url && (
            <a
              href={selected.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
            >
              <ExternalLink className="h-4 w-4" /> 原文链接
            </a>
          )}

          <DetailSection
            label="关注"
            action={(
              <Link
                to={keywordsSettingsTo("message-follow")}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-medium text-primary underline-offset-2 hover:underline"
              >
                消息关注词 →
              </Link>
            )}
          >
            {selected.followed ? (
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="border-primary/40 bg-primary/15 text-primary">已命中</Badge>
                {(selected.matched_follow_keywords?.length ?? 0) > 0 &&
                  selected.matched_follow_keywords!.map((k) => (
                    <Badge key={`kw-${k}`} className="border-primary/30 bg-primary/10 text-primary">{k}</Badge>
                  ))}
                {(selected.matched_follow_blocks?.length ?? 0) > 0 &&
                  selected.matched_follow_blocks!.map((b) => (
                    <Badge key={`blk-${b}`} className="border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-200">
                      板块·{b}
                    </Badge>
                  ))}
                {(selected.matched_follow_keywords?.length ?? 0) === 0 &&
                  (selected.matched_follow_blocks?.length ?? 0) === 0 && (
                  <span className="text-sm text-muted-foreground">已关注，无匹配项</span>
                )}
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">未命中关注词 / 关注板块</span>
            )}
          </DetailSection>

          <DetailSection label="关键词">
            {selected.keywords.length > 0 ? (
              <div className="flex flex-wrap gap-1.5" title={keywordHint(selected.source_id)}>
                {selected.keywords.map((k) => (
                  <Badge
                    key={k}
                    className="border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-200"
                  >
                    {k}
                  </Badge>
                ))}
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">—</span>
            )}
          </DetailSection>

          {selected.marks.length > 0 && (
            <DetailSection label="标记">
              <div className="flex flex-wrap gap-1.5">
                {selected.marks.map((m) => (
                  <Badge key={m} className="border-muted-foreground/30 bg-muted/40 text-foreground" title={formatMarkLabel(m)}>
                    {formatMarkLabel(m)}
                  </Badge>
                ))}
              </div>
            </DetailSection>
          )}

          <DetailSection label="摘要">
            <p className="text-sm leading-relaxed text-foreground">{selected.summary || "—"}</p>
          </DetailSection>

          <div className="glass rounded-xl bg-muted/20 p-4 text-sm">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
              <dt className="text-muted-foreground">产生</dt>
              <dd className="font-medium tabular-nums text-foreground">{selected.produced_at}</dd>
              <dt className="text-muted-foreground">生效</dt>
              <dd className="text-foreground">
                {selected.effective_mode === "scheduled" && selected.effective_at
                  ? selected.effective_at
                  : "立即（回测按产生时间）"}
              </dd>
              <dt className="text-muted-foreground">结束</dt>
              <dd className="font-medium tabular-nums text-foreground">
                {hasExplicitEndAt(selected)
                  ? selected.end_at
                  : `${endAt(selected, defaultEndDays)}（默认 ${defaultEndDays} 天）`}
              </dd>
              <dt className="text-muted-foreground">级别</dt>
              <dd className="text-foreground">
                {IMPACT_LABEL[selected.impact_level]}
                {selected.impact_manual ? "（手动）" : ""}
              </dd>
              <dt className="text-muted-foreground">初始级别</dt>
              <dd className="text-foreground">
                {IMPACT_LABEL[selected.initial_impact_level || selected.impact_level]}
              </dd>
              <dt className="text-muted-foreground">新旧</dt>
              <dd className="text-foreground">{FRESHNESS_LABEL[selected.freshness]}</dd>
              <dt className="text-muted-foreground">炒作</dt>
              <dd className="text-foreground">
                <EffectBadge status={selected.effect_status} />
              </dd>
            </dl>
          </div>

          {selected.targets.length > 0 && (
            <DetailSection label="影响标的">
              <MessageDetailTargets
                targets={selected.targets}
                stockHitBlockNames={
                  followStockChange ? selected.matched_current_stock_blocks : undefined
                }
              />
            </DetailSection>
          )}

          <DetailSection label="详情">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
              {selected.detail || "—"}
            </p>
          </DetailSection>

          <CollapsibleRawSection
            key={selected.id}
            rawMessages={rawMessages}
            loading={detailLoading}
          />
        </>
      )}
    </div>
  );

  return (
    <StockResolveScope queries={stockQueries}>
      <BlockResolveScope names={blockNames}>
        {body}
      </BlockResolveScope>
    </StockResolveScope>
  );
}
