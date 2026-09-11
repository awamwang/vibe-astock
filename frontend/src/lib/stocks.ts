import type { StockResolveItem } from "@/lib/api";

/** 仅接受已是 6 位的 A 股代码，避免板块短 ID（如 61）被补成 000061。 */
export function normStockCode(code?: string | null): string {
  let c = (code || "").trim();
  if (!c) return "";
  if (c.includes(".")) c = c.split(".", 1)[0].trim();
  return /^\d{6}$/.test(c) ? c : "";
}

export function normStockName(name?: string | null): string {
  return (name || "").replace(/\s+/g, "").trim();
}

/** 批量解析用的稳定键；有合法 code 时优先用 code */
export function stockQueryKey(t: { code?: string | null; name?: string | null }): string {
  const c = normStockCode(t.code);
  if (c) return `c:${c}`;
  const n = normStockName(t.name);
  return n ? `n:${n}` : "";
}

/** 股票映射成功时的标签样式 */
export function stockMatchedClass(matched?: boolean): string {
  return matched
    ? "border-sky-500/40 bg-sky-500/10 font-medium text-sky-800 ring-1 ring-sky-500/25 dark:text-sky-300"
    : "";
}

export function isStockMatched(item?: StockResolveItem | null): boolean {
  return item?.status === "matched" && !!item.stock;
}
