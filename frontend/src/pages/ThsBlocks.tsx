import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Boxes, ChevronDown, ChevronRight, Folder, FolderOpen,
  LayoutList, Loader2, Network, RefreshCw, Search,
} from "lucide-react";
import { toast } from "sonner";
import { BlockStocksTable } from "@/components/block/BlockStocksTable";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type Quote, type ThsBlockRow, type ThsBlocksSnapshot, type ThsBlockStocksDetail,
  type ThsTreeNode,
} from "@/lib/api";
import {
  THS_BLOCK_KINDS, THS_NODE_TYPE_LABEL,
  collectThsBranchIds, filterThsTree, parseThsTree,
  sortRowsByTreeOrder, thsBlockKindLabel, thsCustomSubtypeLabel,
} from "@/lib/thsBlocks";

const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const inputCls =
  "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground";

type SortKey = "id" | "name" | "node_type" | "tree_path" | "subtype";
type ViewMode = "tree" | "list";

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

function ThsBlockTreeItem({
  node,
  depth,
  expanded,
  rowById,
  selectedId,
  onToggle,
  onSelect,
}: {
  node: ThsTreeNode;
  depth: number;
  expanded: Set<string>;
  rowById: Map<string, ThsBlockRow>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (row: ThsBlockRow) => void;
}) {
  const isBranch = node.node_type === "branch";
  const isOpen = isBranch && expanded.has(node.id);
  const row = rowById.get(node.id);
  const active = selectedId === node.id;
  const stockCount = row?.stock_count;

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
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
          "hover:bg-muted/40",
          active && "bg-primary/10 ring-1 ring-primary/20",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
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
        {stockCount != null && (
          <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
            {stockCount}
          </span>
        )}
        <span className="hidden shrink-0 font-mono text-[10px] text-muted-foreground/70 sm:inline">
          {node.id}
        </span>
      </button>
      {isBranch && isOpen && (node.children ?? []).map((child) => (
        <ThsBlockTreeItem
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          rowById={rowById}
          selectedId={selectedId}
          onToggle={onToggle}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

export function ThsBlocks() {
  const [snapshot, setSnapshot] = useState<ThsBlocksSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshingKind, setRefreshingKind] = useState<string | null>(null);

  const [kindFilter, setKindFilter] = useState<string>("conception");
  const [q, setQ] = useState("");
  const [nodeFilter, setNodeFilter] = useState<"all" | "leaf" | "branch">("all");
  const [viewMode, setViewMode] = useState<ViewMode>("tree");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [sort, setSort] = useState<SortKey>("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");

  const [selected, setSelected] = useState<ThsBlockRow | null>(null);
  const [stocksDetail, setStocksDetail] = useState<ThsBlockStocksDetail | null>(null);
  const [stocksLoading, setStocksLoading] = useState(false);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});

  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.thsBlocksSnapshot();
      setSnapshot(data);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "加载板块缓存失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  const refreshAll = async () => {
    setRefreshing(true);
    const failed: string[] = [];
    let latest: ThsBlocksSnapshot | null = snapshot;

    for (const k of THS_BLOCK_KINDS) {
      setRefreshingKind(k.value);
      try {
        latest = await api.thsBlocksRefreshKind(k.value);
        setSnapshot(latest);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "刷新失败";
        failed.push(`${k.label}: ${msg}`);
      }
    }

    setRefreshingKind(null);
    setSelected(null);
    setStocksDetail(null);
    setQuotes({});

    const loaded = latest?.kinds ? Object.keys(latest.kinds).length : 0;
    if (latest?.linker_unavailable) {
      notify.error(latest.linker_message || "依赖于第三方工具，目前无法请求");
    } else if (failed.length) {
      notify.error(`部分类型刷新失败（${loaded}/${THS_BLOCK_KINDS.length} 成功）：${failed.join("；")}`);
    } else {
      notify.success(`板块已刷新 · ${latest?.updated_at || ""}`);
    }
    setRefreshing(false);
  };

  const refreshOneKind = async (kind: string) => {
    setRefreshing(true);
    setRefreshingKind(kind);
    try {
      const data = await api.thsBlocksRefreshKind(kind);
      setSnapshot(data);
      const label = thsBlockKindLabel(kind);
      const err = (data.errors || []).find((e) => e.startsWith(`${kind}:`));
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

  const kindEntry = snapshot?.kinds?.[kindFilter];
  const allRows = kindEntry?.rows || [];
  const showSubtypeCol = kindFilter === "custom";
  const canShowTree = kindEntry?.tree_mode === "tree" && !!kindEntry.tree;

  useEffect(() => {
    if (canShowTree) {
      setViewMode("tree");
    } else {
      setViewMode("list");
    }
  }, [kindFilter, canShowTree]);

  useEffect(() => {
    if (!canShowTree || !kindEntry?.tree) {
      setExpanded(new Set());
      return;
    }
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
  }, [kindFilter, canShowTree, kindEntry?.tree]);

  const rowById = useMemo(
    () => new Map(allRows.map((row) => [row.id, row])),
    [allRows],
  );

  const filteredTree = useMemo(() => {
    if (!canShowTree || !kindEntry?.tree) return null;
    const root = parseThsTree(kindEntry.tree);
    if (!root) return null;
    return filterThsTree(root, { query: q, nodeFilter });
  }, [canShowTree, kindEntry?.tree, q, nodeFilter]);

  const filteredRows = useMemo(() => {
    const query = q.trim().toLowerCase();
    let rows = allRows.filter((row) => {
      if (nodeFilter === "leaf" && row.node_type === "branch") return false;
      if (nodeFilter === "branch" && row.node_type !== "branch") return false;
      if (!query) return true;
      const subtype = thsCustomSubtypeLabel(row) || "";
      return (
        row.id.toLowerCase().includes(query)
        || row.name.toLowerCase().includes(query)
        || row.tree_path.toLowerCase().includes(query)
        || subtype.toLowerCase().includes(query)
        || (row.query_key || "").toLowerCase().includes(query)
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
      } else {
        av = String(a[sort] ?? "");
        bv = String(b[sort] ?? "");
      }
      const cmp = av.localeCompare(bv, "zh-CN");
      return order === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [allRows, q, nodeFilter, sort, order, viewMode, canShowTree]);

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
    if (!kindEntry?.tree) return;
    const root = parseThsTree(kindEntry.tree);
    if (!root) return;
    setExpanded(new Set(collectThsBranchIds(root)));
  };

  const collapseAllBranches = () => setExpanded(new Set());

  const openDetail = async (row: ThsBlockRow) => {
    setSelected(row);
    setStocksDetail(null);
    setQuotes({});
    if (row.node_type === "branch") return;
    setStocksLoading(true);
    try {
      const detail = await api.thsBlockStocks(row.kind, row.id);
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

  const emptyCache = !snapshot?.updated_at;
  const linkerDown = snapshot?.linker_unavailable;
  const linkerMessage = snapshot?.linker_message || "依赖于第三方工具，目前无法请求";
  const selectedSubtype = selected ? thsCustomSubtypeLabel(selected) : null;
  const visibleCount = filteredRows.length;

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <Boxes className="h-5 w-5 text-primary" />
              <h1 className="text-xl font-bold text-foreground">同花顺板块</h1>
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              概念 / 行业 / 地域层级树，以及自定义、每日动态板块；数据经 ths-linker 读取，成分股来自本地配置。
            </p>
          </div>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void refreshAll()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshingKind ? `刷新 ${thsBlockKindLabel(refreshingKind)}…` : "刷新板块"}
          </button>
        </div>

        {linkerDown && (
          <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-800 dark:text-amber-200">
            {linkerMessage}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {THS_BLOCK_KINDS.map((k) => {
            const loaded = snapshot?.kinds?.[k.value] != null;
            const hasErr = kindHasError(snapshot?.errors, k.value);
            const count = snapshot?.kinds?.[k.value]?.count;
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
                  kindFilter === k.value
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border bg-background text-muted-foreground hover:text-foreground",
                  hasErr && "border-amber-500/50",
                )}
              >
                {k.label}
                {count != null && (
                  <span className="ml-1.5 tabular-nums opacity-70">{count}</span>
                )}
                {!loaded && !emptyCache && (
                  <span className="ml-1 text-xs opacity-60">未加载</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {linkerDown ? (
            <span className="text-amber-700 dark:text-amber-300">{linkerMessage}</span>
          ) : emptyCache ? (
            <span className="text-amber-700 dark:text-amber-300">尚未刷新 — 请点击「刷新板块」从 ths-linker 拉取</span>
          ) : (
            <>
              <span>缓存 <strong className="text-foreground">{snapshot?.updated_at}</strong></span>
              {snapshot?.ths_dir && (
                <span className="max-w-xs truncate" title={snapshot.ths_dir}>{snapshot.ths_dir}</span>
              )}
            </>
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
          {kindEntry && (
            <button
              type="button"
              disabled={refreshing}
              onClick={() => void refreshOneKind(kindFilter)}
              className="text-primary hover:underline disabled:opacity-50"
            >
              仅刷新当前类型
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
                    placeholder="搜索 ID、名称、树路径…"
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
                {canShowTree && (
                  <div className="inline-flex rounded-lg border border-border p-0.5">
                    <button
                      type="button"
                      onClick={() => setViewMode("tree")}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors",
                        viewMode === "tree"
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:text-foreground",
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
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  共 <strong className="text-foreground">{visibleCount}</strong> 条
                  {kindEntry ? ` · ${kindEntry.kind_label}` : ""}
                  {viewMode === "tree" && canShowTree ? " · 树形浏览" : ""}
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
              ) : linkerDown ? (
                <div className="p-12 text-center text-sm text-amber-700 dark:text-amber-300">
                  {linkerMessage}
                </div>
              ) : emptyCache ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  点击右上角「刷新板块」加载同花顺板块数据
                </div>
              ) : !kindEntry ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  该类型尚未加载
                  {kindHasError(snapshot?.errors, kindFilter) && (
                    <p className="mt-2 text-amber-700 dark:text-amber-300">
                      {(snapshot?.errors || []).find((e) => e.startsWith(`${kindFilter}:`))?.slice(kindFilter.length + 2)}
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
                      selectedId={selected?.id ?? null}
                      onToggle={toggleExpanded}
                      onSelect={(row) => void openDetail(row)}
                    />
                  </div>
                ) : (
                  <p className="p-8 text-center text-sm text-muted-foreground">无匹配板块</p>
                )
              ) : (
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="sticky top-0 z-[1] bg-background/95 backdrop-blur">
                    <tr className="border-b border-border/60 text-left">
                      <SortTh col="id" label="ID" sortCol={sort} order={order} onSort={toggleSort} />
                      <SortTh col="name" label="名称" sortCol={sort} order={order} onSort={toggleSort} />
                      {showSubtypeCol && (
                        <SortTh col="subtype" label="子类型" sortCol={sort} order={order} onSort={toggleSort} />
                      )}
                      <SortTh col="node_type" label="节点" sortCol={sort} order={order} onSort={toggleSort} />
                      <SortTh col="tree_path" label="树路径" sortCol={sort} order={order} onSort={toggleSort} />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((row) => {
                      const active = selected?.kind === row.kind && selected?.id === row.id;
                      const subtype = thsCustomSubtypeLabel(row);
                      const depth = row.depth ?? 0;
                      return (
                        <tr
                          key={`${row.kind}-${row.id}`}
                          className={cn(
                            "cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/30",
                            active && "bg-primary/8",
                          )}
                          onClick={() => void openDetail(row)}
                        >
                          <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{row.id}</td>
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
                          {showSubtypeCol && (
                            <td className="px-4 py-2.5 text-muted-foreground">{subtype || "—"}</td>
                          )}
                          <td className="px-4 py-2.5 text-muted-foreground">
                            {THS_NODE_TYPE_LABEL[row.node_type] || row.node_type}
                          </td>
                          <td className="max-w-[280px] truncate px-4 py-2.5 text-muted-foreground" title={row.tree_path}>
                            {row.tree_path}
                          </td>
                        </tr>
                      );
                    })}
                    {!filteredRows.length && (
                      <tr>
                        <td colSpan={showSubtypeCol ? 5 : 4} className="px-4 py-10 text-center text-muted-foreground">
                          无匹配板块
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
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
                      <h2 className="text-lg font-semibold text-foreground">{selected.name || selected.id}</h2>
                      <span className={cn(
                        "rounded-md px-2 py-0.5 text-[11px] font-bold",
                        selected.node_type === "branch"
                          ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                          : "bg-primary/15 text-primary",
                      )}>
                        {THS_NODE_TYPE_LABEL[selected.node_type] || selected.node_type}
                      </span>
                    </div>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">{selected.id}</p>
                    {selected.tree_path && (
                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{selected.tree_path}</p>
                    )}
                  </div>

                  <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                      <dt className="text-muted-foreground">类型</dt>
                      <dd className="text-foreground">{thsBlockKindLabel(selected.kind)}</dd>
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

                  {selected.node_type === "branch" ? (
                    <p className="rounded-lg bg-muted/25 px-3 py-2 text-sm text-muted-foreground">
                      分组节点不含成分股，请展开并选择叶子板块。
                    </p>
                  ) : (
                    <DetailSection label="成分股">
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
