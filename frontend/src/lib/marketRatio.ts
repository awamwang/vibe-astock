import { finite } from "@/lib/agent";

/** 全市场股票只数：优先用后端 universe，否则用涨+跌+平家数之和。 */
export function marketTotal(
  universe?: number | null,
  up?: number | null,
  down?: number | null,
  flat?: number | null,
): number | null {
  const u = finite(universe);
  if (u != null && u > 0) return u;
  const a = finite(up), b = finite(down), c = finite(flat);
  if (a != null && b != null && c != null && a + b + c > 0) return a + b + c;
  return null;
}

function pctText(n: number, total: number): string {
  const v = (n / total) * 100;
  return `${v.toFixed(2)}%`;
}

function permilleText(n: number, total: number): string {
  const v = (n / total) * 1000;
  return `${v.toFixed(2)}‰`;
}

/** 个数后附百分占比，如 2845(52.34%) */
export function fmtCountPct(count: number | null | undefined, total: number | null): string {
  const n = finite(count);
  if (n == null) return "—";
  const base = String(Math.round(n));
  if (total == null || total <= 0) return base;
  return `${base}(${pctText(n, total)})`;
}

/** 个数后附千分占比，如 45(8.33‰) */
export function fmtCountPermille(count: number | null | undefined, total: number | null): string {
  const n = finite(count);
  if (n == null) return "—";
  const base = String(Math.round(n));
  if (total == null || total <= 0) return base;
  return `${base}(${permilleText(n, total)})`;
}
