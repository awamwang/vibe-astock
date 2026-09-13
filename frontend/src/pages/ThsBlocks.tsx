import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Boxes, ChevronDown, ChevronRight, Folder, FolderOpen,
  LayoutList, Loader2, Network, RefreshCw, Search, Star,
} from "lucide-react";
import { toast } from "sonner";
import {
  BlockDetailPanel, FollowBlockButton, SourceBadges, thsStocksKind,
} from "@/components/block/BlockDetailPanel";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type BlocksManageSnapshot, type ManagedBlockRow, type ThemeAliasEntry,
  type ThsTreeNode,
} from "@/lib/api";
import {
  isBlockFollowed, setFollowBlocksCache, type FollowBlock,
} from "@/lib/message-follow-blocks";
import {
  THS_BLOCK_KINDS, BLOCK_MANAGE_KINDS, THS_NODE_TYPE_LABEL,
  aliasesForBlockName, attachOrphanLeavesToTree, blockTreeNodeId,
  buildAliasesByCanonical, buildSyntheticBlockTree, collectThsBranchIds,
  collectThsNodeIds, filterThsTree, manageTabKplKind, manageTabThsKind,
  parseThsTree, sortRowsByTreeOrder,
  themeAliasEntriesFromConfig, thsBlockKindLabel, thsBlockPrimaryCode,
  thsCustomSubtypeLabel,
} from "@/lib/thsBlocks";
import { keywordsSettingsTo } from "@/lib/settingsNav";

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

function kindHasError(errors: string[] | undefined, kind: string): boolean {
  return (errors || []).some((e) => e.startsWith(`${kind}:`));
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

  const [kindFilter, setKindFilter] = useState<string>("conception");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [q, setQ] = useState("");
  const [nodeFilter, setNodeFilter] = useState<"all" | "leaf" | "branch">("all");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortKey>("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");

  const [selected, setSelected] = useState<ManagedBlockRow | null>(null);
  const [followBlocks, setFollowBlocks] = useState<FollowBlock[]>([]);
  const [aliasEntries, setAliasEntries] = useState<ThemeAliasEntry[]>([]);

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

  const refreshThs = async () => {
    setRefreshing(true);
    setRefreshingKind("ths");
    // 先清详情，避免刷新后大列表 reconcile 时详情区条件节点与表格同时撕裂 DOM
    setSelected(null);
    const failed: string[] = [];

    for (const k of THS_BLOCK_KINDS) {
      try {
        await api.thsBlocksRefreshKind(k.value);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "刷新失败";
        failed.push(`${k.label}: ${msg}`);
      }
    }

    let latest: BlocksManageSnapshot | null = null;
    try {
      latest = await api.blocksManage();
      setSnapshot(latest);
    } catch {
      /* ignore */
    }

    const loaded = latest?.ths?.kinds ? Object.keys(latest.ths.kinds).length : 0;
    const toastMsg = latest?.linker_unavailable
      ? { type: "error" as const, text: latest.linker_message || "依赖于第三方工具，目前无法请求" }
      : failed.length
        ? {
            type: "error" as const,
            text: `同花顺部分刷新失败（${loaded}/${THS_BLOCK_KINDS.length}）：${failed.join("；")}`,
          }
        : { type: "success" as const, text: `同花顺已刷新 · ${latest?.ths?.updated_at || "—"}` };

    setRefreshingKind(null);
    setRefreshing(false);
    // toast 延后到本次 commit 之后，避免与列表/详情卸载抢 DOM
    window.setTimeout(() => {
      if (toastMsg.type === "error") notify.error(toastMsg.text);
      else notify.success(toastMsg.text);
    }, 0);
  };

  const refreshKpl = async () => {
    setRefreshing(true);
    setRefreshingKind("kpl");
    setSelected(null);
    let toastMsg: { type: "success" | "error"; text: string } | null = null;
    try {
      const latest = await api.blocksManageRefreshKpl();
      setSnapshot(latest);
      if (latest.linker_unavailable) {
        toastMsg = { type: "error", text: latest.linker_message || "依赖于第三方工具，目前无法请求" };
      } else {
        toastMsg = { type: "success", text: `开盘啦已刷新 · ${latest.kpl?.fetched_date || "—"}` };
      }
    } catch (e) {
      toastMsg = { type: "error", text: e instanceof ApiError ? e.message : "开盘啦刷新失败" };
      try {
        const latest = await api.blocksManage();
        setSnapshot(latest);
      } catch {
        /* ignore */
      }
    } finally {
      setRefreshingKind(null);
      setRefreshing(false);
      if (toastMsg) {
        const msg = toastMsg;
        window.setTimeout(() => {
          if (msg.type === "error") notify.error(msg.text);
          else notify.success(msg.text);
        }, 0);
      }
    }
  };

  const refreshOneKind = async (kind: string) => {
    setRefreshing(true);
    setRefreshingKind("ths");
    setSelected(null);
    let toastMsg: { type: "success" | "error"; text: string } | null = null;
    try {
      await api.thsBlocksRefreshKind(kind);
      const data = await api.blocksManage();
      setSnapshot(data);
      const label = thsBlockKindLabel(kind);
      const err = (data.ths?.errors || data.errors || []).find((e) => e.startsWith(`${kind}:`));
      if (err) {
        toastMsg = { type: "error", text: `${label}：${err.slice(kind.length + 2)}` };
      } else {
        toastMsg = { type: "success", text: `${label} 已刷新` };
      }
    } catch (e) {
      toastMsg = { type: "error", text: e instanceof ApiError ? e.message : "刷新失败" };
    } finally {
      setRefreshingKind(null);
      setRefreshing(false);
      if (toastMsg) {
        const msg = toastMsg;
        window.setTimeout(() => {
          if (msg.type === "error") notify.error(msg.text);
          else notify.success(msg.text);
        }, 0);
      }
    }
  };

  const isFollowedView = kindFilter === FOLLOWED_KIND;
  const thsKindForTab = manageTabThsKind(kindFilter);
  const kplKindForTab = manageTabKplKind(kindFilter);

  /** 当前来源下可选的类型页签（概念/行业/地域不按来源拆分） */
  const visibleTypeTabs = useMemo(() => {
    if (sourceFilter === "ths") {
      return BLOCK_MANAGE_KINDS.filter((k) => "thsKind" in k);
    }
    if (sourceFilter === "kpl") {
      return BLOCK_MANAGE_KINDS.filter((k) => "kplKind" in k);
    }
    return [...BLOCK_MANAGE_KINDS];
  }, [sourceFilter]);

  useEffect(() => {
    if (isFollowedView) return;
    if (!visibleTypeTabs.some((t) => t.value === kindFilter)) {
      setKindFilter(visibleTypeTabs[0]?.value || "conception");
      setSelected(null);
    }
  }, [sourceFilter, visibleTypeTabs, kindFilter, isFollowedView]);

  /** 关注视图：从融合行解析已关注；普通视图：当前类型页签，可再按来源筛行 */
  const allRows = useMemo(() => {
    const matchSource = (row: ManagedBlockRow) => {
      if (sourceFilter === "ths") return row.has_ths || row.origin === "ths";
      if (sourceFilter === "kpl") return row.has_kpl || row.origin === "kpl";
      return true;
    };
    if (!isFollowedView) {
      return (snapshot?.merged?.[kindFilter] || []).filter(matchSource);
    }
    const out: ManagedBlockRow[] = [];
    const seen = new Set<string>();
    for (const fb of followBlocks) {
      const key = `${fb.kind}|${fb.id}`;
      if (seen.has(key)) continue;
      const row = (snapshot?.merged?.[fb.kind] || []).find((r) => r.id === fb.id);
      if (row && matchSource(row)) {
        seen.add(key);
        out.push(row);
      }
    }
    return out;
  }, [isFollowedView, kindFilter, snapshot, followBlocks, sourceFilter]);

  const kindEntry = isFollowedView || !thsKindForTab
    ? null
    : thsSnap?.kinds?.[thsKindForTab];
  const showSubtypeCol = thsKindForTab === "custom";

  /** 关注视图：任一关注项所属 kind 有树即可树形浏览 */
  const followedTreeSections = useMemo(() => {
    if (!isFollowedView || !thsSnap?.kinds) return [];
    const matchSource = (row: ManagedBlockRow) => {
      if (sourceFilter === "ths") return row.has_ths || row.origin === "ths";
      if (sourceFilter === "kpl") return false; // 关注仅同花顺
      return row.has_ths || row.origin === "ths";
    };
    const sections: { kind: string; label: string; tree: ThsTreeNode; rowById: Map<string, ManagedBlockRow> }[] = [];
    for (const k of THS_BLOCK_KINDS) {
      const entry = thsSnap.kinds[k.value];
      const followedInKind = followBlocks.filter((b) => b.kind === k.value);
      if (!followedInKind.length) continue;
      const mergedRows = (snapshot?.merged?.[k.value] || []).filter(matchSource);
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
      kplKindForTab ? `__kpl_${kplKindForTab}_root__` : "",
      "__hot_root__",
    ].filter(Boolean)));
  }, [kindFilter, kplKindForTab, canShowTree, viewMode, kindEntry?.tree, kindEntry?.tree_mode, isFollowedView, followedTreeSections]);

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
      root = buildSyntheticBlockTree(
        allRows,
        label,
        kplKindForTab && !thsKindForTab
          ? `__kpl_${kplKindForTab}_root__`
          : `__root_${kindFilter}__`,
      );
    }
    return filterThsTree(root, {
      query: q,
      nodeFilter,
      codeById,
      aliasesByName: aliasesByCanonical,
    });
  }, [isFollowedView, viewMode, kindEntry?.tree, kindEntry?.tree_mode, q, nodeFilter, allRows, aliasesByCanonical, kindFilter, kplKindForTab, thsKindForTab]);

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

  const openDetail = (row: ManagedBlockRow) => {
    setSelected(row);
  };

  const emptyThs = !thsSnap?.updated_at;
  const emptyKpl = !snapshot?.kpl?.available;
  const emptyCache = emptyThs && emptyKpl;
  const linkerDown = snapshot?.linker_unavailable;
  const linkerMessage = snapshot?.linker_message || "依赖于第三方工具，目前无法请求";
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
              概念 / 行业 / 地域按名称跨来源融合；开盘啦目录每日自动最多拉取一次，可分别强制刷新同花顺或开盘啦。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={refreshing}
              onClick={() => void refreshThs()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
            >
              <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
                {refreshing && refreshingKind === "ths" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </span>
              <span>{refreshing && refreshingKind === "ths" ? "刷新同花顺…" : "刷新同花顺"}</span>
            </button>
            <button
              type="button"
              disabled={refreshing}
              onClick={() => void refreshKpl()}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted/50 disabled:opacity-50"
            >
              <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
                {refreshing && refreshingKind === "kpl" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
              </span>
              <span>{refreshing && refreshingKind === "kpl" ? "刷新开盘啦…" : "刷新开盘啦"}</span>
            </button>
          </div>
        </div>

        {linkerDown && (
          <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
            {linkerMessage}
          </div>
        )}

        {!linkerDown && emptyThs && !emptyKpl && (
          <div className="mt-4 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-3 text-sm text-sky-900 dark:text-sky-200">
            同花顺板块缓存未加载（重启后需重新拉取）。请点击右上角「刷新同花顺」；来源请选「全部」或「同花顺」查看。
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

          {/* 类型页签始终挂载：用 hidden 切换可见性，避免来源切换时增删节点触发 insertBefore/removeChild */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">类型</span>
            {BLOCK_MANAGE_KINDS.map((k) => {
              const hasThs = "thsKind" in k;
              const hasKpl = "kplKind" in k;
              const tabVisible =
                sourceFilter === "all"
                || (sourceFilter === "ths" && hasThs)
                || (sourceFilter === "kpl" && hasKpl);
              const fused = Boolean(k.fused);
              const rows = snapshot?.merged?.[k.value] || [];
              const count = (() => {
                if (rows.length || snapshot?.merged?.[k.value]) {
                  if (sourceFilter === "ths") {
                    return rows.filter((r) => r.has_ths || r.origin === "ths").length;
                  }
                  if (sourceFilter === "kpl") {
                    return rows.filter((r) => r.has_kpl || r.origin === "kpl").length;
                  }
                  return rows.length;
                }
                if (hasThs && k.thsKind) return thsSnap?.kinds?.[k.thsKind]?.count;
                if (hasKpl && k.kplKind) return snapshot?.kpl?.kinds?.[k.kplKind]?.count;
                return undefined;
              })();
              const loaded = (count ?? 0) > 0
                || (hasThs && k.thsKind != null && thsSnap?.kinds?.[k.thsKind] != null)
                || (hasKpl && k.kplKind != null && !!snapshot?.kpl?.kinds?.[k.kplKind]);
              const hasErr = hasThs && k.thsKind != null
                && kindHasError(thsSnap?.errors || snapshot?.errors, k.thsKind);
              const active = kindFilter === k.value;
              return (
                <button
                  key={k.value}
                  type="button"
                  hidden={!tabVisible}
                  onClick={() => {
                    setKindFilter(k.value);
                    setSelected(null);
                  }}
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm font-semibold transition-colors",
                    active
                      ? fused
                        ? "border-primary/50 bg-primary/10 text-primary"
                        : hasThs && !hasKpl
                          ? "border-sky-500/50 bg-sky-500/10 text-sky-800 dark:text-sky-300"
                          : "border-emerald-500/50 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                    hasErr && "border-amber-500/50",
                  )}
                  title={fused ? "同花顺与开盘啦按名称融合" : hasThs ? "同花顺" : "开盘啦"}
                >
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
            <span className="text-amber-700 dark:text-amber-300">尚未加载 — 请点击「刷新同花顺」或「刷新开盘啦」</span>
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
                      : ` · ${thsBlockKindLabel(kindFilter)}`}
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
                  点击右上角「刷新同花顺」或「刷新开盘啦」加载目录
                </div>
              ) : isFollowedView ? (
                !followBlocks.length ? (
                  <p className="p-12 text-center text-sm text-muted-foreground">
                    暂无关注板块，在概念 / 行业等类型中点击星标即可收藏
                  </p>
                ) : !allRows.length ? (
                  <p className="p-12 text-center text-sm text-muted-foreground">
                    已关注 {followBlocks.length} 个板块，但当前缓存中未找到对应数据，请先刷新同花顺
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
                  {kindFilter === "hot"
                    ? "该人气类型暂无数据"
                    : "该类型尚未加载或当前来源下无匹配"}
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
                <BlockDetailPanel
                  key={managedRowKey(selected)}
                  kind={thsStocksKind(selected) || selected.kind}
                  blockId={selected.id || selected.kpl_code || selected.name}
                  name={selected.name || selected.id || selected.kpl_code}
                  code={selected.code}
                  row={selected}
                  aliasEntries={aliasEntries}
                  onAliasEntriesChange={setAliasEntries}
                  followBlocks={followBlocks}
                  onFollowBlocksChange={setFollowBlocks}
                />
              )}
            </div>
          </div>
        </div>
      </section>

      <Disclaimer />
    </div>
  );
}
