import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Boxes, Check, ChevronDown, ChevronRight, Folder, FolderOpen,
  LayoutList, Loader2, Network, Pencil, Plus, RefreshCw, Search, Star, Trash2, X,
} from "lucide-react";
import { toast } from "sonner";
import { BlockStocksTable } from "@/components/block/BlockStocksTable";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type BlocksManageSnapshot, type ManagedBlockRow, type Quote, type ThemeAliasEntry,
  type ThsBlockStocksDetail, type ThsTreeNode,
} from "@/lib/api";
import {
  isBlockFollowed, setFollowBlocksCache, type FollowBlock,
} from "@/lib/message-follow-blocks";
import {
  THS_BLOCK_KINDS, BLOCK_MANAGE_THS_KINDS, BLOCK_MANAGE_KPL_KINDS, THS_NODE_TYPE_LABEL,
  aliasesForBlockName, attachOrphanLeavesToTree, blockTreeNodeId,
  buildAliasesByCanonical, buildSyntheticBlockTree, collectThsBranchIds,
  collectThsNodeIds, filterThsTree, manageTabOrigin, manageTabThsKind,
  normalizeThemeTag, parseThsTree, sortRowsByTreeOrder,
  themeAliasEntriesFromConfig, thsBlockCodeSubtitle, thsBlockKindLabel,
  thsBlockPrimaryCode, thsCustomSubtypeLabel,
} from "@/lib/thsBlocks";
import { keywordsSettingsTo } from "@/lib/settingsNav";

const ALIAS_MAX_LEN = 20;
const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const inputCls =
  "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground";

type SortKey = "id" | "name" | "node_type" | "tree_path" | "subtype" | "kpl_code";
type ViewMode = "tree" | "list";
type SourceFilter = "all" | "ths" | "kpl";
/** 关注为虚拟类型：跨 kind 展示已关注板块，树视图按原层级裁剪 */
const FOLLOWED_KIND = "followed";

function managedRowKey(row: Pick<ManagedBlockRow, "kind" | "id" | "kpl_code" | "name">): string {
  if (row.id) return `${row.kind}|${row.id}`;
  return `${row.kind}|kpl:${row.kpl_code || row.name}`;
}

/** 同花顺成分股 / 关注用的类型：人气页签回退 ths_kind */
function thsStocksKind(row: ManagedBlockRow): string {
  const k = (row.ths_kind || "").trim();
  if (k && k !== "hot") return k;
  if (row.kind && row.kind !== "hot") return row.kind;
  return "";
}

function SourceBadges({ row }: { row: ManagedBlockRow }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {row.has_ths && (
        <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700 dark:text-sky-300">
          同花顺
        </span>
      )}
      {row.has_kpl && (
        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
          开盘啦
        </span>
      )}
      {!row.has_ths && !row.has_kpl && (
        <span className="text-muted-foreground/50">—</span>
      )}
    </span>
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

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function kindHasError(errors: string[] | undefined, kind: string): boolean {
  return (errors || []).some((e) => e.startsWith(`${kind}:`));
}

function FollowBlockButton({
  followed,
  onToggle,
  size = "sm",
  className,
}: {
  followed: boolean;
  onToggle: () => void;
  size?: "sm" | "md";
  className?: string;
}) {
  const iconCls = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  return (
    <button
      type="button"
      title={followed ? "取消关注" : "关注板块"}
      aria-label={followed ? "取消关注" : "关注板块"}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md border transition-colors",
        size === "md" ? "h-8 gap-1.5 px-2.5 text-xs font-semibold" : "h-7 w-7",
        followed
          ? "border-amber-500/40 bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 dark:text-amber-300"
          : "border-border bg-background text-muted-foreground hover:border-amber-500/35 hover:text-amber-700 dark:hover:text-amber-300",
        className,
      )}
    >
      <Star className={cn(iconCls, followed && "fill-current")} />
      {size === "md" && (followed ? "已关注" : "关注")}
    </button>
  );
}

function AliasInlineText({ aliases }: { aliases: string[] }) {
  if (!aliases.length) return <span className="text-muted-foreground/50">—</span>;
  const text = aliases.join("、");
  return (
    <span className="text-muted-foreground" title={text}>
      {text}
    </span>
  );
}

function FollowedOrKindTable({
  filteredRows,
  showSubtypeCol,
  sort,
  order,
  onSort,
  selected,
  followedIds,
  aliasesByCanonical,
  onOpen,
  onToggleFollow,
}: {
  filteredRows: ManagedBlockRow[];
  showSubtypeCol: boolean;
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey) => void;
  selected: ManagedBlockRow | null;
  followedIds: Set<string>;
  aliasesByCanonical: Map<string, string[]>;
  onOpen: (row: ManagedBlockRow) => void;
  onToggleFollow: (row: ManagedBlockRow) => void;
}) {
  const colCount = (showSubtypeCol ? 9 : 8);
  return (
    <table className="w-full min-w-[920px] text-sm">
      <thead className="sticky top-0 z-[1] bg-background/95 backdrop-blur">
        <tr className="border-b border-border/60 text-left">
          <SortTh col="id" label="同花顺码" sortCol={sort} order={order} onSort={onSort} />
          <SortTh col="kpl_code" label="开盘啦码" sortCol={sort} order={order} onSort={onSort} />
          <SortTh col="name" label="名称" sortCol={sort} order={order} onSort={onSort} />
          <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">来源</th>
          <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">别名</th>
          {showSubtypeCol && (
            <SortTh col="subtype" label="子类型" sortCol={sort} order={order} onSort={onSort} />
          )}
          <SortTh col="node_type" label="节点" sortCol={sort} order={order} onSort={onSort} />
          <SortTh col="tree_path" label="树路径" sortCol={sort} order={order} onSort={onSort} />
          <th className="w-16 px-3 py-2.5 text-center text-xs font-semibold text-muted-foreground">关注</th>
        </tr>
      </thead>
      <tbody>
        {filteredRows.map((row) => {
          const active = selected != null && managedRowKey(selected) === managedRowKey(row);
          const subtype = thsCustomSubtypeLabel(row);
          const depth = row.depth ?? 0;
          const followed = (() => {
            const sk = thsStocksKind(row);
            return !!(row.id && sk && followedIds.has(`${sk}|${row.id}`));
          })();
          const aliases = aliasesForBlockName(row.name, aliasesByCanonical);
          return (
            <tr
              key={managedRowKey(row)}
              className={cn(
                "cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/30",
                active && "bg-primary/8",
              )}
              onClick={() => onOpen(row)}
            >
              <td className="px-4 py-2.5 font-mono text-xs">
                {row.code ? (
                  <span className="text-foreground">{row.code}</span>
                ) : row.id ? (
                  <span className="text-muted-foreground">{row.id}</span>
                ) : (
                  <span className="text-muted-foreground/50">—</span>
                )}
              </td>
              <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                {row.kpl_code || "—"}
              </td>
              <td className="px-4 py-2.5 font-medium text-foreground">
                <span style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
                  {row.name || "—"}
                </span>
                {row.stock_count != null && (
                  <span className="ml-1.5 text-xs tabular-nums text-muted-foreground">
                    ({row.stock_count})
                  </span>
                )}
              </td>
              <td className="px-3 py-2.5">
                <SourceBadges row={row} />
              </td>
              <td className="max-w-[180px] truncate px-3 py-2.5 text-xs">
                <AliasInlineText aliases={aliases} />
              </td>
              {showSubtypeCol && (
                <td className="px-4 py-2.5 text-muted-foreground">{subtype || "—"}</td>
              )}
              <td className="px-4 py-2.5 text-muted-foreground">
                {THS_NODE_TYPE_LABEL[row.node_type] || row.node_type || "—"}
              </td>
              <td className="max-w-[280px] truncate px-4 py-2.5 text-muted-foreground" title={row.tree_path}>
                {row.tree_path || "—"}
              </td>
              <td className="px-3 py-2.5 text-center">
                {row.has_ths && row.id && thsStocksKind(row) ? (
                  <FollowBlockButton
                    followed={followed}
                    onToggle={() => onToggleFollow(row)}
                    className="mx-auto"
                  />
                ) : (
                  <span className="text-muted-foreground/40">—</span>
                )}
              </td>
            </tr>
          );
        })}
        {!filteredRows.length && (
          <tr>
            <td colSpan={colCount} className="px-4 py-10 text-center text-muted-foreground">
              无匹配板块
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
function ThsBlockTreeItem({
  node,
  depth,
  expanded,
  rowById,
  selectedId,
  followedIds,
  aliasesByCanonical,
  onToggle,
  onSelect,
  onToggleFollow,
}: {
  node: ThsTreeNode;
  depth: number;
  expanded: Set<string>;
  rowById: Map<string, ManagedBlockRow>;
  selectedId: string | null;
  followedIds: Set<string>;
  aliasesByCanonical: Map<string, string[]>;
  onToggle: (id: string) => void;
  onSelect: (row: ManagedBlockRow) => void;
  onToggleFollow: (row: ManagedBlockRow) => void;
}) {
  const isBranch = node.node_type === "branch";
  const isOpen = isBranch && expanded.has(node.id);
  const row = rowById.get(node.id);
  const active = selectedId === node.id;
  const stockCount = row?.stock_count;
  const followed = row ? followedIds.has(`${row.kind}|${row.id}`) : false;
  const aliases = aliasesForBlockName(node.name, aliasesByCanonical);
  const aliasText = aliases.length ? aliases.join("、") : "";

  const handleClick = () => {
    if (isBranch) {
      onToggle(node.id);
      if (row) onSelect(row);
      return;
    }
    if (row) onSelect(row);
  };

  return (
    <div>
      <div
        className={cn(
          "group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
          "hover:bg-muted/40",
          active && "bg-primary/10 ring-1 ring-primary/20",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          onClick={handleClick}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          <span className="flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground">
            {isBranch ? (
              isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />
            ) : (
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            )}
          </span>
          <span className="flex h-5 w-5 shrink-0 items-center justify-center">
            {isBranch ? (
              isOpen
                ? <FolderOpen className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                : <Folder className="h-4 w-4 text-amber-600/80 dark:text-amber-400/80" />
            ) : (
              <Boxes className="h-3.5 w-3.5 text-primary/70" />
            )}
          </span>
          <span className="min-w-0 flex-1 truncate font-medium text-foreground">
            {node.name || node.id}
          </span>
          {aliasText && (
            <span
              className="hidden max-w-[140px] shrink truncate text-[11px] text-muted-foreground lg:inline"
              title={`别名：${aliasText}`}
            >
              {aliasText}
            </span>
          )}
          {stockCount != null && (
            <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
              {stockCount}
            </span>
          )}
          <span className="hidden shrink-0 font-mono text-[10px] text-muted-foreground/70 sm:inline">
            {row ? thsBlockPrimaryCode(row) : node.id}
          </span>
        </button>
        {row && (
          <FollowBlockButton
            followed={followed}
            onToggle={() => onToggleFollow(row)}
            className="opacity-70 group-hover:opacity-100"
          />
        )}
      </div>
      {isBranch && isOpen && (node.children ?? []).map((child) => (
        <ThsBlockTreeItem
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          rowById={rowById}
          selectedId={selectedId}
          followedIds={followedIds}
          aliasesByCanonical={aliasesByCanonical}
          onToggle={onToggle}
          onSelect={onSelect}
          onToggleFollow={onToggleFollow}
        />
      ))}
    </div>
  );
}

export function ThsBlocks() {
  const [snapshot, setSnapshot] = useState<BlocksManageSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingKind, setRefreshingKind] = useState<string | null>(null);

  const [kindFilter, setKindFilter] = useState<string>("ths:conception");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [q, setQ] = useState("");
  const [nodeFilter, setNodeFilter] = useState<"all" | "leaf" | "branch">("all");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortKey>("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");

  const [selected, setSelected] = useState<ManagedBlockRow | null>(null);
  const [stocksDetail, setStocksDetail] = useState<ThsBlockStocksDetail | null>(null);
  const [stocksLoading, setStocksLoading] = useState(false);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [followBlocks, setFollowBlocks] = useState<FollowBlock[]>([]);
  const [aliasEntries, setAliasEntries] = useState<ThemeAliasEntry[]>([]);
  const [aliasSaving, setAliasSaving] = useState(false);
  const [aliasDraft, setAliasDraft] = useState("");
  const [aliasEditingKey, setAliasEditingKey] = useState<string | null>(null);
  const [aliasEditDraft, setAliasEditDraft] = useState("");

  const thsSnap = snapshot?.ths ?? null;

  const followedIds = useMemo(
    () => new Set(followBlocks.map((b) => `${b.kind}|${b.id}`)),
    [followBlocks],
  );

  const aliasesByCanonical = useMemo(
    () => buildAliasesByCanonical(aliasEntries),
    [aliasEntries],
  );

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.blocksManage();
      setSnapshot(data);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "加载板块管理失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadFollowBlocks = useCallback(async () => {
    try {
      const data = await api.messageFollowBlocks();
      setFollowBlocks(setFollowBlocksCache(data.blocks || []));
    } catch {
      /* 关注列表失败不阻断板块浏览 */
    }
  }, []);

  const loadAliases = useCallback(async () => {
    try {
      const cfg = await api.themeAliases();
      setAliasEntries(themeAliasEntriesFromConfig(cfg));
    } catch {
      /* 别名失败不阻断板块浏览 */
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
    void loadFollowBlocks();
    void loadAliases();
  }, [loadSnapshot, loadFollowBlocks, loadAliases]);

  useEffect(() => {
    setAliasDraft("");
    setAliasEditingKey(null);
    setAliasEditDraft("");
  }, [selected?.kind, selected?.id]);

  const persistAliases = useCallback(async (next: ThemeAliasEntry[]) => {
    setAliasSaving(true);
    try {
      const r = await api.saveThemeAliases(next);
      setAliasEntries(themeAliasEntriesFromConfig(r));
      notify.success("板块别名已保存");
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "保存别名失败");
    } finally {
      setAliasSaving(false);
    }
  }, []);

  const addAliasForSelected = useCallback(async () => {
    if (!selected) return;
    const alias = normalizeThemeTag(aliasDraft);
    const canonical = normalizeThemeTag(selected.name || selected.id);
    if (!alias || !canonical) {
      notify.error("请填写别名");
      return;
    }
    if (alias.length > ALIAS_MAX_LEN || canonical.length > ALIAS_MAX_LEN) {
      notify.error(`板块名不超过 ${ALIAS_MAX_LEN} 个字`);
      return;
    }
    if (alias === canonical) {
      notify.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => normalizeThemeTag(e.alias) === alias)) {
      notify.error("该别名已存在");
      return;
    }
    const next = [
      ...aliasEntries,
      { alias, canonical, type: "" },
    ].sort((a, b) => {
      const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
      if (byCanonical !== 0) return byCanonical;
      return a.alias.localeCompare(b.alias, "zh-CN");
    });
    setAliasDraft("");
    await persistAliases(next);
  }, [selected, aliasDraft, aliasEntries, persistAliases]);

  const removeAlias = useCallback(async (alias: string) => {
    if (aliasEditingKey === alias) {
      setAliasEditingKey(null);
      setAliasEditDraft("");
    }
    const next = aliasEntries.filter((e) => e.alias !== alias);
    await persistAliases(next);
  }, [aliasEditingKey, aliasEntries, persistAliases]);

  const saveEditAlias = useCallback(async () => {
    if (!selected || !aliasEditingKey) return;
    const alias = normalizeThemeTag(aliasEditDraft);
    const canonical = normalizeThemeTag(selected.name || selected.id);
    if (!alias || !canonical) {
      notify.error("请填写别名");
      return;
    }
    if (alias.length > ALIAS_MAX_LEN || canonical.length > ALIAS_MAX_LEN) {
      notify.error(`板块名不超过 ${ALIAS_MAX_LEN} 个字`);
      return;
    }
    if (alias === canonical) {
      notify.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => e.alias === alias && e.alias !== aliasEditingKey)) {
      notify.error("该别名已存在");
      return;
    }
    const next = aliasEntries
      .map((e) =>
        e.alias === aliasEditingKey
          ? { alias, canonical, type: e.type }
          : e,
      )
      .sort((a, b) => {
        const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
        if (byCanonical !== 0) return byCanonical;
        return a.alias.localeCompare(b.alias, "zh-CN");
      });
    setAliasEditingKey(null);
    setAliasEditDraft("");
    await persistAliases(next);
  }, [selected, aliasEditingKey, aliasEditDraft, aliasEntries, persistAliases]);

  const toggleFollow = useCallback(async (row: ManagedBlockRow) => {
    const followKind = thsStocksKind(row);
    if (!row.has_ths || !row.id || !followKind) {
      notify.error("仅同花顺板块可关注");
      return;
    }
    const nextFollow = !isBlockFollowed(followKind, row.id, followBlocks);
    try {
      const data = await api.toggleMessageFollowBlock({
        kind: followKind,
        id: row.id,
        name: row.name || row.id,
        follow: nextFollow,
      });
      setFollowBlocks(setFollowBlocksCache(data.blocks || []));
      notify.success(nextFollow ? `已关注「${row.name || row.id}」` : `已取消关注「${row.name || row.id}」`);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "更新关注失败");
    }
  }, [followBlocks]);

  const refreshAll = async () => {
    setRefreshing(true);
    const failed: string[] = [];

    for (const k of THS_BLOCK_KINDS) {
      setRefreshingKind(k.value);
      try {
        await api.thsBlocksRefreshKind(k.value);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "刷新失败";
        failed.push(`${k.label}: ${msg}`);
      }
    }

    setRefreshingKind("kpl");
    let latest: BlocksManageSnapshot | null = null;
    try {
      latest = await api.blocksManageRefreshKpl();
      setSnapshot(latest);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "开盘啦刷新失败";
      failed.push(`开盘啦: ${msg}`);
      try {
        latest = await api.blocksManage();
        setSnapshot(latest);
      } catch {
        /* ignore */
      }
    }

    setRefreshingKind(null);
    setSelected(null);
    setStocksDetail(null);
    setQuotes({});

    const loaded = latest?.ths?.kinds ? Object.keys(latest.ths.kinds).length : 0;
    if (latest?.linker_unavailable) {
      notify.error(latest.linker_message || "依赖于第三方工具，目前无法请求");
    } else if (failed.length) {
      notify.error(`部分刷新失败（同花顺 ${loaded}/${THS_BLOCK_KINDS.length}）：${failed.join("；")}`);
    } else {
      notify.success(`板块已刷新 · 同花顺 ${latest?.ths?.updated_at || "—"} · 开盘啦 ${latest?.kpl?.fetched_date || "—"}`);
    }
    setRefreshing(false);
  };

  const refreshOneKind = async (kind: string) => {
    setRefreshing(true);
    setRefreshingKind(kind);
    try {
      await api.thsBlocksRefreshKind(kind);
      const data = await api.blocksManage();
      setSnapshot(data);
      const label = thsBlockKindLabel(kind);
      const err = (data.ths?.errors || data.errors || []).find((e) => e.startsWith(`${kind}:`));
      if (err) {
        notify.error(`${label}：${err.slice(kind.length + 2)}`);
      } else {
        notify.success(`${label} 已刷新`);
      }
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "刷新失败");
    } finally {
      setRefreshingKind(null);
      setRefreshing(false);
    }
  };

  const isFollowedView = kindFilter === FOLLOWED_KIND;
  const tabOrigin = manageTabOrigin(kindFilter);
  const thsKindForTab = manageTabThsKind(kindFilter);

  /** 当前来源下可选的类型页签 */
  const visibleTypeTabs = useMemo(() => {
    if (sourceFilter === "ths") return [...BLOCK_MANAGE_THS_KINDS];
    if (sourceFilter === "kpl") return [...BLOCK_MANAGE_KPL_KINDS];
    return [...BLOCK_MANAGE_THS_KINDS, ...BLOCK_MANAGE_KPL_KINDS];
  }, [sourceFilter]);

  useEffect(() => {
    if (isFollowedView) return;
    if (!visibleTypeTabs.some((t) => t.value === kindFilter)) {
      setKindFilter(visibleTypeTabs[0]?.value || "ths:conception");
      setSelected(null);
      setStocksDetail(null);
    }
  }, [sourceFilter, visibleTypeTabs, kindFilter, isFollowedView]);

  /** 关注视图：从融合行解析已关注；普通视图：当前原始类型页签 */
  const allRows = useMemo(() => {
    if (!isFollowedView) {
      // 页签已按来源原始分类切开，不再用 source 二次混入对方类型
      return snapshot?.merged?.[kindFilter] || [];
    }
    const out: ManagedBlockRow[] = [];
    const seen = new Set<string>();
    const matchSource = (row: ManagedBlockRow) => {
      if (sourceFilter === "ths") return row.origin === "ths" || row.has_ths;
      if (sourceFilter === "kpl") return row.origin === "kpl" || row.has_kpl;
      return true;
    };
    for (const fb of followBlocks) {
      const key = `${fb.kind}|${fb.id}`;
      if (seen.has(key)) continue;
      const tabKey = `ths:${fb.kind}`;
      const row = (snapshot?.merged?.[tabKey] || []).find((r) => r.id === fb.id);
      if (row && matchSource(row)) {
        seen.add(key);
        out.push(row);
      }
    }
    return out;
  }, [isFollowedView, kindFilter, snapshot, followBlocks, sourceFilter]);

  const kindEntry = isFollowedView || tabOrigin !== "ths" || !thsKindForTab
    ? null
    : thsSnap?.kinds?.[thsKindForTab];
  const showSubtypeCol = thsKindForTab === "custom";

  /** 关注视图：任一关注项所属 kind 有树即可树形浏览 */
  const followedTreeSections = useMemo(() => {
    if (!isFollowedView || !thsSnap?.kinds) return [];
    const matchSource = (row: ManagedBlockRow) => {
      if (sourceFilter === "ths") return row.origin === "ths" || row.has_ths;
      if (sourceFilter === "kpl") return false; // 关注仅同花顺
      return row.origin === "ths" || row.has_ths;
    };
    const sections: { kind: string; label: string; tree: ThsTreeNode; rowById: Map<string, ManagedBlockRow> }[] = [];
    for (const k of THS_BLOCK_KINDS) {
      const entry = thsSnap.kinds[k.value];
      const followedInKind = followBlocks.filter((b) => b.kind === k.value);
      if (!followedInKind.length) continue;
      const mergedRows = (snapshot?.merged?.[`ths:${k.value}`] || []).filter(matchSource);
      const rowById = new Map<string, ManagedBlockRow>();
      for (const row of mergedRows) {
        rowById.set(blockTreeNodeId(row), row);
      }
      const allowedIds = new Set(
        followedInKind
          .map((b) => {
            const row = mergedRows.find((r) => r.id === b.id);
            return row ? blockTreeNodeId(row) : b.id;
          })
          .filter(Boolean),
      );
      let root: ThsTreeNode | null = null;
      if (entry?.tree && entry.tree_mode === "tree") {
        root = parseThsTree(entry.tree);
      }
      if (!root) {
        const rows = mergedRows.filter((r) => followedInKind.some((b) => b.id === r.id));
        if (!rows.length) continue;
        root = buildSyntheticBlockTree(rows, k.label, `__followed_${k.value}__`);
      } else {
        const orphans = mergedRows.filter(
          (r) => followedInKind.some((b) => b.id === r.id) && !collectThsNodeIds(root).has(blockTreeNodeId(r)),
        );
        root = attachOrphanLeavesToTree(root, orphans);
      }
      const codeById = new Map<string, string>();
      for (const row of mergedRows) {
        const nid = blockTreeNodeId(row);
        if (row.code) codeById.set(nid, row.code);
        else if (row.kpl_code) codeById.set(nid, row.kpl_code);
      }
      const pruned = filterThsTree(root, {
        query: q,
        nodeFilter,
        codeById,
        aliasesByName: aliasesByCanonical,
        allowedIds,
      });
      if (!pruned) continue;
      sections.push({
        kind: k.value,
        label: k.label,
        tree: pruned,
        rowById,
      });
    }
    return sections;
  }, [isFollowedView, thsSnap, followBlocks, q, nodeFilter, aliasesByCanonical, sourceFilter, snapshot]);

  /** 有同花顺树或可合成挂根树时均可树形浏览；筛选不强制切视图 */
  const canShowTree = isFollowedView
    ? followedTreeSections.length > 0 || allRows.length > 0
    : allRows.length > 0 || !!(kindEntry?.tree && kindEntry.tree_mode === "tree");

  useEffect(() => {
    if (!canShowTree || viewMode !== "tree") {
      if (!canShowTree) setExpanded(new Set());
      return;
    }
    if (isFollowedView) {
      const ids = new Set<string>();
      for (const section of followedTreeSections) {
        for (const id of collectThsBranchIds(section.tree)) ids.add(id);
      }
      setExpanded(ids);
      return;
    }
    if (kindEntry?.tree && kindEntry.tree_mode === "tree") {
      const root = parseThsTree(kindEntry.tree);
      if (!root) return;
      const ids = new Set<string>();
      const walk = (node: ThsTreeNode, depth: number) => {
        if (node.node_type === "branch" && depth < 2) {
          ids.add(node.id);
          for (const child of node.children ?? []) walk(child, depth + 1);
        }
      };
      walk(root, 0);
      setExpanded(ids);
      return;
    }
    // 合成树：默认展开根
    setExpanded(new Set([
      `__root_${kindFilter}__`,
      `__kpl_${kindFilter.replace("kpl:", "")}_root__`,
      "__hot_root__",
    ]));
  }, [kindFilter, canShowTree, viewMode, kindEntry?.tree, kindEntry?.tree_mode, isFollowedView, followedTreeSections]);

  const rowById = useMemo(() => {
    const m = new Map<string, ManagedBlockRow>();
    for (const row of allRows) {
      m.set(blockTreeNodeId(row), row);
    }
    return m;
  }, [allRows]);

  const filteredTree = useMemo(() => {
    if (isFollowedView || viewMode !== "tree") return null;
    const label = thsBlockKindLabel(kindFilter);
    const codeById = new Map<string, string>();
    for (const row of allRows) {
      const nid = blockTreeNodeId(row);
      if (row.code) codeById.set(nid, row.code);
      else if (row.kpl_code) codeById.set(nid, row.kpl_code);
    }
    let root: ThsTreeNode | null = null;
    if (kindEntry?.tree && kindEntry.tree_mode === "tree") {
      root = parseThsTree(kindEntry.tree);
      if (root) {
        const inTree = collectThsNodeIds(root);
        const orphans = allRows.filter((r) => r.node_type !== "branch" && !inTree.has(blockTreeNodeId(r)));
        root = attachOrphanLeavesToTree(root, orphans);
      }
    }
    if (!root) {
      const kplKind = kindFilter.startsWith("kpl:") ? kindFilter.slice(4) : "";
      root = buildSyntheticBlockTree(
        allRows,
        label,
        kplKind ? `__kpl_${kplKind}_root__` : `__root_${kindFilter}__`,
      );
    }
    return filterThsTree(root, {
      query: q,
      nodeFilter,
      codeById,
      aliasesByName: aliasesByCanonical,
    });
  }, [isFollowedView, viewMode, kindEntry?.tree, kindEntry?.tree_mode, q, nodeFilter, allRows, aliasesByCanonical, kindFilter]);

  const filteredRows = useMemo((): ManagedBlockRow[] => {
    const query = q.trim().toLowerCase();
    let rows: ManagedBlockRow[] = allRows.filter((row) => {
      if (nodeFilter === "leaf" && row.node_type === "branch") return false;
      if (nodeFilter === "branch" && row.node_type !== "branch") return false;
      if (!query) return true;
      const subtype = thsCustomSubtypeLabel(row) || "";
      const aliases = aliasesForBlockName(row.name, aliasesByCanonical);
      return (
        (row.id || "").toLowerCase().includes(query)
        || (row.code || "").toLowerCase().includes(query)
        || (row.kpl_code || "").toLowerCase().includes(query)
        || (row.name || "").toLowerCase().includes(query)
        || (row.tree_path || "").toLowerCase().includes(query)
        || subtype.toLowerCase().includes(query)
        || (row.query_key || "").toLowerCase().includes(query)
        || aliases.some((a) => a.toLowerCase().includes(query))
      );
    });
    if (viewMode === "tree" && canShowTree && !query && nodeFilter === "all") {
      return sortRowsByTreeOrder(rows);
    }
    rows = [...rows].sort((a, b) => {
      let av: string;
      let bv: string;
      if (sort === "subtype") {
        av = thsCustomSubtypeLabel(a) || "";
        bv = thsCustomSubtypeLabel(b) || "";
      } else if (sort === "id") {
        av = thsBlockPrimaryCode(a);
        bv = thsBlockPrimaryCode(b);
      } else if (sort === "kpl_code") {
        av = a.kpl_code || "";
        bv = b.kpl_code || "";
      } else {
        av = String(a[sort] ?? "");
        bv = String(b[sort] ?? "");
      }
      const cmp = av.localeCompare(bv, "zh-CN");
      return order === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [allRows, q, nodeFilter, sort, order, viewMode, canShowTree, aliasesByCanonical]);

  /** 关注视图中无树结构的类型（自定义 / 每日动态等），树形模式下附在裁剪树之后 */
  const followedFlatGroups = useMemo(() => {
    if (!isFollowedView) return [];
    const treeKinds = new Set(followedTreeSections.map((s) => s.kind));
    const groups: { kind: string; label: string; rows: ManagedBlockRow[] }[] = [];
    for (const k of THS_BLOCK_KINDS) {
      if (treeKinds.has(k.value)) continue;
      const rows = filteredRows.filter((r) => r.kind === k.value);
      if (!rows.length) continue;
      groups.push({ kind: k.value, label: k.label, rows });
    }
    return groups;
  }, [isFollowedView, followedTreeSections, filteredRows]);

  const toggleSort = (key: SortKey) => {
    if (sort === key) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setOrder("asc");
    }
  };

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const expandAllBranches = () => {
    if (isFollowedView) {
      const ids = new Set<string>();
      for (const section of followedTreeSections) {
        for (const id of collectThsBranchIds(section.tree)) ids.add(id);
      }
      setExpanded(ids);
      return;
    }
    if (filteredTree) {
      setExpanded(new Set(collectThsBranchIds(filteredTree)));
      return;
    }
    if (!kindEntry?.tree) return;
    const root = parseThsTree(kindEntry.tree);
    if (!root) return;
    setExpanded(new Set(collectThsBranchIds(root)));
  };

  const collapseAllBranches = () => setExpanded(new Set());

  const openDetail = async (row: ManagedBlockRow) => {
    setSelected(row);
    setStocksDetail(null);
    setQuotes({});
    if (row.node_type === "branch") return;
    const stocksKind = thsStocksKind(row);
    if (!row.has_ths || !row.id || !stocksKind) {
      setStocksLoading(false);
      return;
    }
    setStocksLoading(true);
    try {
      const detail = await api.thsBlockStocks(stocksKind, row.id);
      setStocksDetail(detail);
      const codes = detail.stocks.map((s) => s.code);
      const quoteMap: Record<string, Quote> = {};
      for (const batch of chunk(codes, 40)) {
        if (!batch.length) continue;
        try {
          const part = await api.quote(batch.join(","));
          Object.assign(quoteMap, part);
        } catch {
          /* 行情失败不影响列表 */
        }
      }
      setQuotes(quoteMap);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "加载成分股失败");
    } finally {
      setStocksLoading(false);
    }
  };

  const emptyThs = !thsSnap?.updated_at;
  const emptyKpl = !snapshot?.kpl?.available;
  const emptyCache = emptyThs && emptyKpl;
  const linkerDown = snapshot?.linker_unavailable;
  const linkerMessage = snapshot?.linker_message || "依赖于第三方工具，目前无法请求";
  const selectedSubtype = selected ? thsCustomSubtypeLabel(selected) : null;
  const selectedAliases = selected
    ? aliasesForBlockName(selected.name, aliasesByCanonical)
    : [];
  const visibleCount = filteredRows.length;

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <Boxes className="h-5 w-5 text-primary" />
              <h1 className="text-xl font-bold text-foreground">板块管理</h1>
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              同花顺与开盘啦按名称融合；开盘啦目录每日自动最多拉取一次，手动「刷新板块」可强制更新。
            </p>
          </div>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void refreshAll()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshingKind
              ? `刷新 ${refreshingKind === "kpl" ? "开盘啦" : thsBlockKindLabel(refreshingKind)}…`
              : "刷新板块"}
          </button>
        </div>

        {linkerDown && (
          <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
            {linkerMessage}
          </div>
        )}

        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">来源</span>
            {([
              { value: "all" as const, label: "全部" },
              { value: "ths" as const, label: "同花顺" },
              { value: "kpl" as const, label: "开盘啦" },
            ]).map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  setSourceFilter(opt.value);
                  setSelected(null);
                  setStocksDetail(null);
                }}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-semibold transition-colors",
                  sourceFilter === opt.value
                    ? "bg-foreground text-background"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* key=sourceFilter：来源切换时整行重挂载，避免页签增删与前缀 span 原地 reconcile 触发 removeChild */}
          <div key={sourceFilter} className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">类型</span>
            {visibleTypeTabs.map((k) => {
              const isThs = "thsKind" in k;
              const count = isThs
                ? (snapshot?.merged?.[k.value]?.length ?? thsSnap?.kinds?.[k.thsKind]?.count)
                : (snapshot?.merged?.[k.value]?.length ?? snapshot?.kpl?.kinds?.[k.kplKind]?.count);
              const loaded = isThs
                ? thsSnap?.kinds?.[k.thsKind] != null || (snapshot?.merged?.[k.value]?.length ?? 0) > 0
                : (count ?? 0) > 0 || !!snapshot?.kpl?.kinds?.[k.kplKind];
              const hasErr = isThs && kindHasError(thsSnap?.errors || snapshot?.errors, k.thsKind);
              const active = kindFilter === k.value;
              const prefix = sourceFilter === "all" ? (isThs ? "同花顺·" : "开盘啦·") : null;
              return (
                <button
                  key={k.value}
                  type="button"
                  onClick={() => {
                    setKindFilter(k.value);
                    setSelected(null);
                    setStocksDetail(null);
                  }}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors",
                    active
                      ? isThs
                        ? "border-sky-500/50 bg-sky-500/10 text-sky-800 dark:text-sky-300"
                        : "border-emerald-500/50 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                    hasErr && "border-amber-500/50",
                  )}
                  title={isThs ? "同花顺原始类型" : "开盘啦原始类型"}
                >
                  {prefix != null && <span className="mr-1 opacity-60">{prefix}</span>}
                  <span>{k.label}</span>
                  {count != null && (
                    <span className="ml-1.5 tabular-nums opacity-70">{count}</span>
                  )}
                  {!loaded && !emptyCache && (
                    <span className="ml-1 text-xs opacity-60">未加载</span>
                  )}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => {
                setKindFilter(FOLLOWED_KIND);
                setSelected(null);
                setStocksDetail(null);
              }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors",
                isFollowedView
                  ? "border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300"
                  : "border-border bg-background text-muted-foreground hover:border-amber-500/35 hover:text-amber-700 dark:hover:text-amber-300",
              )}
            >
              <Star className={cn("h-3.5 w-3.5", isFollowedView && "fill-current")} />
              <span>关注</span>
              <span className="tabular-nums opacity-70">{followBlocks.length}</span>
            </button>
          </div>
        </div>

        <div className="mt-2">
          <Link
            to={keywordsSettingsTo("theme-aliases")}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          >
            板块别名 →
          </Link>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {linkerDown ? (
            <span className="text-amber-700 dark:text-amber-300">{linkerMessage}</span>
          ) : emptyCache ? (
            <span className="text-amber-700 dark:text-amber-300">尚未加载 — 请点击「刷新板块」</span>
          ) : (
            <>
              <span>
                同花顺 <strong className="text-foreground">{thsSnap?.updated_at || "未加载"}</strong>
              </span>
              <span>
                开盘啦 <strong className="text-foreground">{snapshot?.kpl?.fetched_date || "未加载"}</strong>
                {snapshot?.kpl?.from_cache ? "（当日缓存）" : snapshot?.kpl?.available ? "（刚拉取）" : ""}
              </span>
              {snapshot?.ths_dir && (
                <span className="max-w-xs truncate" title={snapshot.ths_dir}>{snapshot.ths_dir}</span>
              )}
            </>
          )}
          {isFollowedView && (
            <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-0.5 text-amber-700 dark:text-amber-300">
              <Star className="h-3 w-3 fill-current" />
              已关注 {followBlocks.length} · 可解析 {allRows.length}
            </span>
          )}
          {kindEntry?.branch_count != null && (
            <span className="inline-flex items-center gap-1 rounded-md bg-muted/40 px-2 py-0.5">
              <Network className="h-3 w-3" />
              分组 {kindEntry.branch_count} · 板块 {kindEntry.leaf_count}
            </span>
          )}
          {kindEntry?.tree_mode === "flat_fallback" && (
            <span className="text-amber-700 dark:text-amber-300">树结构不可用，已展示 flat 列表</span>
          )}
          {kindEntry && !isFollowedView && thsKindForTab && (
            <button
              type="button"
              disabled={refreshing}
              onClick={() => void refreshOneKind(thsKindForTab)}
              className="text-primary hover:underline disabled:opacity-50"
            >
              仅刷新当前同花顺类型
            </button>
          )}
        </div>
      </section>

      <section className="w-full min-w-0">
        <div className="grid w-full min-w-0 gap-4 xl:grid-cols-5">
          <div className="glass min-w-0 overflow-hidden rounded-2xl xl:col-span-3">
            <div className="border-b border-border/60 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative min-w-[200px] flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    className={inputCls}
                    placeholder="搜索代码、名称、别名、树路径…"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                  />
                </div>
                <select
                  className={selectCls}
                  value={nodeFilter}
                  onChange={(e) => setNodeFilter(e.target.value as typeof nodeFilter)}
                >
                  <option value="all">全部节点</option>
                  <option value="leaf">仅叶子板块</option>
                  <option value="branch">仅分组</option>
                </select>
                <div className="inline-flex rounded-lg border border-border p-0.5">
                  <button
                    type="button"
                    disabled={!canShowTree && viewMode === "list"}
                    onClick={() => setViewMode("tree")}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors",
                      viewMode === "tree"
                        ? "bg-primary/15 text-primary"
                        : "text-muted-foreground hover:text-foreground",
                      !canShowTree && "opacity-50",
                    )}
                  >
                    <Network className="h-3.5 w-3.5" /> 树形
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("list")}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors",
                      viewMode === "list"
                        ? "bg-primary/15 text-primary"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <LayoutList className="h-3.5 w-3.5" /> 列表
                  </button>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  <span>共 </span>
                  <strong className="text-foreground">{visibleCount}</strong>
                  <span> 条</span>
                  <span>
                    {isFollowedView
                      ? " · 关注"
                      : ` · ${tabOrigin === "kpl" ? "开盘啦" : tabOrigin === "ths" ? "同花顺" : ""}${thsBlockKindLabel(kindFilter)}`}
                  </span>
                  {sourceFilter === "ths" && <span> · 筛选同花顺</span>}
                  {sourceFilter === "kpl" && <span> · 筛选开盘啦</span>}
                  {viewMode === "tree" && canShowTree && <span> · 树形浏览</span>}
                </p>
                {viewMode === "tree" && canShowTree && (
                  <div className="flex items-center gap-2 text-xs">
                    <button type="button" onClick={expandAllBranches} className="text-primary hover:underline">
                      全部展开
                    </button>
                    <span className="text-muted-foreground/50">|</span>
                    <button type="button" onClick={collapseAllBranches} className="text-primary hover:underline">
                      全部折叠
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="max-h-[calc(100vh-280px)] overflow-auto p-2">
              {loading ? (
                <div className="flex items-center justify-center gap-2 p-12 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" /> 加载中…
                </div>
              ) : linkerDown && emptyKpl && emptyThs ? (
                <div className="p-12 text-center text-sm text-amber-700 dark:text-amber-300">
                  {linkerMessage}
                </div>
              ) : emptyCache ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  点击右上角「刷新板块」加载同花顺与开盘啦目录
                </div>
              ) : isFollowedView ? (
                !followBlocks.length ? (
                  <p className="p-12 text-center text-sm text-muted-foreground">
                    暂无关注板块，在概念 / 行业等类型中点击星标即可收藏
                  </p>
                ) : !allRows.length ? (
                  <p className="p-12 text-center text-sm text-muted-foreground">
                    已关注 {followBlocks.length} 个板块，但当前缓存中未找到对应数据，请先刷新板块
                  </p>
                ) : viewMode === "tree" && canShowTree ? (
                  followedTreeSections.length || followedFlatGroups.length ? (
                    <div className="space-y-4 py-1">
                      {followedTreeSections.map((section) => (
                        <div key={section.kind}>
                          <p className="mb-1 px-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                            {section.label}
                          </p>
                          <ThsBlockTreeItem
                            node={section.tree}
                            depth={0}
                            expanded={expanded}
                            rowById={section.rowById}
                            selectedId={selected ? blockTreeNodeId(selected) : null}
                            followedIds={followedIds}
                            aliasesByCanonical={aliasesByCanonical}
                            onToggle={toggleExpanded}
                            onSelect={(row) => void openDetail(row)}
                            onToggleFollow={(row) => void toggleFollow(row)}
                          />
                        </div>
                      ))}
                      {followedFlatGroups.map((group) => (
                        <div key={group.kind}>
                          <p className="mb-1 px-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                            {group.label}
                          </p>
                          <div className="space-y-0.5">
                            {group.rows.map((row) => {
                              const active = selected?.kind === row.kind && selected?.id === row.id;
                              const followed = followedIds.has(`${row.kind}|${row.id}`);
                              const aliases = aliasesForBlockName(row.name, aliasesByCanonical);
                              const aliasText = aliases.length ? aliases.join("、") : "";
                              return (
                                <div
                                  key={`${row.kind}-${row.id}`}
                                  className={cn(
                                    "group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm transition-colors",
                                    "hover:bg-muted/40",
                                    active && "bg-primary/10 ring-1 ring-primary/20",
                                  )}
                                >
                                  <button
                                    type="button"
                                    onClick={() => void openDetail(row)}
                                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                                  >
                                    <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                                      <Boxes className="h-3.5 w-3.5 text-primary/70" />
                                    </span>
                                    <span className="min-w-0 flex-1 truncate font-medium text-foreground">
                                      {row.name || row.id}
                                    </span>
                                    {aliasText && (
                                      <span
                                        className="hidden max-w-[140px] shrink truncate text-[11px] text-muted-foreground lg:inline"
                                        title={`别名：${aliasText}`}
                                      >
                                        {aliasText}
                                      </span>
                                    )}
                                    {row.stock_count != null && (
                                      <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
                                        {row.stock_count}
                                      </span>
                                    )}
                                  </button>
                                  <FollowBlockButton
                                    followed={followed}
                                    onToggle={() => void toggleFollow(row)}
                                    className="opacity-70 group-hover:opacity-100"
                                  />
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="p-8 text-center text-sm text-muted-foreground">无匹配板块</p>
                  )
                ) : (
                  <FollowedOrKindTable
                    filteredRows={filteredRows}
                    showSubtypeCol={false}
                    sort={sort}
                    order={order}
                    onSort={toggleSort}
                    selected={selected}
                    followedIds={followedIds}
                    aliasesByCanonical={aliasesByCanonical}
                    onOpen={(row) => void openDetail(row)}
                    onToggleFollow={(row) => void toggleFollow(row)}
                  />
                )
              ) : !allRows.length && !kindEntry ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  {tabOrigin === "kpl"
                    ? "该开盘啦类型暂无数据"
                    : "该同花顺类型尚未加载"}
                  {thsKindForTab && kindHasError(thsSnap?.errors || snapshot?.errors, thsKindForTab) && (
                    <p className="mt-2 text-amber-700 dark:text-amber-300">
                      {(thsSnap?.errors || snapshot?.errors || [])
                        .find((e) => e.startsWith(`${thsKindForTab}:`))
                        ?.slice(thsKindForTab.length + 2)}
                    </p>
                  )}
                </div>
              ) : viewMode === "tree" && canShowTree ? (
                filteredTree ? (
                  <div className="py-1">
                    <ThsBlockTreeItem
                      node={filteredTree}
                      depth={0}
                      expanded={expanded}
                      rowById={rowById}
                      selectedId={selected ? blockTreeNodeId(selected) : null}
                      followedIds={followedIds}
                      aliasesByCanonical={aliasesByCanonical}
                      onToggle={toggleExpanded}
                      onSelect={(row) => void openDetail(row)}
                      onToggleFollow={(row) => void toggleFollow(row)}
                    />
                  </div>
                ) : (
                  <p className="p-8 text-center text-sm text-muted-foreground">无匹配板块</p>
                )
              ) : (
                <FollowedOrKindTable
                  filteredRows={filteredRows}
                  showSubtypeCol={showSubtypeCol}
                  sort={sort}
                  order={order}
                  onSort={toggleSort}
                  selected={selected}
                  followedIds={followedIds}
                  aliasesByCanonical={aliasesByCanonical}
                  onOpen={(row) => void openDetail(row)}
                  onToggleFollow={(row) => void toggleFollow(row)}
                />
              )}
            </div>
          </div>

          <div className="glass min-w-0 rounded-2xl xl:col-span-2">
            <div className="border-b border-border/60 px-4 py-3">
              <p className="text-xs font-bold uppercase tracking-wider text-primary">板块详情</p>
            </div>
            <div className="max-h-[calc(100vh-280px)] overflow-auto p-4">
              {!selected ? (
                <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
                  <Boxes className="h-10 w-10 text-muted-foreground/30" />
                  <p className="text-sm text-muted-foreground">选择左侧板块查看详情与成分股</p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-foreground">{selected.name || selected.id || selected.kpl_code}</h2>
                      <SourceBadges row={selected} />
                      {selected.node_type && (
                        <span className={cn(
                          "rounded-md px-2 py-0.5 text-[11px] font-bold",
                          selected.node_type === "branch"
                            ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                            : "bg-primary/15 text-primary",
                        )}>
                          {THS_NODE_TYPE_LABEL[selected.node_type] || selected.node_type}
                        </span>
                      )}
                      {selected.has_ths && selected.id && thsStocksKind(selected) && (
                        <FollowBlockButton
                          followed={followedIds.has(`${thsStocksKind(selected)}|${selected.id}`)}
                          onToggle={() => void toggleFollow(selected)}
                          size="md"
                        />
                      )}
                    </div>
                    {selected.has_ths && (() => {
                      const sub = thsBlockCodeSubtitle(selected);
                      return (
                        <p className="mt-1 font-mono text-xs">
                          <span className="font-medium text-foreground">{sub.primary}</span>
                          {sub.secondary && (
                            <span className="text-muted-foreground"> · {sub.secondary}</span>
                          )}
                        </p>
                      );
                    })()}
                    {selected.kpl_code && (
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        开盘啦 <span className="font-medium text-foreground">{selected.kpl_code}</span>
                        {selected.kpl_kind_label ? ` · ${selected.kpl_kind_label}` : ""}
                      </p>
                    )}
                    {selected.tree_path && (
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{selected.tree_path}</p>
                    )}
                  </div>

                  <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                      <dt className="text-muted-foreground">类型</dt>
                      <dd className="text-foreground">{thsBlockKindLabel(selected.kind) || selected.kpl_kind_label || "—"}</dd>
                      {selected.code && (
                        <>
                          <dt className="text-muted-foreground">同花顺行情码</dt>
                          <dd className="font-mono text-foreground">{selected.code}</dd>
                        </>
                      )}
                      {selected.id && (
                        <>
                          <dt className="text-muted-foreground">同花顺本地 ID</dt>
                          <dd className="font-mono text-muted-foreground">{selected.id}</dd>
                        </>
                      )}
                      {selected.kpl_code && (
                        <>
                          <dt className="text-muted-foreground">开盘啦 PlateID</dt>
                          <dd className="font-mono text-foreground">{selected.kpl_code}</dd>
                        </>
                      )}
                      {selected.kpl_power != null && (
                        <>
                          <dt className="text-muted-foreground">开盘啦人气</dt>
                          <dd className="text-foreground">{selected.kpl_power}</dd>
                        </>
                      )}
                      {selected.kpl_pct != null && (
                        <>
                          <dt className="text-muted-foreground">开盘啦涨幅</dt>
                          <dd className="text-foreground">{selected.kpl_pct}%</dd>
                        </>
                      )}
                      {selectedSubtype && (
                        <>
                          <dt className="text-muted-foreground">子类型</dt>
                          <dd className="text-foreground">{selectedSubtype}</dd>
                        </>
                      )}
                      {selected.hex_id && (
                        <>
                          <dt className="text-muted-foreground">Hex ID</dt>
                          <dd className="font-mono text-foreground">{selected.hex_id}</dd>
                        </>
                      )}
                      {selected.query_key && (
                        <>
                          <dt className="text-muted-foreground">问财 Key</dt>
                          <dd className="break-all text-foreground">{selected.query_key}</dd>
                        </>
                      )}
                      {selected.stock_count != null && (
                        <>
                          <dt className="text-muted-foreground">成分数</dt>
                          <dd className="text-foreground">{selected.stock_count}</dd>
                        </>
                      )}
                    </dl>
                  </div>

                  <DetailSection label="板块别名">
                    <p className="mb-2 text-xs text-muted-foreground">
                      与配置中的板块别名同源；别名匹配到标准名「{selected.name || selected.id}」。
                      {" "}
                      <Link
                        to={keywordsSettingsTo("theme-aliases")}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-primary underline-offset-2 hover:underline"
                      >
                        打开配置 →
                      </Link>
                    </p>
                    {selectedAliases.length === 0 ? (
                      <p className="mb-2 text-xs text-muted-foreground">暂无别名，可在下方添加。</p>
                    ) : (
                      <ul className="mb-3 space-y-1.5">
                        {selectedAliases.map((alias) => {
                          const editing = aliasEditingKey === alias;
                          return (
                            <li
                              key={alias}
                              className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border/50 bg-background/60 px-2.5 py-1.5"
                            >
                              {editing ? (
                                <>
                                  <input
                                    className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
                                    value={aliasEditDraft}
                                    onChange={(e) => setAliasEditDraft(e.target.value)}
                                    disabled={aliasSaving}
                                    placeholder="别名"
                                    maxLength={ALIAS_MAX_LEN}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        void saveEditAlias();
                                      } else if (e.key === "Escape") {
                                        setAliasEditingKey(null);
                                        setAliasEditDraft("");
                                      }
                                    }}
                                  />
                                  <button
                                    type="button"
                                    disabled={aliasSaving}
                                    onClick={() => void saveEditAlias()}
                                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-primary hover:bg-primary/10 disabled:opacity-50"
                                    title="保存"
                                  >
                                    <Check className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    disabled={aliasSaving}
                                    onClick={() => {
                                      setAliasEditingKey(null);
                                      setAliasEditDraft("");
                                    }}
                                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                                    title="取消"
                                  >
                                    <X className="h-3.5 w-3.5" />
                                  </button>
                                </>
                              ) : (
                                <>
                                  <button
                                    type="button"
                                    disabled={aliasSaving || aliasEditingKey != null}
                                    onClick={() => {
                                      setAliasEditingKey(alias);
                                      setAliasEditDraft(alias);
                                    }}
                                    className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground hover:text-primary disabled:opacity-50"
                                    title={`点击修改「${alias}」`}
                                  >
                                    {alias}
                                  </button>
                                  <button
                                    type="button"
                                    disabled={aliasSaving || aliasEditingKey != null}
                                    onClick={() => {
                                      setAliasEditingKey(alias);
                                      setAliasEditDraft(alias);
                                    }}
                                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                                    title={`编辑「${alias}」`}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    type="button"
                                    disabled={aliasSaving || aliasEditingKey != null}
                                    onClick={() => void removeAlias(alias)}
                                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                                    title={`删除「${alias}」`}
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </button>
                                </>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm"
                        value={aliasDraft}
                        onChange={(e) => setAliasDraft(e.target.value)}
                        disabled={aliasSaving || aliasEditingKey != null}
                        placeholder="新增别名（原始写法）"
                        maxLength={ALIAS_MAX_LEN}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void addAliasForSelected();
                          }
                        }}
                      />
                      <button
                        type="button"
                        disabled={aliasSaving || aliasEditingKey != null || !aliasDraft.trim()}
                        onClick={() => void addAliasForSelected()}
                        className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs font-semibold text-foreground hover:bg-muted/40 disabled:opacity-50"
                      >
                        {aliasSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                        添加
                      </button>
                    </div>
                  </DetailSection>

                  {selected.node_type === "branch" ? (
                    <p className="rounded-lg bg-muted/25 px-3 py-2 text-sm text-muted-foreground">
                      分组节点不含成分股，请展开并选择叶子板块。
                    </p>
                  ) : !selected.has_ths || !selected.id || !thsStocksKind(selected) ? (
                    <p className="rounded-lg bg-muted/25 px-3 py-2 text-sm text-muted-foreground">
                      仅开盘啦类型的板块暂无同花顺成分股；可在短线盘面用人气/点查查看。
                    </p>
                  ) : (
                    <DetailSection label="成分股">
                      <p className="mb-2 text-xs text-muted-foreground">
                        口径：按同花顺板块成分股（本地 INI），不以开盘啦成分为准。
                      </p>
                      {stocksLoading ? (
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" /> 加载成分股…
                        </div>
                      ) : stocksDetail ? (
                        <>
                          <p className="mb-2 text-xs text-muted-foreground">
                            共 <strong className="text-foreground">{stocksDetail.count}</strong> 只
                          </p>
                          {stocksDetail.count === 0 ? (
                            <p className="text-sm text-muted-foreground">暂无成分股数据</p>
                          ) : (
                            <BlockStocksTable
                              key={`${selected.kind}-${selected.id}`}
                              stocks={stocksDetail.stocks}
                              quotes={quotes}
                            />
                          )}
                        </>
                      ) : (
                        <p className="text-sm text-muted-foreground">—</p>
                      )}
                    </DetailSection>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      <Disclaimer />
    </div>
  );
}
