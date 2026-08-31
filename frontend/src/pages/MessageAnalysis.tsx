import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useSearchParams } from "react-router-dom";
import {
  Search, RefreshCw, Loader2, ChevronDown, ChevronUp, ChevronLeft, ChevronRight,
  Plus, Trash2, ExternalLink, Sparkles, Check, Newspaper, Radio, X, Star,
  RotateCcw, Pencil, LayoutList, CalendarDays,
} from "lucide-react";
import {
  MessageDetailEdit,
  draftFromMessage,
  patchFromDraft,
  type DetailEditDraft,
} from "@/components/MessageDetailEdit";
import { MessageCalendar } from "@/components/MessageCalendar";
import { MessageStockPipButton, MessageStockPopupButton } from "@/components/MessageStockPip";
import { toast } from "sonner";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type AnalyzedMessage, type BlockResolveItem, type EffectStatus, type Freshness, type ImpactLevel,
  type ImpactTarget, type MessageSourceInfo, type RawMessage, type RawMessageDraft,
  type StockResolveItem,
} from "@/lib/api";
import {
  EFFECT_LABEL, EFFECT_STATUS_OPTIONS, FRESHNESS_LABEL, IMPACT_LABEL, STATUS_LABEL, TARGET_KIND_LABEL,
  effectiveAt, endAt, formatMarkLabel, getDefaultEndDays, hasExplicitEndAt, keywordHint,
  monthRange, setDefaultEndDays, clampDefaultEndDays, targetHint, targetTitle,
} from "@/lib/messages";
import { hasLlm, messageAnalyzeRun } from "@/lib/messageAnalyze";
import { chatStream } from "@/lib/llm";
import {
  buildArticleIngestPrompt,
  parseArticleIngestExtract,
  type ArticleIngestExtract,
} from "@/lib/articles";
import { usePluginCurrentStock } from "@/lib/currentStockStream";
import { keywordsSettingsTo } from "@/lib/settingsNav";
import { StockLabel } from "@/components/stock/StockLabel";
import { StockResolveScope, useStockResolve, useStockResolveOptional } from "@/components/stock/StockResolveContext";
import { BlockLabel } from "@/components/block/BlockLabel";
import { BlockResolveScope, useBlockResolveOptional } from "@/components/block/BlockResolveContext";
import { isStockMatched } from "@/lib/stocks";
import { isBlockMatched } from "@/lib/thsBlocks";

const IMPACT_LEVELS: ImpactLevel[] = ["critical", "high", "medium", "low", "noise"];
const FRESHNESS_VALUES: Freshness[] = ["new", "follow_up", "duplicate", "rumor"];
const EFFECT_STATUSES: EffectStatus[] = [...EFFECT_STATUS_OPTIONS];
const quickSelectCls =
  "h-8 max-w-[7.5rem] rounded-lg border border-border bg-background px-2 text-xs font-semibold text-foreground disabled:opacity-40";

const PAGE_SIZE = 100;
const CALENDAR_LIMIT = 1000;
const SEARCH_DEBOUNCE_MS = 300;
const HIDDEN_SOURCE_IDS = new Set(["paste", "structured"]);

type ViewMode = "calendar" | "list";
type NavFocusPane = "list" | "detail";

/** 解析列表页码 URL 参数，非法或缺失时回退为第 1 页 */
function parseListPage(raw: string | null): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.floor(n);
}

/** 解析逗号分隔的多选筛选参数 */
function parseCsvParam(raw: string | null): string[] {
  if (!raw?.trim()) return [];
  return raw.split(",").map((s) => s.trim()).filter(Boolean);
}

/** 解析布尔筛选参数（yes/1/true） */
function parseFlagParam(raw: string | null): boolean {
  const v = (raw || "").trim().toLowerCase();
  return v === "yes" || v === "1" || v === "true";
}

function setCsvParam(params: URLSearchParams, key: string, values: string[]) {
  if (values.length) params.set(key, values.join(","));
  else params.delete(key);
}

function setFlagParam(params: URLSearchParams, key: string, on: boolean) {
  if (on) params.set(key, "yes");
  else params.delete(key);
}

type ListQueryPatch = {
  q?: string;
  page?: number | ((prev: number) => number);
  source?: string[];
  impact_level?: string[];
  effect_status?: string[];
  followed?: string[];
  favorited?: string[];
  follow_stock?: boolean;
  include_history?: boolean;
};

/** 输入控件内不响应条目切换快捷键 */
function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return Boolean(el.closest("[contenteditable='true']"));
}

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

/** 高/重大级别标题着色，与级别徽章文字色一致 */
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
  // 历史数据兼容
  early_hype: "bg-orange-500/12 text-orange-800 border-orange-500/35 dark:text-orange-200",
  faded: "bg-muted/50 text-muted-foreground border-border/50",
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

function ImpactBadge({ level, manual }: { level: string; manual?: boolean }) {
  return (
    <Badge className={IMPACT_BADGE[level] || IMPACT_BADGE.medium} title={manual ? "已手动指定优先级" : undefined}>
      {IMPACT_LABEL[level] || level}
      {manual ? <span className="ml-1 opacity-80">手</span> : null}
    </Badge>
  );
}

function EffectBadge({ status }: { status: string }) {
  return (
    <Badge className={EFFECT_BADGE[status] || EFFECT_BADGE.not_erupted}>
      {EFFECT_LABEL[status] || status}
    </Badge>
  );
}

/** 生成可点击页号序列，两端固定、中间窗口，超出用 gap 省略 */
function buildPageItems(current: number, total: number, radius = 2): Array<number | "gap"> {
  if (total <= 1) return [1];
  if (total <= 9) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = new Set<number>([1, total]);
  for (let p = current - radius; p <= current + radius; p += 1) {
    if (p >= 1 && p <= total) pages.add(p);
  }
  const sorted = Array.from(pages).sort((a, b) => a - b);
  const out: Array<number | "gap"> = [];
  for (let i = 0; i < sorted.length; i += 1) {
    if (i > 0 && sorted[i]! - sorted[i - 1]! > 1) out.push("gap");
    out.push(sorted[i]!);
  }
  return out;
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

/** 展示排序：已解析板块 → 已解析个股 → 未解析；股票联动命中板块按成分股从少到多（stockHitBlockNames 顺序） */
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

function MessageTargets({
  item,
  max = 4,
  stockHitBlockNames,
}: {
  item: AnalyzedMessage;
  max?: number;
  stockHitBlockNames?: string[];
}) {
  const sortTargets = useSortMessageTargets(stockHitBlockNames);
  if (!item.targets.length) return <span className="text-muted-foreground">—</span>;
  const targets = sortTargets(item.targets);
  return (
    <div className="flex flex-wrap gap-1">
      {targets.slice(0, max).map((t, i) => (
        <MessageTargetBadge key={`${t.name}-${i}`} t={t} stockHitBlockNames={stockHitBlockNames} />
      ))}
    </div>
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

function FollowStockHint({
  code,
  status,
  error,
}: {
  code: string | null;
  status: "idle" | "connecting" | "connected" | "error";
  error: string | null;
}) {
  const resolved = useStockResolve({ code });
  const name = resolved?.stock?.name?.trim() || "";
  const text = code
    ? name || code
    : status === "connecting"
      ? "连接中…"
      : status === "connected"
        ? "等待焦点股…"
        : status === "error"
          ? error || "未连接"
          : "等待插件…";
  return (
    <span className="relative inline-block min-w-[5.5rem] align-middle text-xs font-normal">
      <span className="invisible whitespace-nowrap" aria-hidden>
        八八八八八八
      </span>
      <span
        className="absolute inset-0 truncate text-right"
        title={code && name ? `${name}（${code}）` : text}
      >
        {text}
      </span>
    </span>
  );
}

export function MessageAnalysis() {
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") ?? "";
  const page = parseListPage(searchParams.get("page"));
  const sourceParam = searchParams.get("source");
  const impactParam = searchParams.get("impact_level");
  const effectParam = searchParams.get("effect_status");
  const followedParam = searchParams.get("followed");
  const favoritedParam = searchParams.get("favorited");
  const sourcesFilter = useMemo(() => parseCsvParam(sourceParam), [sourceParam]);
  const impactLevels = useMemo(() => parseCsvParam(impactParam), [impactParam]);
  const effectStatuses = useMemo(() => parseCsvParam(effectParam), [effectParam]);
  const followedFilter = useMemo(() => parseCsvParam(followedParam), [followedParam]);
  const favoritedFilter = useMemo(() => parseCsvParam(favoritedParam), [favoritedParam]);
  const followStockChange = parseFlagParam(searchParams.get("follow_stock"));
  const includeHistory = parseFlagParam(searchParams.get("include_history"));
  const [qInput, setQInput] = useState(q);

  /** 同步筛选条件 / 分页到 URL（缺省值不占参数） */
  const patchListQuery = useCallback(
    (patch: ListQueryPatch, replace = true) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if ("q" in patch) {
          const v = patch.q ?? "";
          if (v) next.set("q", v);
          else next.delete("q");
        }
        if ("page" in patch) {
          const cur = parseListPage(prev.get("page"));
          const raw = patch.page!;
          const resolved = typeof raw === "function" ? raw(cur) : raw;
          const n = Math.max(1, Math.floor(Number(resolved) || 1));
          if (n <= 1) next.delete("page");
          else next.set("page", String(n));
        }
        if ("source" in patch) setCsvParam(next, "source", patch.source ?? []);
        if ("impact_level" in patch) setCsvParam(next, "impact_level", patch.impact_level ?? []);
        if ("effect_status" in patch) setCsvParam(next, "effect_status", patch.effect_status ?? []);
        if ("followed" in patch) setCsvParam(next, "followed", patch.followed ?? []);
        if ("favorited" in patch) setCsvParam(next, "favorited", patch.favorited ?? []);
        if ("follow_stock" in patch) setFlagParam(next, "follow_stock", Boolean(patch.follow_stock));
        if ("include_history" in patch) setFlagParam(next, "include_history", Boolean(patch.include_history));
        if (next.toString() === prev.toString()) return prev;
        return next;
      }, { replace });
    },
    [setSearchParams],
  );
  const setPage = useCallback(
    (value: number | ((prev: number) => number)) => patchListQuery({ page: value }),
    [patchListQuery],
  );

  // URL → 输入框（后退 / 分享链接 / 重置）
  useEffect(() => {
    setQInput(q);
  }, [q]);

  // 输入框 → URL（防抖后再触发列表请求）
  useEffect(() => {
    if (qInput === q) return;
    const timer = window.setTimeout(() => {
      patchListQuery({ q: qInput, page: 1 });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [qInput, q, patchListQuery]);

  const [sources, setSources] = useState<MessageSourceInfo[]>([]);
  const [items, setItems] = useState<AnalyzedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [pollingCls, setPollingCls] = useState(false);
  const pollInFlight = useRef(false);

  const { code: currentStockCode, status: currentStockStatus, error: currentStockError } =
    usePluginCurrentStock(followStockChange);
  const [sort, setSort] = useState("produced_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const listScrollRef = useRef<HTMLDivElement>(null);
  const listPaneRef = useRef<HTMLDivElement>(null);
  const detailPaneRef = useRef<HTMLDivElement>(null);
  const detailReqId = useRef(0);
  const [navFocus, setNavFocus] = useState<NavFocusPane | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const nowInit = useMemo(() => new Date(), []);
  const [calendarYear, setCalendarYear] = useState(nowInit.getFullYear());
  const [calendarMonth, setCalendarMonth] = useState(nowInit.getMonth());
  const [calendarItems, setCalendarItems] = useState<AnalyzedMessage[]>([]);
  const [calendarTotal, setCalendarTotal] = useState(0);
  const [calendarLoading, setCalendarLoading] = useState(false);

  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestFormat, setIngestFormat] = useState<"plain" | "structured" | "calendar" | "article">("plain");
  const [ingestText, setIngestText] = useState("");
  const [articleExtract, setArticleExtract] = useState<ArticleIngestExtract | null>(null);
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
  const [quickPatching, setQuickPatching] = useState(false);
  const [defaultEndDays, setDefaultEndDaysState] = useState(() => getDefaultEndDays());
  const defaultEndDaysSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageItems = useMemo(() => buildPageItems(page, totalPages), [page, totalPages]);
  const pageFrom = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const pageTo = Math.min(page * PAGE_SIZE, total);

  useEffect(() => {
    listScrollRef.current?.scrollTo({ top: 0 });
  }, [page]);

  // 从后端配置加载默认有效期；无落盘时把本地缓存迁过去
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.messageDefaultEndDays();
        if (cancelled) return;
        const serverDays = clampDefaultEndDays(cfg.default_end_days);
        const localDays = getDefaultEndDays();
        if (!cfg.from_disk && localDays !== serverDays) {
          await api.saveMessageDefaultEndDays(localDays);
          if (cancelled) return;
          setDefaultEndDays(localDays);
          setDefaultEndDaysState(localDays);
        } else {
          setDefaultEndDays(serverDays);
          setDefaultEndDaysState(serverDays);
        }
      } catch {
        /* 保留 localStorage 缓存 */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (defaultEndDaysSaveTimer.current) clearTimeout(defaultEndDaysSaveTimer.current);
    };
  }, []);

  const hasActiveFilters = useMemo(
    () =>
      q.trim() !== "" ||
      qInput.trim() !== "" ||
      sourcesFilter.length > 0 ||
      impactLevels.length > 0 ||
      effectStatuses.length > 0 ||
      followedFilter.length > 0 ||
      favoritedFilter.length > 0 ||
      followStockChange ||
      includeHistory,
    [q, qInput, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter, followStockChange, includeHistory],
  );

  const resetFilters = () => {
    setQInput("");
    patchListQuery({
      q: "",
      page: 1,
      source: [],
      impact_level: [],
      effect_status: [],
      followed: [],
      favorited: [],
      follow_stock: false,
      include_history: false,
    });
  };

  const onDefaultEndDaysChange = (days: number) => {
    const n = clampDefaultEndDays(days);
    setDefaultEndDays(n);
    setDefaultEndDaysState(n);
    if (defaultEndDaysSaveTimer.current) clearTimeout(defaultEndDaysSaveTimer.current);
    defaultEndDaysSaveTimer.current = setTimeout(() => {
      void api.saveMessageDefaultEndDays(n).catch(() => {
        /* 落盘失败时仍保留本地缓存与当前筛选 */
      });
    }, 300);
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
        match_current_stock: followStockChange ? "yes" : undefined,
        include_history: includeHistory ? "yes" : undefined,
        default_end_days: defaultEndDays,
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
  }, [q, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter, followStockChange, includeHistory, defaultEndDays, currentStockCode, sort, order, page]);

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
        match_current_stock: followStockChange ? "yes" : undefined,
        include_history: includeHistory ? "yes" : undefined,
        default_end_days: defaultEndDays,
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
  }, [calendarYear, calendarMonth, q, sourcesFilter, impactLevels, effectStatuses, followedFilter, favoritedFilter, followStockChange, includeHistory, defaultEndDays, currentStockCode]);

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
    if (!selected?.id) return;
    const updated = items.find((x) => x.id === selected.id);
    if (updated) setSelected(updated);
  }, [items, selected?.id]);

  useEffect(() => {
    if (viewMode === "calendar") loadCalendar();
  }, [loadCalendar, viewMode]);

  const refreshMessages = useCallback(async () => {
    if (viewMode === "calendar") await loadCalendar();
    else await loadList();
  }, [viewMode, loadCalendar, loadList]);

  const loadDetail = useCallback(async (item: AnalyzedMessage) => {
    const reqId = ++detailReqId.current;
    setSelected(item);
    setRawMessages([]);
    setDetailLoading(true);
    try {
      const detail = await api.messageAnalyzedDetail(item.id);
      if (reqId !== detailReqId.current) return;
      setSelected(detail);
      setRawMessages(detail.raw_messages || []);
    } catch (e) {
      if (reqId !== detailReqId.current) return;
      notify.error(e instanceof ApiError ? e.message : "加载详情失败");
    } finally {
      if (reqId === detailReqId.current) setDetailLoading(false);
    }
  }, []);

  const focusNavPane = useCallback((pane: NavFocusPane) => {
    setNavFocus(pane);
    const el = pane === "list" ? listPaneRef.current : detailPaneRef.current;
    el?.focus({ preventScroll: true });
  }, []);

  const selectItem = useCallback((item: AnalyzedMessage, focus: NavFocusPane = "list") => {
    setEditing(false);
    setEditDraft(null);
    void loadDetail(item);
    // 下一帧聚焦，避免点击行时焦点落在不可导航区域
    requestAnimationFrame(() => focusNavPane(focus));
  }, [loadDetail, focusNavPane]);

  /** 详情左右切换所依据的当前可见列表（列表页 / 日历月内） */
  const detailNavItems = viewMode === "calendar" ? calendarItems : items;
  const detailNavIndex = selected
    ? detailNavItems.findIndex((x) => x.id === selected.id)
    : -1;
  const canNavPrev = detailNavIndex > 0;
  const canNavNext = detailNavIndex >= 0 && detailNavIndex < detailNavItems.length - 1;

  const selectAdjacent = useCallback((delta: -1 | 1, focus: NavFocusPane = "detail") => {
    const list = viewMode === "calendar" ? calendarItems : items;
    const idx = selected ? list.findIndex((x) => x.id === selected.id) : -1;
    if (idx < 0) return;
    const next = list[idx + delta];
    if (!next) return;
    selectItem(next, focus);
  }, [viewMode, calendarItems, items, selected, selectItem]);

  // 选中项变化时，列表行滚入可视区
  useEffect(() => {
    if (!selected?.id || viewMode !== "list") return;
    const row = listScrollRef.current?.querySelector<HTMLElement>(
      `[data-message-id="${CSS.escape(selected.id)}"]`,
    );
    row?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected?.id, viewMode, page]);

  // 列表聚焦：↑↓；详情聚焦：←→（录入弹层 / 编辑输入中不抢键）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (ingestOpen || editing) return;
      if (isTypingTarget(e.target)) return;
      if (navFocus !== "list" && navFocus !== "detail") return;

      const pane = navFocus === "list" ? listPaneRef.current : detailPaneRef.current;
      const active = document.activeElement;
      // 焦点已离开列表/详情区域时不响应（例如点到顶部筛选）
      if (pane && active && active !== pane && !pane.contains(active)) return;

      let delta: -1 | 1 | null = null;
      if (navFocus === "list") {
        if (e.key === "ArrowUp") delta = -1;
        else if (e.key === "ArrowDown") delta = 1;
      } else if (navFocus === "detail") {
        if (e.key === "ArrowLeft") delta = -1;
        else if (e.key === "ArrowRight") delta = 1;
      }
      if (delta == null) return;

      const list = viewMode === "calendar" ? calendarItems : items;
      const idx = selected ? list.findIndex((x) => x.id === selected.id) : -1;
      if (idx < 0) {
        if (list.length === 0) return;
        e.preventDefault();
        selectItem(list[0], navFocus);
        return;
      }
      const next = list[idx + delta];
      if (!next) return;
      e.preventDefault();
      selectItem(next, navFocus);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    ingestOpen, editing, navFocus, viewMode,
    calendarItems, items, selected, selectItem,
  ]);

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
      if (ingestFormat === "article") {
        const text = ingestText.trim();
        if (!text) {
          notify.error("请先粘贴整篇研报或文章");
          return;
        }
        if (!hasLlm()) {
          notify.error("请先在「接入 AI」配置模型");
          return;
        }
        const prompt = buildArticleIngestPrompt(text);
        const result = await chatStream(
          [{ role: "user", content: prompt }],
          "你只输出合法 JSON，不要调用工具，不要解释。",
        );
        const extracted = parseArticleIngestExtract(result.content, text);
        const draftKey = `article-${Date.now()}`;
        const draft: RawMessageDraft = {
          draft_key: draftKey,
          source_id: "article",
          source_label: "研报文章",
          content: extracted.original,
          title: extracted.title,
          keywords: extracted.keywords,
          url: "",
          marks: [],
          targets: extracted.targets.map((t) => ({
            kind: (["market", "sector", "theme", "stock", "other"].includes(t.kind)
              ? t.kind
              : "other") as ImpactTarget["kind"],
            code: t.code ?? null,
            name: t.name,
          })),
          meta: {
            format: "article",
            ai_extracted: true,
            summary: extracted.summary,
            impact_level: extracted.impact_level,
            freshness: extracted.freshness,
            effect_status: extracted.effect_status,
            article_date: extracted.date,
            stocks: extracted.stocks,
            sectors: extracted.sectors,
          },
        };
        setArticleExtract(extracted);
        setDrafts([draft]);
        notify.success("整篇分析完成，请确认字段后入库");
        return;
      }

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
      setArticleExtract(null);
      setDrafts(rows);
      notify.success(`解析成功，共 ${rows.length} 条`);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "解析预览失败"));
    } finally {
      setPreviewLoading(false);
    }
  };

  const closeIngest = () => {
    setIngestOpen(false);
    setIngestMetaOpen(false);
    setArticleExtract(null);
  };

  const openIngest = () => {
    setIngestMetaSourceLabel(ingestFormat === "article" ? "研报文章" : "手动录入");
    setIngestMetaProducedAt(nowStorageDatetime());
    setIngestMetaOpen(false);
    setArticleExtract(null);
    setIngestOpen(true);
  };

  const applyIngestMeta = (rows: RawMessageDraft[]): RawMessageDraft[] => {
    const label = ingestMetaSourceLabel.trim()
      || (ingestFormat === "article" ? "研报文章" : "手动录入");
    const produced = fromDatetimeLocal(toDatetimeLocal(ingestMetaProducedAt)) || ingestMetaProducedAt.trim() || nowStorageDatetime();
    return rows.map((d) => ({
      ...d,
      source_id: ingestFormat === "article" ? "article" : "manual",
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

      if (ingestFormat === "article") {
        try {
          const articleFiles = toCommit.map((d) => {
            const meta = d.meta || {};
            const stocks = Array.isArray(meta.stocks)
              ? (meta.stocks as { code?: string | null; name?: string | null }[])
              : [];
            const sectors = Array.isArray(meta.sectors)
              ? (meta.sectors as { name: string }[])
              : d.targets
                .filter((t) => t.kind === "sector" || t.kind === "theme")
                .map((t) => ({ name: t.name }));
            const date = String(meta.article_date || "").trim() || undefined;
            return {
              title: d.title || "未命名文章",
              summary: String(meta.summary || d.title || "").trim() || d.title || "未命名文章",
              date,
              original: d.content,
              stocks,
              sectors,
            };
          });
          await api.articlesCommit(articleFiles);
        } catch (e) {
          notify.error(e instanceof ApiError ? e.message : "消息已入库，但文章库写入失败");
        }
      }

      setDrafts([]);
      setIngestText("");
      setArticleExtract(null);
      setIngestMetaOpen(false);
      setIngestOpen(false);
      notify.success(
        ingestFormat === "article"
          ? `已入库 ${n} 条，并写入研报文章库`
          : `已入库 ${n} 条`,
      );
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
    if (ingestFormat === "plain" || ingestFormat === "structured" || ingestFormat === "article") {
      setIngestMetaSourceLabel((v) => v.trim() || (ingestFormat === "article" ? "研报文章" : "手动录入"));
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

  const pollCls = useCallback(async (opts?: { silent?: boolean; backfill?: boolean }) => {
    if (pollInFlight.current) return;
    pollInFlight.current = true;
    setPollingCls(true);
    try {
      const r = await api.messagePollCls({ backfill: opts?.backfill });
      if (r.inserted > 0) {
        notify.success(`财联社 +${r.inserted} 条（新增候选 ${r.new_candidates}）`);
        await refreshMessages();
        await loadSources();
      } else if (!opts?.silent) {
        const backfillHint = r.backfill_today ? " · 已补拉当日" : "";
        notify.info(`财联社已同步 · 拉取 ${r.fetched} 条 · 无新增${backfillHint}`);
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

  const applyMessagePatch = (updated: AnalyzedMessage) => {
    setItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
    setCalendarItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
    if (selected?.id === updated.id) {
      setSelected(updated);
      void loadDetail(updated);
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
      applyMessagePatch(updated);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "更新失败");
    } finally {
      setQuickPatching(false);
    }
  };

  const stockQueries = useMemo(() => {
    const out: { code?: string | null; name?: string | null }[] = [];
    if (currentStockCode) out.push({ code: currentStockCode });
    const pool = [...items, ...calendarItems];
    if (selected) pool.push(selected);
    for (const item of pool) {
      for (const t of item.targets) {
        if (t.name || t.code) out.push({ code: t.code, name: t.name });
      }
    }
    return out;
  }, [items, calendarItems, selected, currentStockCode]);

  const blockNames = useMemo(() => {
    const names: string[] = [];
    const pool = [...items, ...calendarItems];
    if (selected) pool.push(selected);
    for (const item of pool) {
      for (const t of item.targets) {
        if (t.kind === "market" || !t.name) continue;
        names.push(t.name);
      }
    }
    return names;
  }, [items, calendarItems, selected]);

  return (
    <StockResolveScope queries={stockQueries}>
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
            onClick={() => pollCls({ backfill: true })}
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
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                if (qInput !== q) patchListQuery({ q: qInput, page: 1 });
                else void refreshMessages();
              }}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 lg:gap-3">
            <FilterMultiSelect
              placeholder="全部来源"
              options={sourceFilterOptions}
              selected={sourcesFilter}
              onChange={(v) => patchListQuery({ source: v, page: 1 })}
            />
            <FilterMultiSelect
              placeholder="全部级别"
              options={Object.entries(IMPACT_LABEL).map(([k, v]) => ({ value: k, label: v }))}
              selected={impactLevels}
              onChange={(v) => patchListQuery({ impact_level: v, page: 1 })}
            />
            <FilterMultiSelect
              placeholder="全部生效"
              options={EFFECT_STATUS_OPTIONS.map((k) => ({ value: k, label: EFFECT_LABEL[k] }))}
              selected={effectStatuses}
              onChange={(v) => patchListQuery({ effect_status: v, page: 1 })}
            />
            <FilterMultiSelect
              placeholder="全部关注"
              options={[
                { value: "yes", label: "已关注" },
                { value: "no", label: "未关注" },
              ]}
              selected={followedFilter}
              onChange={(v) => patchListQuery({ followed: v, page: 1 })}
            />
            <FilterMultiSelect
              placeholder="全部收藏"
              options={[
                { value: "yes", label: "已收藏" },
                { value: "no", label: "未收藏" },
              ]}
              selected={favoritedFilter}
              onChange={(v) => patchListQuery({ favorited: v, page: 1 })}
            />
            <label
              className={cn(
                "inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors",
                followStockChange
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-background text-muted-foreground hover:text-foreground",
              )}
              title="勾选后仅显示与插件上报焦点股相关的消息（标的含该股、摘要/内容含股票名、或板块成分含该股）；排序优先标的→内容→板块，板块层内按成分股从少到多；需启用 vibe-ths-linker"
            >
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                checked={followStockChange}
                onChange={(e) => patchListQuery({ follow_stock: e.target.checked, page: 1 })}
              />
              <span>跟随股票变化</span>
              {followStockChange && (
                <FollowStockHint
                  code={currentStockCode}
                  status={currentStockStatus}
                  error={currentStockError}
                />
              )}
            </label>
            <MessageStockPipButton defaultEndDays={defaultEndDays} />
            <MessageStockPopupButton />
            <label
              className={cn(
                "inline-flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors",
                includeHistory
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border bg-background text-muted-foreground hover:text-foreground",
              )}
              title="默认只显示结束时间≥当前的未归档消息；勾选后才包含结束时间已过、但仍未归档的消息（不包含归档库）"
            >
              <input
                type="checkbox"
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                checked={includeHistory}
                onChange={(e) => patchListQuery({ include_history: e.target.checked, page: 1 })}
              />
              <span>包含历史消息</span>
            </label>
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
          <div
            ref={listPaneRef}
            tabIndex={0}
            aria-label="消息列表"
            className={cn(
              "glass min-w-0 overflow-hidden rounded-2xl outline-none xl:col-span-2",
              navFocus === "list" && "ring-2 ring-primary/35",
            )}
            onMouseDown={() => setNavFocus("list")}
            onFocus={() => setNavFocus("list")}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                setNavFocus((f) => (f === "list" ? null : f));
              }
            }}
          >
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
            <div ref={listScrollRef} className="max-h-[calc(100vh-220px)] overflow-auto">
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
                      <SortTh col="title" label="标题" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("title")} className="min-w-[240px] max-w-[360px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="produced_at" label="产生时间" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("produced_at")} className="w-32 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <th className="w-32 px-3 py-2.5 text-left align-middle">
                        <span className={sortThLabelCls}>生效时间</span>
                      </th>
                      <SortTh col="source" label="来源" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("source")} className="w-24 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="impact_level" label="级别" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("impact_level")} className="w-20 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="effect_status" label="生效情况" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("effect_status")} className="w-24 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="followed" label="关注" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("followed")} className="w-20 px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="keywords" label="关键词" hint="粘贴/结构化录入的关键词" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("keywords")} className="min-w-[140px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <SortTh col="targets" label="关联标的" sortCol={sort} order={order} onSort={toggleSort} sortable={SORTABLE_COLS.has("targets")} className="min-w-[160px] px-3 py-2.5 text-left align-middle" labelClassName={sortThLabelCls} />
                      <th className="w-32 px-3 py-2.5 text-left align-middle">
                        <span className={sortThLabelCls}>结束时间</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr
                        key={item.id}
                        data-message-id={item.id}
                        aria-selected={selected?.id === item.id}
                        className={cn(
                          "cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/25",
                          selected?.id === item.id &&
                            "bg-primary/12 shadow-[inset_3px_0_0_0_hsl(var(--primary))]",
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
                        <td className="px-3 py-3 align-top max-w-[360px]">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {item.favorited && (
                              <Star className="h-3.5 w-3.5 shrink-0 fill-amber-500 text-amber-500" aria-label="已收藏" />
                            )}
                            {item.marks.includes("highlight") && (
                              <Badge className="border-danger/40 bg-danger/15 text-danger">标红</Badge>
                            )}
                            <span
                              className={cn(
                                "font-semibold leading-snug line-clamp-2",
                                IMPACT_TITLE[item.impact_level] || "text-foreground",
                              )}
                            >
                              {item.title || "—"}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {item.produced_at}
                        </td>
                        <td className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {item.effective_mode === "scheduled" && item.effective_at
                            ? item.effective_at
                            : effectiveAt(item)}
                        </td>
                        <td className="px-3 py-3 align-top text-xs text-muted-foreground">
                          {item.source_label}
                        </td>
                        <td className="px-3 py-3 align-top">
                          <ImpactBadge level={item.impact_level} manual={item.impact_manual} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <EffectBadge status={item.effect_status} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          {item.followed ? (
                            <div className="space-y-1">
                              <Badge className="border-primary/40 bg-primary/15 text-primary">关注</Badge>
                              {((item.matched_follow_keywords?.length ?? 0) > 0
                                || (item.matched_follow_blocks?.length ?? 0) > 0) && (
                                <div className="flex flex-wrap gap-0.5">
                                  {(item.matched_follow_keywords ?? []).slice(0, 2).map((k) => (
                                    <span key={`kw-${k}`} className="text-[10px] text-primary/80">{k}</span>
                                  ))}
                                  {(item.matched_follow_blocks ?? []).slice(0, 2).map((b) => (
                                    <span key={`blk-${b}`} className="text-[10px] text-amber-700/90 dark:text-amber-300/90">
                                      板块·{b}
                                    </span>
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
                          <MessageTargets
                            item={item}
                            max={3}
                            stockHitBlockNames={
                              followStockChange ? item.matched_current_stock_blocks : undefined
                            }
                          />
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
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    disabled={page <= 1 || loading}
                    className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-40"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </button>
                  {pageItems.map((item, idx) =>
                    item === "gap" ? (
                      <span key={`gap-${idx}`} className="px-1 text-xs text-muted-foreground">
                        …
                      </span>
                    ) : (
                      <button
                        key={item}
                        type="button"
                        disabled={loading || item === page}
                        aria-current={item === page ? "page" : undefined}
                        className={cn(
                          "min-w-8 rounded-lg border px-2.5 py-1.5 text-xs font-semibold tabular-nums transition-colors disabled:opacity-100",
                          item === page
                            ? "border-primary/40 bg-primary/15 text-primary"
                            : "border-border bg-background text-foreground hover:bg-muted/50 disabled:opacity-40",
                        )}
                        onClick={() => setPage(item)}
                      >
                        {item}
                      </button>
                    ),
                  )}
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

          <div
            ref={detailPaneRef}
            tabIndex={0}
            aria-label="消息详情"
            className={cn(
              "glass max-h-[calc(100vh-220px)] min-w-0 overflow-auto rounded-2xl p-4 outline-none xl:col-span-1",
              navFocus === "detail" && "ring-2 ring-primary/35",
            )}
            onMouseDown={() => setNavFocus("detail")}
            onFocus={() => setNavFocus("detail")}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                setNavFocus((f) => (f === "detail" ? null : f));
              }
            }}
          >
            {!selected ? (
              <p className="py-12 text-center text-sm text-muted-foreground">选择消息查看详情</p>
            ) : (
              <div className="space-y-4">
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
                    {detailNavItems.length > 0 && detailNavIndex >= 0 && (
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          aria-label="上一条"
                          title="上一条（←）"
                          disabled={!canNavPrev}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-foreground transition-colors hover:bg-muted/50 disabled:opacity-40"
                          onClick={() => selectAdjacent(-1, "detail")}
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </button>
                        <span className="min-w-[3.25rem] text-center text-[11px] tabular-nums text-muted-foreground">
                          {detailNavIndex + 1}/{detailNavItems.length}
                        </span>
                        <button
                          type="button"
                          aria-label="下一条"
                          title="下一条（→）"
                          disabled={!canNavNext}
                          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-foreground transition-colors hover:bg-muted/50 disabled:opacity-40"
                          onClick={() => selectAdjacent(1, "detail")}
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
                {(["plain", "structured", "calendar", "article"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors",
                      ingestFormat === f
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => {
                      setIngestFormat(f);
                      setDrafts([]);
                      setArticleExtract(null);
                      if (f === "article") setIngestMetaSourceLabel("研报文章");
                      else if (f === "plain" || f === "structured") setIngestMetaSourceLabel("手动录入");
                    }}
                  >
                    {f === "plain" ? "文字粘贴" : f === "structured" ? "JSON" : f === "calendar" ? "财经日历" : "研报文章"}
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
                      : ingestFormat === "article"
                        ? "粘贴整篇研报或文章原文（不拆分）。点「AI 分析整篇」提取标题、摘要、关键词、个股与板块等字段…"
                        : '[{"title":"…","content":"…","url":"…","keywords":["…"],"marks":["highlight"]}]'
                }
                value={ingestText}
                onChange={(e) => setIngestText(e.target.value)}
              />
              {ingestFormat === "article" && articleExtract && drafts.length > 0 && (
                <div className="space-y-3 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">标题</div>
                    <div className="font-medium text-foreground">{articleExtract.title}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">摘要</div>
                    <div className="text-foreground/90">{articleExtract.summary}</div>
                  </div>
                  <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span>日期 {articleExtract.date}</span>
                    <span>影响 {IMPACT_LABEL[articleExtract.impact_level] || articleExtract.impact_level}</span>
                    <span>新旧 {FRESHNESS_LABEL[articleExtract.freshness] || articleExtract.freshness}</span>
                    <span>发酵 {EFFECT_LABEL[articleExtract.effect_status] || articleExtract.effect_status}</span>
                  </div>
                  {articleExtract.keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {articleExtract.keywords.map((k) => (
                        <span key={k} className="rounded-md border border-border bg-background px-2 py-0.5 text-xs">
                          {k}
                        </span>
                      ))}
                    </div>
                  )}
                  {articleExtract.targets.length > 0 && (
                    <div>
                      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">关联标的</div>
                      <div className="flex flex-wrap gap-1.5">
                        {articleExtract.targets.map((t, i) => (
                          <span
                            key={`${t.kind}-${t.code}-${t.name}-${i}`}
                            className="rounded-md border border-border/80 bg-background px-2 py-0.5 text-xs text-foreground"
                          >
                            {TARGET_KIND_LABEL[t.kind] || t.kind}·{t.name}
                            {t.code ? ` ${t.code}` : ""}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <p className="text-[11px] text-muted-foreground">
                    确认入库后：写入消息分析，并同步到研报文章库（保留原文 + 摘要索引，个股/板块经处理器解析）。
                  </p>
                </div>
              )}
              {drafts.length > 0 && ingestFormat !== "article" && (
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
                {ingestFormat === "article" ? (
                  <span className="inline-flex items-center gap-1">
                    {!previewLoading && <Sparkles className="h-3.5 w-3.5" />}
                    AI 分析整篇
                  </span>
                ) : (
                  "预览拆分"
                )}
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
              {ingestFormat === "article" && " 研报文章将同时写入文章库。"}
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-muted-foreground">数据来源</label>
                <input
                  className={inputCls}
                  placeholder={ingestFormat === "article" ? "研报文章" : "手动录入"}
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
    </StockResolveScope>
  );
}
