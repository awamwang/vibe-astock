/** 侧栏菜单顺序（短线 / 设置分区各自独立，互不混排） */

const STORAGE_KEY = "va-sidebar-nav-order";

export type SidebarNavOrder = {
  review: string[];
  settings: string[];
};

export function loadSidebarNavOrder(): SidebarNavOrder | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SidebarNavOrder>;
    return {
      review: Array.isArray(parsed.review) ? parsed.review.map(String) : [],
      settings: Array.isArray(parsed.settings) ? parsed.settings.map(String) : [],
    };
  } catch {
    return null;
  }
}

export function saveSidebarNavOrder(order: SidebarNavOrder): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
}

export function clearSidebarNavOrder(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** 按已存路径重排；未知项丢弃，默认列表中的新项追加到末尾 */
export function applyNavOrder<T extends { to: string }>(items: T[], order: string[] | undefined | null): T[] {
  if (!order?.length) return items;
  const map = new Map(items.map((item) => [item.to, item]));
  const result: T[] = [];
  for (const to of order) {
    const hit = map.get(to);
    if (!hit) continue;
    result.push(hit);
    map.delete(to);
  }
  for (const item of items) {
    if (map.has(item.to)) result.push(item);
  }
  return result;
}

export function sameOrder(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((to, i) => to === b[i]);
}

export function moveNavItem(order: string[], fromTo: string, toTo: string): string[] {
  if (fromTo === toTo) return order;
  const next = [...order];
  const fromIdx = next.indexOf(fromTo);
  const toIdx = next.indexOf(toTo);
  if (fromIdx < 0 || toIdx < 0) return order;
  next.splice(fromIdx, 1);
  next.splice(toIdx, 0, fromTo);
  return next;
}
