import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Boxes, Loader2, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { StockLabel } from "@/components/stock/StockLabel";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SortTh } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type Quote, type ThsBlockRow, type ThsBlocksSnapshot, type ThsBlockStocksDetail,
} from "@/lib/api";
import { THS_BLOCK_KINDS, THS_NODE_TYPE_LABEL, thsBlockKindLabel } from "@/lib/thsBlocks";

const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const inputCls =
  "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground";

type SortKey = "id" | "name" | "node_type" | "tree_path";

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

export function ThsBlocks() {
  const [snapshot, setSnapshot] = useState<ThsBlocksSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [kindFilter, setKindFilter] = useState<string>("conception");
  const [q, setQ] = useState("");
  const [nodeFilter, setNodeFilter] = useState<"all" | "leaf" | "branch">("all");
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

  const refresh = async () => {
    setRefreshing(true);
    try {
      const data = await api.thsBlocksRefresh();
      setSnapshot(data);
      setSelected(null);
      setStocksDetail(null);
      setQuotes({});
      if (data.errors?.length) {
        notify.error(`部分类型刷新失败：${data.errors.join("；")}`);
      } else {
        notify.success(`板块已刷新 · ${data.updated_at || ""}`);
      }
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "刷新失败");
    } finally {
      setRefreshing(false);
    }
  };

  const kindEntry = snapshot?.kinds?.[kindFilter];
  const allRows = kindEntry?.rows || [];

  const filteredRows = useMemo(() => {
    const query = q.trim().toLowerCase();
    let rows = allRows.filter((row) => {
      if (nodeFilter === "leaf" && row.node_type === "branch") return false;
      if (nodeFilter === "branch" && row.node_type !== "branch") return false;
      if (!query) return true;
      return (
        row.id.toLowerCase().includes(query)
        || row.name.toLowerCase().includes(query)
        || row.tree_path.toLowerCase().includes(query)
      );
    });
    rows = [...rows].sort((a, b) => {
      const av = String(a[sort] ?? "");
      const bv = String(b[sort] ?? "");
      const cmp = av.localeCompare(bv, "zh-CN");
      return order === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [allRows, q, nodeFilter, sort, order]);

  const toggleSort = (key: SortKey) => {
    if (sort === key) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setOrder("asc");
    }
  };

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

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <Boxes className="h-5 w-5 text-primary" />
              <h1 className="text-xl font-bold text-foreground">同花顺板块</h1>
            </div>
            <p className="text-sm text-muted-foreground">
              概念 / 行业 / 地域层级树，以及自定义、每日动态板块；数据经 ths-linker 读取，成分股来自本地配置。
            </p>
          </div>
          <button
            type="button"
            disabled={refreshing}
            onClick={() => void refresh()}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新板块
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {THS_BLOCK_KINDS.map((k) => (
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
              )}
            >
              {k.label}
              {snapshot?.kinds?.[k.value]?.count != null && (
                <span className="ml-1.5 tabular-nums opacity-70">
                  {snapshot.kinds[k.value].count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {emptyCache ? (
            <span className="text-amber-700 dark:text-amber-300">尚未刷新 — 请点击「刷新板块」从 ths-linker 拉取</span>
          ) : (
            <>
              <span>缓存时间 <strong className="text-foreground">{snapshot?.updated_at}</strong></span>
              {snapshot?.ths_dir && (
                <span className="truncate" title={snapshot.ths_dir}>· {snapshot.ths_dir}</span>
              )}
            </>
          )}
          {kindEntry?.branch_count != null && (
            <span>· 树节点 {kindEntry.branch_count} · 叶子 {kindEntry.leaf_count}</span>
          )}
        </div>
      </section>

      <section className="w-full min-w-0">
        <div className="grid w-full min-w-0 gap-4 xl:grid-cols-3">
          <div className="glass min-w-0 overflow-hidden rounded-2xl xl:col-span-2">
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
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                共 <strong className="text-foreground">{filteredRows.length}</strong> 条
                {kindEntry ? ` · ${kindEntry.kind_label}` : ""}
              </p>
            </div>

            <div className="max-h-[calc(100vh-280px)] overflow-auto">
              {loading ? (
                <div className="flex items-center justify-center gap-2 p-12 text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" /> 加载中…
                </div>
              ) : emptyCache ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  点击右上角「刷新板块」加载同花顺板块数据
                </div>
              ) : !kindEntry ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
                  该类型刷新失败或未加载
                </div>
              ) : (
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="sticky top-0 z-[1] bg-background/95 backdrop-blur">
                    <tr className="border-b border-border/60 text-left">
                      <SortTh label="ID" active={sort === "id"} order={order} onClick={() => toggleSort("id")} />
                      <SortTh label="名称" active={sort === "name"} order={order} onClick={() => toggleSort("name")} />
                      <SortTh label="节点" active={sort === "node_type"} order={order} onClick={() => toggleSort("node_type")} />
                      <SortTh label="树路径" active={sort === "tree_path"} order={order} onClick={() => toggleSort("tree_path")} />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((row) => {
                      const active = selected?.kind === row.kind && selected?.id === row.id;
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
                          <td className="px-4 py-2.5 font-medium text-foreground">{row.name || "—"}</td>
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
                        <td colSpan={4} className="px-4 py-10 text-center text-muted-foreground">
                          无匹配板块
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="glass min-w-0 rounded-2xl xl:col-span-1">
            <div className="border-b border-border/60 px-4 py-3">
              <p className="text-xs font-bold uppercase tracking-wider text-primary">板块详情</p>
            </div>
            <div className="max-h-[calc(100vh-280px)] overflow-auto p-4">
              {!selected ? (
                <p className="text-sm text-muted-foreground">点击左侧表格行查看详情与成分股</p>
              ) : (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-lg font-semibold text-foreground">{selected.name || selected.id}</h2>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">{selected.id}</p>
                  </div>

                  <div className="glass rounded-xl bg-muted/20 p-4 text-sm">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                      <dt className="text-muted-foreground">类型</dt>
                      <dd className="text-foreground">{thsBlockKindLabel(selected.kind)}</dd>
                      <dt className="text-muted-foreground">节点</dt>
                      <dd className="text-foreground">{THS_NODE_TYPE_LABEL[selected.node_type] || selected.node_type}</dd>
                      <dt className="text-muted-foreground">路径</dt>
                      <dd className="text-foreground">{selected.tree_path || "—"}</dd>
                    </dl>
                  </div>

                  {selected.node_type === "branch" ? (
                    <p className="text-sm text-muted-foreground">分组节点不含成分股，请选择叶子板块。</p>
                  ) : (
                    <>
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
                              <div className="overflow-hidden rounded-xl border border-border/60">
                                <table className="w-full text-sm">
                                  <thead>
                                    <tr className="border-b border-border/60 bg-muted/20 text-left text-xs text-muted-foreground">
                                      <th className="px-3 py-2">代码</th>
                                      <th className="px-3 py-2">名称</th>
                                      <th className="px-3 py-2 text-right">涨跌幅</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {stocksDetail.stocks.map((s) => {
                                      const q = quotes[s.code];
                                      const pct = q?.change_pct;
                                      return (
                                        <tr key={s.code} className="border-b border-border/30">
                                          <td className="px-3 py-2">
                                            <StockLabel code={s.code} variant="codeOnly" />
                                          </td>
                                          <td className="px-3 py-2">
                                            <StockLabel
                                              code={s.code}
                                              name={q?.name}
                                              variant="nameOnly"
                                            />
                                          </td>
                                          <td className={cn(
                                            "px-3 py-2 text-right tabular-nums",
                                            pct == null ? "text-muted-foreground"
                                              : pct > 0 ? "text-danger" : pct < 0 ? "text-emerald-600 dark:text-emerald-400" : "text-foreground",
                                          )}>
                                            {pct != null ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "—"}
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </>
                        ) : (
                          <p className="text-sm text-muted-foreground">—</p>
                        )}
                      </DetailSection>
                    </>
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
