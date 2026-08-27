import { useMemo, useState } from "react";
import { StockLabel } from "@/components/stock/StockLabel";
import { SortTh, type SortOrder } from "@/components/ui/SortTh";
import { cn } from "@/lib/utils";
import type { Quote, ThsBlockStockItem } from "@/lib/api";

type SortKey = "change_pct";

interface Props {
  stocks: ThsBlockStockItem[];
  quotes: Record<string, Quote>;
}

/** 板块成分股表格，默认按涨跌幅倒序 */
export function BlockStocksTable({ stocks, quotes }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("change_pct");
  const [order, setOrder] = useState<SortOrder>("desc");

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setOrder((o) => (o === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setOrder("desc");
    }
  };

  const sorted = useMemo(() => {
    const mul = order === "asc" ? 1 : -1;
    return [...stocks].sort((a, b) => {
      const ap = quotes[a.code]?.change_pct;
      const bp = quotes[b.code]?.change_pct;
      if (ap == null && bp == null) return a.code.localeCompare(b.code);
      if (ap == null) return 1;
      if (bp == null) return -1;
      if (ap !== bp) return mul * (ap - bp);
      return a.code.localeCompare(b.code);
    });
  }, [stocks, quotes, order]);

  return (
    <div className="overflow-hidden rounded-xl border border-border/60">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 bg-muted/20 text-left text-xs text-muted-foreground">
            <th className="px-3 py-2">代码</th>
            <th className="px-3 py-2">名称</th>
            <SortTh
              col="change_pct"
              label="涨跌幅"
              sortCol={sortKey}
              order={order}
              onSort={toggleSort}
              className="px-3 py-2 text-right"
            />
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => {
            const qt = quotes[s.code];
            const pct = qt?.change_pct;
            return (
              <tr key={s.code} className="border-b border-border/30">
                <td className="px-3 py-2">
                  <StockLabel code={s.code} variant="codeOnly" />
                </td>
                <td className="px-3 py-2">
                  <StockLabel code={s.code} name={qt?.name} variant="nameOnly" />
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
  );
}
