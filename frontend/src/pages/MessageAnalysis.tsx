import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  Search, RefreshCw, Loader2, ChevronDown, ChevronUp, Plus, Trash2,
  ExternalLink, Sparkles, Check, Newspaper, Radio, X, Star, RotateCcw, Pencil,
  LayoutList, CalendarDays,
} from "lucide-react";
import {
  MessageDetailEdit,
  draftFromMessage,
  patchFromDraft,
  type DetailEditDraft,
} from "@/components/MessageDetailEdit";
import { MessageCalendar } from "@/components/MessageCalendar";
import { toast } from "sonner";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type AnalyzedMessage, type MessageSourceInfo, type RawMessage, type RawMessageDraft,
} from "@/lib/api";
import {
  EFFECT_LABEL, EFFECT_STATUS_OPTIONS, FRESHNESS_LABEL, IMPACT_LABEL, STATUS_LABEL,
  effectiveAt, endAt, formatMarkLabel, getDefaultEndDays, hasExplicitEndAt, keywordHint,
  monthRange, setDefaultEndDays, targetHint, targetTitle,
} from "@/lib/messages";
import { hasLlm, messageAnalyzeRun } from "@/lib/messageAnalyze";
import { Link } from "react-router-dom";
import { StockLabel } from "@/components/stock/StockLabel";
import { BlockLabel } from "@/components/block/BlockLabel";
import { BlockResolveScope } from "@/components/block/BlockResolveContext";

const PAGE_SIZE = 100;
const CALENDAR_LIMIT = 1000;
const HIDDEN_SOURCE_IDS = new Set(["paste", "structured"]);

type ViewMode = "calendar" | "list";

function nowStorageDatetime(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function toDatetimeLocal(value: string): string {
  if (!value) return "";
  const m = value.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
  return m ? `${m[1]}T${m[2]}` : "";
}

function fromDatetimeLocal(value: string): string {
  if (!value) return "";
  const normalized = value.replace("T", " ");
  return normalized.length === 16 ? `${normalized}:00` : normalized;
}

const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  info: (msg: string) => toast.info(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

const SORTABLE_COLS = new Set(["produced_at", "title", "impact_level", "effect_status"]);

const sortThLabelCls = "text-xs font-semibold uppercase tracking-wide";

const IMPACT_BADGE: Record<string, string> = {
  critical: "bg-danger/15 text-danger border-danger/30",
  high: "bg-primary/15 text-primary border-primary/30",
  medium: "bg-muted text-foreground border-border",
  low: "bg-muted/60 text-muted-foreground border-border/60",
  noise: "bg-muted/40 text-muted-foreground border-border/40",
};

const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const inputCls =
  "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground";

function FilterMultiSelect({
  placeholder,
  options,
  selected,
  onChange,
}: {
  placeholder: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; minWidth: number } | null>(null);

  const updateMenuPos = useCallback(() => {
    const btn = btnRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    setMenuPos({ top: rect.bottom + 4, left: rect.left, minWidth: Math.max(rect.width, 160) });
  }, []);

  useEffect(() => {
    if (!open) {
      setMenuPos(null);
      return;
    }
    updateMenuPos();
    window.addEventListener("scroll", updateMenuPos, true);
    window.addEventListener("resize", updateMenuPos);
    return () => {
      window.removeEventListener("scroll", updateMenuPos, true);
      window.removeEventListener("resize", updateMenuPos);
    };
  }, [open, updateMenuPos]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (rootRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const label = useMemo(() => {
    if (!selected.length) return placeholder;
    if (selected.length === 1) {
      return options.find((o) => o.value === selected[0])?.label || selected[0];
    }
    return `已选 ${selected.length} 项`;
  }, [selected, options, placeholder]);

  const toggle = (value: string) => {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );
  };

  const menu = open && menuPos && (
    <div
      ref={menuRef}
      className="fixed z-[80] max-h-[min(320px,calc(100vh-1rem))] overflow-auto rounded-lg border border-border bg-background py-1 shadow-lg"
      style={{ top: menuPos.top, left: menuPos.left, minWidth: menuPos.minWidth }}
    >
      {selected.length > 0 && (
        <button
          type="button"
          className="w-full px-3 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          onClick={() => onChange([])}
        >
          清除选择
        </button>
      )}
      {options.map((o) => (
        <label
          key={o.value}
          className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/50"
        >
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
            checked={selected.includes(o.value)}
            onChange={() => toggle(o.value)}
          />
          <span className="text-foreground">{o.label}</span>
        </label>
      ))}
    </div>
  );

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={btnRef}
        type="button"
        className={cn(
          selectCls,
          "inline-flex min-w-[120px] items-center justify-between gap-2",
          selected.length > 0 && "border-primary/40 text-primary",
        )}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="truncate">{label}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {menu && createPortal(menu, document.body)}
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
      {children}
    </span>
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

function ImpactBadge({ level }: { level: string }) {
  return (
    <Badge className={IMPACT_BADGE[level] || IMPACT_BADGE.medium}>
      {IMPACT_LABEL[level] || level}
    </Badge>
  );
}

function EffectBadge({ status }: { status: string }) {
  return (
    <Badge className="border-border bg-muted/50 text-foreground">
      {EFFECT_LABEL[status] || status}
    </Badge>
  );
}

function MessageKeywords({ item }: { item: AnalyzedMessage }) {
  if (item.source_id === "xgb_msgs" || !item.keywords.length) {
    return <span className="text-muted-foreground">—</span>;
  }
  const shown = item.keywords.slice(0, 2);
  const rest = item.keywords.length - shown.length;
  const allHint = item.keywords.join("、");
  return (
    <div className="flex flex-wrap gap-1" title={`${keywordHint(item.source_id)}：${allHint}`}>
      {shown.map((k) => (
        <Badge key={k} className="border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-200">
          {k}
        </Badge>
      ))}
      {rest > 0 && (
        <Badge className="border-border bg-muted/40 text-muted-foreground" title={allHint}>
          其他{rest}个
        </Badge>
      )}
    </div>
  );
}

function sortMessageTargets(targets: AnalyzedMessage["targets"]) {
  return [...targets].sort((a, b) => {
    const rank = (t: (typeof targets)[number]) => (t.kind === "stock" ? 0 : 1);
    return rank(a) - rank(b);
  });
}

function MessageTargetBadge({ t }: { t: AnalyzedMessage["targets"][number] }) {
  if (t.kind === "stock" && t.code) {
    return (
      <Badge
        className="border-primary/30 bg-primary/10 text-foreground"
        title={targetHint(t)}
      >
        <StockLabel code={t.code} name={t.name} variant="inline" />
      </Badge>
    );
  }
  if (t.kind === "sector" || t.kind === "theme") {
    return (
      <Badge
        className="border-amber-500/30 bg-amber-500/10 p-0 text-foreground"
        title={targetHint(t)}
      >
        <BlockLabel name={targetTitle(t)} variant="tag" className="border-0 bg-transparent" />
      </Badge>
    );
  }
  return (
    <Badge className="border-border bg-background text-foreground" title={targetHint(t)}>
      {targetTitle(t)}
    </Badge>
  );
}

function MessageTargets({ item, max = 4 }: { item: AnalyzedMessage; max?: number }) {
  if (!item.targets.length) return <span className="text-muted-foreground">—</span>;
  const targets = sortMessageTargets(item.targets);
  return (
    <div className="flex flex-wrap gap-1">
      {targets.slice(0, max).map((t, i) => (
        <MessageTargetBadge key={`${t.name}-${i}`} t={t} />
      ))}
    </div>
  );
}

function DetailSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
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

export function MessageAnalysis() {
  const [sources, setSources] = useState<MessageSourceInfo[]>([]);
  const [items, setItems] = useState<AnalyzedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [pollingCls, setPollingCls] = useState(false);
  const pollInFlight = useRef(false);

  const [q, setQ] = useState("");
  const [sourcesFilter, setSourcesFilter] = useState<string[]>([]);
  const [impactLevels, setImpactLevels] = useState<string[]>([]);
  const [effectStatuses, setEffectStatuses] = useState<string[]>([]);
  const [followedFilter, setFollowedFilter] = useState<string[]>([]);
  const [favoritedFilter, setFavoritedFilter] = useState<string[]>([]);
  const [sort, setSort] = useState("produced_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const nowInit = useMemo(() => new Date(), []);
  const [calendarYear, setCalendarYear] = useState(nowInit.getFullYear());
  const [calendarMonth, setCalendarMonth] = useState(nowInit.getMonth());
  const [calendarItems, setCalendarItems] = useState<AnalyzedMessage[]>([]);
  const [calendarTotal, setCalendarTotal] = useState(0);
  const [calendarLoading, setCalendarLoading] = useState(false);

  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestFormat, setIngestFormat] = useState<"plain" | "structured" | "calendar">("plain");
  const [ingestText, setIngestText] = useState("");
  const [drafts, setDrafts] = useState<RawMessageDraft[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);
  const [ingestMetaOpen, setIngestMetaOpen] = useState(false);
  const [ingestMetaSourceLabel, setIngestMetaSourceLabel] = useState("手动录入");
  const [ingestMetaProducedAt, setIngestMetaProducedAt] = useState(() => nowStorageDatetime());

  const [selected, setSelected] = useState<AnalyzedMessage | null>(null);
  const [rawMessages, setRawMessages] = useState<RawMessage[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState<DetailEditDraft | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [defaultEndDays, setDefaultEndDaysState] = useState(() => getDefaultEndDays());

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageFrom = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageTo = Math.min(page * PAGE_SIZE, total);

  const hasActiveFilters = useMemo(
    () =>
      q.trim() !== "" ||
      sourcesFilter.length > 0 ||
      impactLevels.length > 0 ||
      effectStatuses.length > 0 ||
      followedFilter.length > 0 ||
      favoritedFilter.length > 0,
    [q, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter],
  );

  const resetFilters = () => {
    setPage(1);
    setQ("");
    setSourcesFilter([]);
    setImpactLevels([]);
    setEffectStatuses([]);
    setFollowedFilter([]);
    setFavoritedFilter([]);
  };

  const onDefaultEndDaysChange = (days: number) => {
    setDefaultEndDays(days);
    setDefaultEndDaysState(days);
  };

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.messageAnalyzedList({
        q: q.trim() || undefined,
        source: sourcesFilter.length ? sourcesFilter : undefined,
        impact_level: impactLevels.length ? impactLevels : undefined,
        effect_status: effectStatuses.length ? effectStatuses : undefined,
        followed: followedFilter.length ? followedFilter : undefined,
        favorited: favoritedFilter.length ? favoritedFilter : undefined,
        sort,
        order,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [q, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter, sort, order, page]);

  const loadCalendar = useCallback(async () => {
    setCalendarLoading(true);
    try {
      const range = monthRange(calendarYear, calendarMonth);
      const data = await api.messageAnalyzedList({
        q: q.trim() || undefined,
        source: sourcesFilter.length ? sourcesFilter : undefined,
        impact_level: impactLevels.length ? impactLevels : undefined,
        effect_status: effectStatuses.length ? effectStatuses : undefined,
        followed: followedFilter.length ? followedFilter : undefined,
        favorited: favoritedFilter.length ? favoritedFilter : undefined,
        from_dt: range.from_dt,
        to_dt: range.to_dt,
        sort: "produced_at",
        order: "asc",
        limit: CALENDAR_LIMIT,
        offset: 0,
      });
      setCalendarItems(data.items || []);
      setCalendarTotal(data.total || 0);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "日历加载失败");
    } finally {
      setCalendarLoading(false);
    }
  }, [calendarYear, calendarMonth, q, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter]);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (total > 0 && page > maxPage) setPage(maxPage);
  }, [total, page]);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api.messageSources());
    } catch {
      /* 来源列表失败不阻塞主列表 */
    }
  }, []);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  useEffect(() => {
    if (viewMode === "list") loadList();
  }, [loadList, viewMode]);

  useEffect(() => {
    if (viewMode === "calendar") loadCalendar();
  }, [loadCalendar, viewMode]);

  const refreshMessages = useCallback(async () => {
    if (viewMode === "calendar") await loadCalendar();
    else await loadList();
  }, [viewMode, loadCalendar, loadList]);

  const loadDetail = useCallback(async (item: AnalyzedMessage) => {
    setSelected(item);
    setRawMessages([]);
    setDetailLoading(true);
    try {
      const detail = await api.messageAnalyzedDetail(item.id);
      setSelected(detail);
      setRawMessages(detail.raw_messages || []);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const selectItem = (item: AnalyzedMessage) => {
    setEditing(false);
    setEditDraft(null);
    void loadDetail(item);
  };

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
      setItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      setCalendarItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      setSelected(updated);
      setEditing(false);
      setEditDraft(null);
      notify.success("已保存人工修正");
      await loadDetail(updated);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setSaveLoading(false);
    }
  };

  const clsSource = useMemo(() => sources.find((s) => s.id === "cls_telegraph"), [sources]);
  const xgbSource = useMemo(() => sources.find((s) => s.id === "xgb_msgs"), [sources]);
  const sourceFilterOptions = useMemo(
    () => sources
      .filter((s) => !HIDDEN_SOURCE_IDS.has(s.id))
      .map((s) => ({ value: s.id, label: s.label })),
    [sources],
  );

  const toggleSort = (col: string) => {
    if (!SORTABLE_COLS.has(col)) return;
    setPage(1);
    if (sort === col) setOrder((o) => (o === "desc" ? "asc" : "desc"));
    else {
      setSort(col);
      setOrder("desc");
    }
  };

  const runPreview = async () => {
    setPreviewLoading(true);
    try {
      let parsedItems: Record<string, unknown>[] | undefined;
      if (ingestFormat === "structured" && ingestText.trim()) {
        parsedItems = JSON.parse(ingestText) as Record<string, unknown>[];
        if (!Array.isArray(parsedItems)) parsedItems = [parsedItems];
      }
      const rows = await api.messageIngestPreview({
        format: ingestFormat,
        source_id: ingestFormat === "calendar" ? "calendar" : "manual",
        text: ingestFormat !== "structured" ? ingestText : undefined,
        items: parsedItems,
        options: { split_mode: "auto" },
      });
      setDrafts(rows);
      notify.success(`解析成功，共 ${rows.length} 条`);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "解析预览失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const closeIngest = () => {
    setIngestOpen(false);
    setIngestMetaOpen(false);
  };

  const openIngest = () => {
    setIngestMetaSourceLabel("手动录入");
    setIngestMetaProducedAt(nowStorageDatetime());
    setIngestMetaOpen(false);
    setIngestOpen(true);
  };

  const applyIngestMeta = (rows: RawMessageDraft[]): RawMessageDraft[] => {
    const label = ingestMetaSourceLabel.trim() || "手动录入";
    const produced = fromDatetimeLocal(toDatetimeLocal(ingestMetaProducedAt)) || ingestMetaProducedAt.trim() || nowStorageDatetime();
    return rows.map((d) => ({
      ...d,
      source_id: "manual",
      source_label: label,
      produced_at: produced,
    }));
  };

  const runCommit = async (rows?: RawMessageDraft[]) => {
    const toCommit = rows ?? drafts;
    if (!toCommit.length) return;
    setCommitLoading(true);
    try {
      const n = toCommit.length;
      await api.messageIngestCommit(toCommit);
      setDrafts([]);
      setIngestText("");
      setIngestMetaOpen(false);
      setIngestOpen(false);
      notify.success(`已入库 ${n} 条`);
      await refreshMessages();
      await loadSources();
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "入库失败");
    } finally {
      setCommitLoading(false);
    }
  };

  const requestCommit = () => {
    if (!drafts.length) return;
    if (ingestFormat === "plain" || ingestFormat === "structured") {
      setIngestMetaSourceLabel((v) => v.trim() || "手动录入");
      setIngestMetaProducedAt((v) => v.trim() || nowStorageDatetime());
      setIngestMetaOpen(true);
      return;
    }
    void runCommit();
  };

  const confirmCommitWithMeta = () => {
    void runCommit(applyIngestMeta(drafts));
  };

  const removeDraft = (key: string) => setDrafts((d) => d.filter((x) => x.draft_key !== key));

  const pollCls = useCallback(async (opts?: { silent?: boolean }) => {
    if (pollInFlight.current) return;
    pollInFlight.current = true;
    setPollingCls(true);
    try {
      const r = await api.messagePollCls();
      if (r.inserted > 0) {
        notify.success(`财联社 +${r.inserted} 条（新增候选 ${r.new_candidates}）`);
        await refreshMessages();
        await loadSources();
      } else if (!opts?.silent) {
        notify.info(`财联社已同步 · 拉取 ${r.fetched} 条 · 无新增`);
      }
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "财联社同步失败");
    } finally {
      pollInFlight.current = false;
      setPollingCls(false);
    }
  }, [refreshMessages, loadSources]);

  useEffect(() => {
    if (!autoRefresh) return;
    void pollCls({ silent: true });
    const timer = window.setInterval(() => {
      void pollCls({ silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, pollCls]);

  const pollXgb = async () => {
    try {
      const r = await api.messagePollXgb();
      const synced = await api.messageXgbResyncTargets();
      notify.success(`拉取 ${r.fetched} 条，入库/更新 ${r.inserted} 条，同步标的 ${synced.synced} 条`);
      await refreshMessages();
      await loadSources();
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "轮询失败");
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const pageIds = useMemo(() => items.map((x) => x.id), [items]);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id));
  const somePageSelected = pageIds.some((id) => selectedIds.has(id));

  const toggleSelectAllPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        pageIds.forEach((id) => next.delete(id));
      } else {
        pageIds.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const runFavorite = async (ids: string[], favorited: boolean) => {
    if (!ids.length) return;
    setBatchBusy(true);
    try {
      const r = await api.messageAnalyzedFavorite(ids, favorited);
      notify.success(favorited ? `已收藏 ${r.updated} 条` : `已取消收藏 ${r.updated} 条`);
      setItems((list) =>
        list.map((x) => (ids.includes(x.id) ? { ...x, favorited } : x)),
      );
      setCalendarItems((list) =>
        list.map((x) => (ids.includes(x.id) ? { ...x, favorited } : x)),
      );
      setSelected((cur) => (cur && ids.includes(cur.id) ? { ...cur, favorited } : cur));
      setSelectedIds(new Set());
      if (favoritedFilter.length) await refreshMessages();
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : favorited ? "收藏失败" : "取消收藏失败");
    } finally {
      setBatchBusy(false);
    }
  };

  const runDelete = async (ids: string[]) => {
    if (!ids.length) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 条消息？此操作不可恢复。`)) return;
    setBatchBusy(true);
    try {
      const r = await api.messageAnalyzedDelete(ids);
      notify.success(`已删除 ${r.deleted} 条`);
      setSelectedIds(new Set());
      if (selected && ids.includes(selected.id)) {
        setSelected(null);
        setRawMessages([]);
      }
      setCalendarItems((list) => list.filter((x) => !ids.includes(x.id)));
      await refreshMessages();
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setBatchBusy(false);
    }
  };

  const queueFavorite = () => runFavorite(Array.from(selectedIds), true);
  const queueUnfavorite = () => runFavorite(Array.from(selectedIds), false);
  const queueDelete = () => runDelete(Array.from(selectedIds));

  const runAnalyze = async (ids: string[]) => {
    if (!ids.length) return;
    if (!hasLlm()) {
      notify.error("请先在「接入 AI」配置模型后再分析");
      return;
    }
    setAnalyzing(true);
    setAnalyzeProgress(null);
    try {
      const result = await messageAnalyzeRun(ids, [], {
        onProgress: (p) => setAnalyzeProgress(`${p.current} / ${p.total}`),
        onItem: (item) => {
          setItems((list) => list.map((x) => (x.id === item.id ? item : x)));
          setCalendarItems((list) => list.map((x) => (x.id === item.id ? item : x)));
          setSelected((cur) => {
            if (cur?.id === item.id) void loadDetail(item);
            return cur?.id === item.id ? item : cur;
          });
        },
      });
      notify.success(`AI 分析完成：成功 ${result.ok} 条${result.failed ? `，失败 ${result.failed} 条` : ""}`);
      if (result.failed) {
        notify.error(result.errors.map((e) => `${e.id}: ${e.message}`).join("；"));
      }
      setSelectedIds(new Set());
      await refreshMessages();
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
      setAnalyzeProgress(null);
    }
  };

  const queueAnalyze = () => runAnalyze(Array.from(selectedIds));

  const confirmItem = async (item: AnalyzedMessage) => {
    try {
      const updated = await api.messageAnalyzedPatch(item.id, { status: "confirmed" });
      setItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      if (selected?.id === updated.id) {
        setSelected(updated);
        void loadDetail(updated);
      }
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "更新失败");
    }
  };

  const blockNames = useMemo(() => {
    const names: string[] = [];
    const pool = [...items, ...calendarItems];
    if (selected) pool.push(selected);
    for (const item of pool) {
      for (const t of item.targets) {
        if ((t.kind === "sector" || t.kind === "theme") && t.name) names.push(t.name);
      }
    }
    return names;
  }, [items, calendarItems, selected]);

  return (
    <BlockResolveScope names={blockNames}>
    <div className="w-full min-w-0 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Newspaper className="h-6 w-6 text-primary" />
            消息分析
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            多源快讯归集与标注 · 主源财联社电报 · 辅助信息整理，不构成投资建议
            {clsSource?.last_poll_at && ` · 财联社同步 ${clsSource.last_poll_at}`}
            {clsSource?.last_error && (
              <span className="text-danger"> · 同步异常：{clsSource.last_error}</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-4 py-2 text-sm font-semibold transition-opacity hover:bg-muted/50",
              autoRefresh
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border bg-background text-foreground",
            )}
          >
            {autoRefresh ? (
              pollingCls ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radio className="h-4 w-4" />
            ) : (
              <Radio className="h-4 w-4" />
            )}
            {autoRefresh ? "自动刷新中 · 5s" : "自动刷新"}
          </button>
          <button
            type="button"
            onClick={() => pollCls()}
            disabled={pollingCls}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-50"
          >
            {pollingCls ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            拉财联社
          </button>
          <button
            type="button"
            onClick={pollXgb}
            className="flex items-center gap-1.5 rounded-lg border border-border/60 bg-background px-3 py-2 text-xs font-medium text-muted-foreground transition-opacity hover:bg-muted/50 hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            拉选股宝
          </button>
          <button
            type="button"
            onClick={openIngest}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground transition-opacity hover:bg-muted/50"
          >
            <Plus className="h-4 w-4 text-primary" />
            录入消息
          </button>
          <button
            type="button"
            onClick={() => refreshMessages()}
            disabled={loading || calendarLoading}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {(loading || calendarLoading) ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {(loading || calendarLoading) ? "加载中…" : "刷新"}
          </button>
        </div>
      </div>

      <Disclaimer />

      <section className="w-full min-w-0">
        <div className="mb-2">
          <SectionLabel>筛选 · Filter</SectionLabel>
        </div>
        <div className="glass w-full rounded-2xl p-4 lg:p-5">
          <div className="relative w-full">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              className={inputCls}
              placeholder="搜索标题、摘要、关键词…"
              value={q}
              onChange={(e) => {
                setPage(1);
                setQ(e.target.value);
              }}
              onKeyDown={(e) => e.key === "Enter" && refreshMessages()}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 lg:gap-3">
            <FilterMultiSelect
              placeholder="全部来源"
              options={sourceFilterOptions}
              selected={sourcesFilter}
              onChange={(v) => {
                setPage(1);
                setSourcesFilter(v);
              }}
            />
            <FilterMultiSelect
              placeholder="全部级别"
              options={Object.entries(IMPACT_LABEL).map(([k, v]) => ({ value: k, label: v }))}
              selected={impactLevels}
              onChange={(v) => {
                setPage(1);
                setImpactLevels(v);
              }}
            />
            <FilterMultiSelect
              placeholder="全部生效"
              options={EFFECT_STATUS_OPTIONS.map((k) => ({ value: k, label: EFFECT_LABEL[k] }))}
              selected={effectStatuses}
              onChange={(v) => {
                setPage(1);
                setEffectStatuses(v);
              }}
            />
            <FilterMultiSelect
              placeholder="全部关注"
              options={[
                { value: "yes", label: "已关注" },
                { value: "no", label: "未关注" },
              ]}
              selected={followedFilter}
              onChange={(v) => {
                setPage(1);
                setFollowedFilter(v);
              }}
            />
            <FilterMultiSelect
              placeholder="全部收藏"
              options={[
                { value: "yes", label: "已收藏" },
                { value: "no", label: "未收藏" },
              ]}
              selected={favoritedFilter}
              onChange={(v) => {
                setPage(1);
                setFavoritedFilter(v);
              }}
            />
            <button
              type="button"
              disabled={!hasActiveFilters}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-sm font-semibold text-muted-foreground transition-opacity hover:bg-muted/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              onClick={resetFilters}
            >
              <RotateCcw className="h-3.5 w-3.5" />
              重置筛选
            </button>
            <div className="ml-auto flex min-w-[220px] max-w-full flex-1 items-center gap-3 sm:flex-none">
              <label
                htmlFor="default-end-days"
                className="shrink-0 text-xs font-semibold text-muted-foreground"
                title="未设结束时间的消息，在展示与后续计算中按生效时间加 N 天"
              >
                默认有效期
              </label>
              <input
                id="default-end-days"
                type="range"
                min={1}
                max={15}
                step={1}
                value={defaultEndDays}
                onChange={(e) => onDefaultEndDaysChange(Number(e.target.value))}
                className="h-1.5 w-28 min-w-[6rem] flex-1 cursor-pointer accent-[hsl(var(--primary))]"
              />
              <span className="w-10 shrink-0 text-xs tabular-nums text-foreground">{defaultEndDays} 天</span>
            </div>
            {selectedIds.size > 0 && (
              <>
                <button
                  type="button"
                  disabled={analyzing}
                  className="flex items-center gap-1.5 rounded-lg bg-primary/90 px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
                  onClick={queueAnalyze}
                >
                  {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  AI 分析 ({selectedIds.size})
                </button>
                <button
                  type="button"
                  disabled={batchBusy}
                  className="flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-800 dark:text-amber-200 disabled:opacity-50"
                  onClick={queueFavorite}
                >
                  {batchBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Star className="h-4 w-4" />}
                  收藏 ({selectedIds.size})
                </button>
                <button
                  type="button"
                  disabled={batchBusy}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-2 text-sm font-semibold text-muted-foreground hover:text-foreground disabled:opacity-50"
                  onClick={queueUnfavorite}
                >
                  取消收藏 ({selectedIds.size})
                </button>
                <button
                  type="button"
                  disabled={batchBusy}
                  className="flex items-center gap-1.5 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm font-semibold text-danger disabled:opacity-50"
                  onClick={queueDelete}
                >
                  {batchBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  删除 ({selectedIds.size})
                </button>
              </>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              共 <strong className="text-foreground">{viewMode === "calendar" ? calendarTotal : total}</strong> 条
              {viewMode === "list" && total > 0 && (
                <> · 当前 {pageFrom}–{pageTo}</>
              )}
              {viewMode === "calendar" && calendarTotal > CALENDAR_LIMIT && (
                <> · 日历仅展示前 {CALENDAR_LIMIT} 条</>
              )}
            </span>
            {analyzeProgress && (
              <span className="text-primary">AI 分析进度 {analyzeProgress}</span>
            )}
            {!hasLlm() && (
              <Link to="/settings" className="text-primary hover:underline">
                尚未接入 AI → 去配置
              </Link>
            )}
            {xgbSource?.last_error && (
              <span className="text-danger">选股宝：{xgbSource.last_error}</span>
            )}
          </div>
        </div>
      </section>

      <section className="w-full min-w-0">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-baseline gap-3">
            <SectionLabel>消息 · Messages</SectionLabel>
            {viewMode === "list" && (
              <p className="text-xs text-muted-foreground">
                橘黄数字 = <code className="text-foreground">keywords</code>（选股宝 SubjIds 主题频道 ID）；
                详情里 <code className="text-foreground">impact:N</code> = 选股宝 Impact 方向，存于 marks
              </p>
            )}
          </div>
          <div className="flex items-center gap-1 rounded-lg border border-border bg-background p-0.5">
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
                viewMode === "calendar"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setViewMode("calendar")}
            >
              <CalendarDays className="h-3.5 w-3.5" />
              日历
            </button>
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
                viewMode === "list"
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setViewMode("list")}
            >
              <LayoutList className="h-3.5 w-3.5" />
              列表
            </button>
          </div>
        </div>
        <div className="grid w-full min-w-0 gap-4 xl:grid-cols-3">
          <div className="glass min-w-0 overflow-hidden rounded-2xl xl:col-span-2">
            {viewMode === "calendar" ? (
              <div className="max-h-[calc(100vh-220px)] overflow-auto p-4">
                <MessageCalendar
                  year={calendarYear}
                  month={calendarMonth}
                  items={calendarItems}
                  loading={calendarLoading}
                  selectedId={selected?.id}
                  onMonthChange={(y, m) => {
                    setCalendarYear(y);
                    setCalendarMonth(m);
                  }}
                  onSelect={selectItem}
                />
              </div>
            ) : (
            <>
            <div className="max-h-[calc(100vh-220px)] overflow-auto">
              {items.length === 0 && !loading && (
                <p className="p-8 text-center text-sm text-muted-foreground">
                  暂无消息，可点击「录入消息」或拉取财联社
                </p>
              )}
              {loading && items.length === 0 && (
                <div className="flex items-center justify-center gap-2 p-12 text-sm text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  加载消息…
                </div>
              )}
              {items.length > 0 && (
                <table className="w-full min-w-[960px] border-collapse text-sm">
                  <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
                    <tr className="border-b border-border/60">
                      <th className="w-10 px-3 py-2.5">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-[hsl(var(--primary))]"
                          checked={allPageSelected}
                          ref={(el) => {
                            if (el) el.indeterminate = !allPageSelected && somePageSelected;
                          }}
                          onChange={toggleSelectAllPage}
                          aria-label="全选当前页"
                        />
                      </th>
                      <SortTh col="produced_at" label="产生时间" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("produced_at")} className="w-32 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <th className="w-32 px-3 py-2.5 text-left align-middle">
                        <span className={sortThLabelCls}>生效时间</span>
                      </th>
                      <th className="w-32 px-3 py-2.5 text-left align-middle">
                        <span className={sortThLabelCls}>结束时间</span>
                      </th>
                      <SortTh col="title" label="标题" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("title")} className="min-w-[240px] max-w-[360px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="source" label="来源" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("source")} className="w-24 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="impact_level" label="级别" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("impact_level")} className="w-20 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="effect_status" label="生效情况" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("effect_status")} className="w-24 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="followed" label="关注" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("followed")} className="w-20 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="keywords" label="关键词" hint="粘贴/结构化录入的关键词" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("keywords")} className="min-w-[140px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="targets" label="关联标的" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("targets")} className="min-w-[160px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr
                        key={item.id}
                        className={cn(
                          "cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/25",
                          selected?.id === item.id && "bg-primary/8",
                        )}
                        onClick={() => selectItem(item)}
                      >
                        <td className="px-3 py-3 align-top" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[hsl(var(--primary))]"
                            checked={selectedIds.has(item.id)}
                            onChange={() => toggleSelect(item.id)}
                          />
                        </td>
                        <td className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {item.produced_at}
                        </td>
                        <td className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {item.effective_mode === "scheduled" && item.effective_at
                            ? item.effective_at
                            : effectiveAt(item)}
                        </td>
                        <td
                          className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap"
                          title={hasExplicitEndAt(item) ? undefined : `默认 ${defaultEndDays} 天`}
                        >
                          {endAt(item, defaultEndDays)}
                          {!hasExplicitEndAt(item) && (
                            <span className="ml-0.5 text-[10px] text-muted-foreground/70">*</span>
                          )}
                        </td>
                        <td className="px-3 py-3 align-top max-w-[360px]">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {item.favorited && (
                              <Star className="h-3.5 w-3.5 shrink-0 fill-amber-500 text-amber-500" aria-label="已收藏" />
                            )}
                            {item.marks.includes("highlight") && (
                              <Badge className="border-danger/40 bg-danger/15 text-danger">标红</Badge>
                            )}
                            <span className="font-semibold leading-snug text-foreground line-clamp-2">
                              {item.title || "—"}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-3 align-top text-xs text-muted-foreground">
                          {item.source_label}
                        </td>
                        <td className="px-3 py-3 align-top">
                          <ImpactBadge level={item.impact_level} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <EffectBadge status={item.effect_status} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          {item.followed ? (
                            <div className="space-y-1">
                              <Badge className="border-primary/40 bg-primary/15 text-primary">关注</Badge>
                              {(item.matched_follow_keywords?.length ?? 0) > 0 && (
                                <div className="flex flex-wrap gap-0.5">
                                  {item.matched_follow_keywords!.slice(0, 3).map((k) => (
                                    <span key={k} className="text-[10px] text-primary/80">{k}</span>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3 align-top">
                          <MessageKeywords item={item} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <MessageTargets item={item} max={3} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {total > PAGE_SIZE && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 px-4 py-3">
                <span className="text-xs text-muted-foreground">
                  第 {page} / {totalPages} 页 · 每页 {PAGE_SIZE} 条
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={page <= 1 || loading}
                    className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-40"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    disabled={page >= totalPages || loading}
                    className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-40"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
            </>
            )}
          </div>

          <div className="glass min-w-0 rounded-2xl p-4 xl:col-span-1 max-h-[calc(100vh-220px)] overflow-auto">
            {!selected ? (
              <p className="py-12 text-center text-sm text-muted-foreground">选择消息查看详情</p>
            ) : (
              <div className="space-y-4">
                <div className="space-y-3 border-b border-border/60 pb-4">
                  <div className="min-w-0">
                    <h2 className="text-base font-bold leading-snug text-foreground">
                      {selected.title || "—"}
                    </h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {selected.source_label} · {STATUS_LABEL[selected.status] || selected.status}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {selected.status !== "confirmed" && (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
                        onClick={() => confirmItem(selected)}
                      >
                        <Check className="h-3.5 w-3.5" /> 确认
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={batchBusy}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-semibold disabled:opacity-40",
                        selected.favorited
                          ? "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200"
                          : "border-border bg-background text-foreground",
                      )}
                      onClick={() => runFavorite([selected.id], !selected.favorited)}
                    >
                      <Star className={cn("h-3.5 w-3.5", selected.favorited && "fill-current")} />
                      {selected.favorited ? "取消收藏" : "收藏"}
                    </button>
                    <button
                      type="button"
                      disabled={batchBusy}
                      className="inline-flex items-center gap-1 rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-xs font-semibold text-danger disabled:opacity-40"
                      onClick={() => runDelete([selected.id])}
                    >
                      <Trash2 className="h-3.5 w-3.5" /> 删除
                    </button>
                    <button
                      type="button"
                      disabled={analyzing || !hasLlm() || editing}
                      className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground disabled:opacity-40"
                      onClick={() => runAnalyze([selected.id])}
                    >
                      {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      AI 分析
                    </button>
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

                <DetailSection label="关注">
                  {selected.followed ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className="border-primary/40 bg-primary/15 text-primary">已命中</Badge>
                      {(selected.matched_follow_keywords?.length ?? 0) > 0 ? (
                        selected.matched_follow_keywords!.map((k) => (
                          <Badge key={k} className="border-primary/30 bg-primary/10 text-primary">{k}</Badge>
                        ))
                      ) : (
                        <span className="text-sm text-muted-foreground">已关注，无匹配词</span>
                      )}
                    </div>
                  ) : (
                    <span className="text-sm text-muted-foreground">未命中关注词</span>
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
                    <dd className="text-foreground">{IMPACT_LABEL[selected.impact_level]}</dd>
                    <dt className="text-muted-foreground">新旧</dt>
                    <dd className="text-foreground">{FRESHNESS_LABEL[selected.freshness]}</dd>
                    <dt className="text-muted-foreground">炒作</dt>
                    <dd className="text-foreground">{EFFECT_LABEL[selected.effect_status]}</dd>
                  </dl>
                </div>

                {selected.targets.length > 0 && (
                  <DetailSection label="影响标的">
                    <div className="flex flex-wrap gap-2">
                      {sortMessageTargets(selected.targets).map((t, i) => (
                        <MessageTargetBadge key={i} t={t} />
                      ))}
                    </div>
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
            )}
          </div>
        </div>
      </section>

      {ingestOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
          onClick={closeIngest}
        >
          <div
            className={cn("glass flex max-h-[min(90vh,720px)] w-full flex-col p-5", drafts.length > 0 ? "max-w-3xl" : "max-w-2xl")}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-foreground">录入消息</h2>
              <button
                type="button"
                disabled={previewLoading || commitLoading}
                onClick={closeIngest}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-auto">
              <div className="flex flex-wrap gap-2">
                {(["plain", "structured", "calendar"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors",
                      ingestFormat === f
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => setIngestFormat(f)}
                  >
                    {f === "plain" ? "文字粘贴" : f === "structured" ? "JSON" : "财经日历"}
                  </button>
                ))}
              </div>
              <textarea
                className="min-h-[160px] w-full resize-y rounded-xl border border-border bg-background p-3 text-sm font-mono text-foreground placeholder:text-muted-foreground"
                placeholder={
                  ingestFormat === "plain"
                    ? "粘贴大段文字，系统将按空行/分隔符拆分…"
                    : ingestFormat === "calendar"
                      ? '{"meta":{"title":"…","month":9,"year":2026,"source":{"name":"…"},"disclaimer":"…"},"legend":[],"events":[{"id":"…","startTime":1759161600000,"title":"…","importanceLevel":4,"category":"必看大事","targets":[{"type":"sector","name":"…","code":""}]}]}'
                      : '[{"title":"…","content":"…","url":"…","keywords":["…"],"marks":["highlight"]}]'
                }
                value={ingestText}
                onChange={(e) => setIngestText(e.target.value)}
              />
              {drafts.length > 0 && (
                <div className="max-h-48 overflow-auto rounded-xl border border-border/60">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-muted/80 text-xs font-semibold uppercase tracking-wide text-muted-foreground backdrop-blur">
                      <tr>
                        <th className="p-3 text-left">标题</th>
                        <th className="p-3 text-left">内容预览</th>
                        <th className="w-10 p-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {drafts.map((d) => (
                        <tr key={d.draft_key} className="border-t border-border/60">
                          <td className="p-3 align-top font-medium text-foreground">{d.title || "—"}</td>
                          <td className="p-3 align-top text-muted-foreground">{d.content.slice(0, 160)}</td>
                          <td className="p-3 align-top">
                            <button type="button" onClick={() => removeDraft(d.draft_key)} aria-label="删除">
                              <Trash2 className="h-4 w-4 text-muted-foreground hover:text-danger" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="mt-4 flex shrink-0 flex-wrap justify-end gap-2 border-t border-border/60 pt-4">
              <button
                type="button"
                disabled={previewLoading || commitLoading}
                onClick={closeIngest}
                className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-muted-foreground hover:bg-muted/50 disabled:opacity-40"
              >
                取消
              </button>
              <button
                type="button"
                disabled={previewLoading || !ingestText.trim()}
                className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground disabled:opacity-40"
                onClick={runPreview}
              >
                {previewLoading && <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />}
                预览拆分
              </button>
              {drafts.length > 0 && (
                <button
                  type="button"
                  disabled={commitLoading}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-40"
                  onClick={requestCommit}
                >
                  {commitLoading && <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />}
                  确认入库 ({drafts.length})
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {ingestMetaOpen && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-4"
          onClick={() => setIngestMetaOpen(false)}
        >
          <div
            className="glass w-full max-w-md p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-foreground">批次元数据</h2>
              <button
                type="button"
                disabled={commitLoading}
                onClick={() => setIngestMetaOpen(false)}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mb-4 text-sm text-muted-foreground">
              为本次入库的 {drafts.length} 条消息统一设置来源与产生时间（选填）。
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">数据来源</label>
                <input
                  className={inputCls}
                  placeholder="手动录入"
                  value={ingestMetaSourceLabel}
                  onChange={(e) => setIngestMetaSourceLabel(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">产生时间</label>
                <input
                  type="datetime-local"
                  className={inputCls}
                  value={toDatetimeLocal(ingestMetaProducedAt)}
                  onChange={(e) => setIngestMetaProducedAt(fromDatetimeLocal(e.target.value))}
                />
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                disabled={commitLoading}
                className="rounded-lg border border-border px-4 py-2 text-sm font-semibold text-muted-foreground hover:bg-muted/50 disabled:opacity-40"
                onClick={() => setIngestMetaOpen(false)}
              >
                返回
              </button>
              <button
                type="button"
                disabled={commitLoading}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-40"
                onClick={confirmCommitWithMeta}
              >
                {commitLoading && <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />}
                确认入库 ({drafts.length})
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </BlockResolveScope>
  );
}
