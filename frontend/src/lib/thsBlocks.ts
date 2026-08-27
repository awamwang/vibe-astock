/** 同花顺板块类型与展示文案 */

import type { ThsBlockRow, ThsTreeNode } from "@/lib/api";

export const THS_BLOCK_KINDS = [
  { value: "conception", label: "概念" },
  { value: "industry", label: "行业" },
  { value: "region", label: "地域" },
  { value: "custom", label: "自定义" },
  { value: "daily", label: "每日动态" },
] as const;

export type ThsBlockKind = (typeof THS_BLOCK_KINDS)[number]["value"];

export const THS_NODE_TYPE_LABEL: Record<string, string> = {
  branch: "分组",
  leaf: "板块",
  flat: "板块",
};

export function thsBlockKindLabel(kind: string): string {
  return THS_BLOCK_KINDS.find((k) => k.value === kind)?.label || kind;
}

export const THS_CUSTOM_TYPE_LABEL: Record<string, string> = {
  static: "静态",
  dynamic: "动态",
};

export const THS_DYNAMIC_KIND_LABEL: Record<string, string> = {
  broker: "营业部问财",
  concept: "概念联动",
  rule: "规则模板",
};

/** 自定义板块子类型展示，如「动态（营业部问财）」 */
export function thsCustomSubtypeLabel(row: {
  custom_type?: string;
  dynamic_kind?: string;
}): string | null {
  if (!row.custom_type) return null;
  const base = THS_CUSTOM_TYPE_LABEL[row.custom_type] || row.custom_type;
  if (row.custom_type === "dynamic" && row.dynamic_kind) {
    const sub = THS_DYNAMIC_KIND_LABEL[row.dynamic_kind] || row.dynamic_kind;
    return `${base}（${sub}）`;
  }
  return base;
}

export interface ThsTreeFilterOpts {
  query?: string;
  nodeFilter?: "all" | "leaf" | "branch";
}

function nodeMatchesFilter(
  node: { node_type: string },
  nodeFilter: "all" | "leaf" | "branch",
): boolean {
  if (nodeFilter === "all") return true;
  if (nodeFilter === "leaf") return node.node_type !== "branch";
  return node.node_type === "branch";
}

function nodeMatchesQuery(
  node: { id: string; name: string },
  query: string,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    node.id.toLowerCase().includes(q)
    || node.name.toLowerCase().includes(q)
  );
}

/** 按搜索与节点类型裁剪板块树，保留匹配节点的祖先链 */
export function filterThsTree(
  node: ThsTreeNode,
  opts: ThsTreeFilterOpts,
): ThsTreeNode | null {
  const nodeFilter = opts.nodeFilter ?? "all";
  const query = opts.query ?? "";
  const children = (node.children ?? [])
    .map((child) => filterThsTree(child, opts))
    .filter((c): c is ThsTreeNode => c != null);

  const selfMatch = nodeMatchesQuery(node, query) && nodeMatchesFilter(node, nodeFilter);
  const childMatch = children.length > 0;

  if (nodeFilter === "leaf" && node.node_type === "branch") {
    return childMatch ? { ...node, children } : null;
  }
  if (nodeFilter === "branch" && node.node_type !== "branch") {
    return null;
  }
  if (selfMatch || childMatch) {
    return { ...node, children: childMatch ? children : undefined };
  }
  return null;
}

/** 收集树中所有分组节点 id，用于默认展开 */
export function collectThsBranchIds(node: ThsTreeNode): string[] {
  const ids: string[] = [];
  if (node.node_type === "branch") {
    ids.push(node.id);
    for (const child of node.children ?? []) {
      ids.push(...collectThsBranchIds(child));
    }
  }
  return ids;
}

/** 将 API 返回的 tree 对象解析为 ThsTreeNode */
export function parseThsTree(raw: Record<string, unknown> | undefined): ThsTreeNode | null {
  if (!raw || typeof raw !== "object") return null;
  const id = String(raw.id ?? "");
  const name = String(raw.name ?? "").trim();
  const node_type: "branch" | "leaf" = raw.node_type === "branch" ? "branch" : "leaf";
  const childRaw = raw.children;
  const children = Array.isArray(childRaw)
    ? childRaw
      .filter((c): c is Record<string, unknown> => c != null && typeof c === "object")
      .map((c) => parseThsTree(c))
      .filter((c): c is ThsTreeNode => c != null)
    : [];
  return {
    id,
    name: name || id,
    node_type,
    children: children.length ? children : undefined,
  };
}

/** 按 tree_order 保持 DFS 顺序筛选表格行 */
export function sortRowsByTreeOrder(rows: ThsBlockRow[]): ThsBlockRow[] {
  return [...rows].sort((a, b) => {
    const ao = a.tree_order ?? Number.MAX_SAFE_INTEGER;
    const bo = b.tree_order ?? Number.MAX_SAFE_INTEGER;
    if (ao !== bo) return ao - bo;
    return a.name.localeCompare(b.name, "zh-CN");
  });
}
