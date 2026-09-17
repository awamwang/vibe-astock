import { cn } from "@/lib/utils";
import { StockLabel } from "@/components/stock/StockLabel";
import { BlockLabel } from "@/components/block/BlockLabel";
import { useStockResolve } from "@/components/stock/StockResolveContext";
import { isStockMatched } from "@/lib/stocks";

function TagBadge({
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

/** 对齐消息分析：已映射个股用 StockLabel，未映射仍可右键尝试解析。 */
export function StockTargetTag({
  code,
  name,
}: {
  code?: string | null;
  name?: string | null;
}) {
  const stockQuery = { code: code || null, name: name || "" };
  const stockResolved = useStockResolve(stockQuery);
  const stockMatched = isStockMatched(stockResolved);
  if (stockMatched) {
    const stock = stockResolved!.stock!;
    return (
      <TagBadge
        className="border-sky-500/30 bg-sky-500/10 p-0 text-foreground"
        title={`个股 · 代码 ${stock.code}`}
      >
        <StockLabel
          code={stock.code}
          name={stock.name}
          resolved={stockResolved}
          variant="nameOnly"
          className="border-0 bg-transparent px-1.5 py-0.5"
        />
      </TagBadge>
    );
  }
  if (!name && !code) return null;
  return (
    <TagBadge
      className="border-primary/30 bg-primary/10 p-0 text-foreground"
      title={code ? `个股 · 代码 ${code}` : "个股"}
    >
      <StockLabel
        code={code || ""}
        name={name}
        resolved={stockResolved}
        variant="nameOnly"
        className="border-0 bg-transparent px-1.5 py-0.5"
      />
    </TagBadge>
  );
}

/** 对齐消息分析：板块用 BlockLabel，映射成功可右键打开详情。 */
export function BlockTargetTag({ name }: { name: string }) {
  const n = (name || "").trim();
  if (!n) return null;
  return (
    <TagBadge className="border-amber-500/30 bg-amber-500/10 p-0 text-foreground" title="板块">
      <BlockLabel name={n} variant="tag" className="border-0 bg-transparent" />
    </TagBadge>
  );
}

export function StockBlockTagRows({
  stocks,
  sectors,
  showEmpty = false,
}: {
  stocks?: { code?: string | null; name?: string | null }[];
  sectors?: { name?: string }[];
  showEmpty?: boolean;
}) {
  const stockItems = (stocks || []).filter((s) => s.name || s.code);
  const sectorItems = (sectors || []).filter((s) => (s.name || "").trim());
  if (!showEmpty && stockItems.length === 0 && sectorItems.length === 0) return null;
  return (
    <div className="mt-1.5 space-y-1">
      {(showEmpty || stockItems.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="shrink-0 text-[10px] font-medium text-muted-foreground">个股</span>
          {stockItems.length === 0 ? (
            <span className="text-[10px] text-muted-foreground/70">—</span>
          ) : (
            stockItems.map((s, i) => (
              <StockTargetTag key={`s-${s.code || s.name || i}`} code={s.code} name={s.name} />
            ))
          )}
        </div>
      )}
      {(showEmpty || sectorItems.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="shrink-0 text-[10px] font-medium text-muted-foreground">板块</span>
          {sectorItems.length === 0 ? (
            <span className="text-[10px] text-muted-foreground/70">—</span>
          ) : (
            sectorItems.map((s, i) => (
              <BlockTargetTag key={`b-${s.name || i}`} name={s.name || ""} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
