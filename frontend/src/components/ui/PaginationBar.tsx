import { useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";

export const LIST_PAGE_SIZE = 100;

export function buildPageItems(current: number, total: number, radius = 2): Array<number | "gap"> {
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

export function usePagedList<T>(
  items: T[],
  page: number,
  setPage: (page: number) => void,
  resetKey: unknown,
  pageSize = LIST_PAGE_SIZE,
) {
  useEffect(() => {
    setPage(1);
  }, [resetKey, setPage]);

  const total = items.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages);

  useEffect(() => {
    if (page !== safePage) setPage(safePage);
  }, [page, safePage, setPage]);

  const paged = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [items, safePage, pageSize]);

  return { page: safePage, paged, total, totalPages, pageSize };
}

interface PaginationBarProps {
  page: number;
  total: number;
  pageSize?: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
  className?: string;
}

export function PaginationBar({
  page,
  total,
  pageSize = LIST_PAGE_SIZE,
  onPageChange,
  disabled,
  className,
}: PaginationBarProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const pageItems = useMemo(() => buildPageItems(page, totalPages), [page, totalPages]);
  if (total <= pageSize) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3",
        className,
      )}
    >
      <span className="text-xs text-muted-foreground">
        第 {page} / {totalPages} 页 · 每页 {pageSize} 条
      </span>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={page <= 1 || disabled}
          className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-40"
          onClick={() => onPageChange(Math.max(1, page - 1))}
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
              disabled={disabled || item === page}
              aria-current={item === page ? "page" : undefined}
              className={cn(
                "min-w-8 rounded-lg border px-2.5 py-1.5 text-xs font-semibold tabular-nums transition-colors disabled:opacity-100",
                item === page
                  ? "border-primary/40 bg-primary/15 text-primary"
                  : "border-border bg-background text-foreground hover:bg-muted/50 disabled:opacity-40",
              )}
              onClick={() => onPageChange(item)}
            >
              {item}
            </button>
          ),
        )}
        <button
          type="button"
          disabled={page >= totalPages || disabled}
          className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:bg-muted/50 disabled:opacity-40"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
        >
          下一页
        </button>
      </div>
    </div>
  );
}
