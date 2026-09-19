/** 同花顺板块类型与展示文案 */

import type { ThsBlockRow, ThsTreeNode, BlockResolveItem, ThemeAliasEntry } from "@/lib/api";

export const THS_BLOCK_KINDS = [
  { value: "conception", label: "概念" },
  { value: "industry", label: "行业" },
  { value: "region", label: "地域" },
  { value: "custom", label: "自定义" },
  { value: "daily", label: "每日动态" },
  { value: "theme", label: "热点主题" },
] as const;

/** 板块管理：跨源融合类型（概念/行业/地域）+ 单源类型 */
export const BLOCK_MANAGE_KINDS = [
  { value: "conception", label: "概念", thsKind: "conception" as const, kplKind: "concept" as const, fused: true as const },
  { value: "industry", label: "行业", thsKind: "industry" as const, kplKind: "industry" as const, fused: true as const },
  { value: "region", label: "地域", thsKind: "region" as const, kplKind: "region" as const, fused: true as const },
  { value: "custom", label: "自定义", thsKind: "custom" as const, fused: false as const },
  { value: "daily", label: "每日动态", thsKind: "daily" as const, fused: false as const },
  { value: "theme", label: "热点主题", thsKind: "theme" as const, fused: false as const },
  { value: "hot", label: "人气", kplKind: "hot" as const, fused: false as const },
  { value: "style", label: "风格指数", catalog: "style" as const, fused: false as const },
] as const;

export type ThsBlockKind = (typeof THS_BLOCK_KINDS)[number]["value"];

export const THS_NODE_TYPE_LABEL: Record<string, string> = {
  branch: "分组",
  leaf: "板块",
  flat: "板块",
};

export function thsBlockKindLabel(kind: string): string {
  const manage = BLOCK_MANAGE_KINDS.find((k) => k.value === kind);
  if (manage) return manage.label;
  return THS_BLOCK_KINDS.find((k) => k.value === kind)?.label || kind;
}

/** 板块管理页签 → 同花顺树/成分股用的原生 kind */
export function manageTabThsKind(tab: string): string | null {
  const hit = BLOCK_MANAGE_KINDS.find((k) => k.value === tab);
  return hit && "thsKind" in hit ? hit.thsKind : null;
}

export function manageTabKplKind(tab: string): string | null {
  const hit = BLOCK_MANAGE_KINDS.find((k) => k.value === tab);
  return hit && "kplKind" in hit ? hit.kplKind : null;
}

/** 页签是否含同花顺树结构（融合页签以同花顺树为主） */
export function manageTabHasThsTree(tab: string): boolean {
  return manageTabThsKind(tab) != null && tab !== "hot";
}

/** @deprecated 融合后页签不再按来源前缀区分 */
export function manageTabOrigin(tab: string): "ths" | "kpl" | "fused" | "style" | null {
  const hit = BLOCK_MANAGE_KINDS.find((k) => k.value === tab);
  if (!hit) return null;
  if ("catalog" in hit) return "style";
  if (hit.fused) return "fused";
  if ("thsKind" in hit && !("kplKind" in hit)) return "ths";
  if ("kplKind" in hit && !("thsKind" in hit)) return "kpl";
  return "fused";
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

/** 与题材别名配置一致：去空白后匹配 */
export function normalizeThemeTag(raw: string): string {
  return String(raw || "").replace(/\s+/g, "").replace(/\u3000/g, "").trim();
}

/** 按标准板块名聚合别名列表（canonical → aliases） */
export function buildAliasesByCanonical(entries: ThemeAliasEntry[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const e of entries) {
    const c = normalizeThemeTag(e.canonical);
    const a = normalizeThemeTag(e.alias);
    if (!c || !a || a === c) continue;
    const list = map.get(c) || [];
    if (!list.includes(a)) list.push(a);
    map.set(c, list);
  }
  for (const [k, list] of map) {
    list.sort((a, b) => a.localeCompare(b, "zh-CN"));
    map.set(k, list);
  }
  return map;
}

export function aliasesForBlockName(
  name: string,
  byCanonical: Map<string, string[]>,
): string[] {
  if (!byCanonical.size) return [];
  return byCanonical.get(normalizeThemeTag(name)) || [];
}

export function themeAliasEntriesFromConfig(cfg: {
  entries?: ThemeAliasEntry[];
  aliases?: Record<string, string>;
  types?: Record<string, string>;
}): ThemeAliasEntry[] {
  if (cfg.entries?.length) {
    return cfg.entries.map((e) => ({
      alias: e.alias,
      canonical: e.canonical,
      type: (e.type ?? "").trim(),
    }));
  }
  const types = cfg.types || {};
  return Object.entries(cfg.aliases || {}).map(([alias, canonical]) => ({
    alias,
    canonical,
    type: types[alias] ?? "",
  }));
}

export interface ThsTreeFilterOpts {
  query?: string;
  nodeFilter?: "all" | "leaf" | "branch";
  /** 本地 id → 行情代码，用于树搜索匹配 code */
  codeById?: Map<string, string>;
  /** 标准板块名 → 别名，用于树搜索匹配别名 */
  aliasesByName?: Map<string, string[]>;
  /** 若提供，仅保留 id 在集合内的节点（及其祖先链） */
  allowedIds?: Set<string>;
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
  codeById?: Map<string, string>,
  aliasesByName?: Map<string, string[]>,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const code = (codeById?.get(node.id) || "").toLowerCase();
  if (
    node.id.toLowerCase().includes(q)
    || node.name.toLowerCase().includes(q)
    || (!!code && code.includes(q))
  ) {
    return true;
  }
  const aliases = aliasesByName?.size
    ? aliasesForBlockName(node.name, aliasesByName)
    : [];
  return aliases.some((a) => a.toLowerCase().includes(q));
}

function nodeMatchesAllowed(
  node: { id: string },
  allowedIds?: Set<string>,
): boolean {
  if (!allowedIds) return true;
  return allowedIds.has(node.id);
}

/** 按搜索与节点类型裁剪板块树，保留匹配节点的祖先链 */
export function filterThsTree(
  node: ThsTreeNode,
  opts: ThsTreeFilterOpts,
): ThsTreeNode | null {
  const nodeFilter = opts.nodeFilter ?? "all";
  const query = opts.query ?? "";
  const codeById = opts.codeById;
  const aliasesByName = opts.aliasesByName;
  const allowedIds = opts.allowedIds;
  const children = (node.children ?? [])
    .map((child) => filterThsTree(child, opts))
    .filter((c): c is ThsTreeNode => c != null);

  const selfMatch =
    nodeMatchesQuery(node, query, codeById, aliasesByName)
    && nodeMatchesFilter(node, nodeFilter)
    && nodeMatchesAllowed(node, allowedIds);
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

/** 同花顺自定义板块颜色：合法 ``#RRGGBB`` 才返回大写值 */
export function normalizeThsBlockColor(value?: string | null): string | undefined {
  const text = String(value || "").trim();
  if (!/^#[0-9A-Fa-f]{6}$/.test(text)) return undefined;
  return `#${text.slice(1).toUpperCase()}`;
}

/** 板块名称文字色；未着色则不覆盖主题色 */
export function thsBlockNameColorStyle(
  color?: string | null,
): { color: string } | undefined {
  const hex = normalizeThsBlockColor(color);
  return hex ? { color: hex } : undefined;
}

/** 按 tree_order 保持 DFS 顺序筛选表格行 */
export function sortRowsByTreeOrder<T extends ThsBlockRow>(rows: T[]): T[] {
  return [...rows].sort((a, b) => {
    const ao = a.tree_order ?? Number.MAX_SAFE_INTEGER;
    const bo = b.tree_order ?? Number.MAX_SAFE_INTEGER;
    if (ao !== bo) return ao - bo;
    return a.name.localeCompare(b.name, "zh-CN");
  });
}

/** 自定义板块：已着色按 color_order 靠前，其余保持原相对顺序 */
export function sortRowsByColorOrder<T extends ThsBlockRow>(
  rows: T[],
  order: "asc" | "desc" = "asc",
): T[] {
  const colored: T[] = [];
  const rest: T[] = [];
  for (const row of rows) {
    if (normalizeThsBlockColor(row.color)) colored.push(row);
    else rest.push(row);
  }
  colored.sort((a, b) => {
    const ao = a.color_order ?? Number.MAX_SAFE_INTEGER;
    const bo = b.color_order ?? Number.MAX_SAFE_INTEGER;
    if (ao !== bo) return ao - bo;
    return (a.name || "").localeCompare(b.name || "", "zh-CN");
  });
  if (order === "desc") colored.reverse();
  return [...colored, ...rest];
}

/** 树节点 / 行展示用 ID：同花顺 id 优先，否则开盘啦合成 */
export function blockTreeNodeId(row: {
  id?: string;
  kpl_code?: string;
  name?: string;
  style_key?: string;
}): string {
  if (row.style_key) return `style:${row.style_key}`;
  if (row.id) return row.id;
  if (row.kpl_code) return `kpl:${row.kpl_code}`;
  return `name:${row.name || ""}`;
}

/** 收集树中全部节点 id */
export function collectThsNodeIds(node: ThsTreeNode | null | undefined): Set<string> {
  const ids = new Set<string>();
  const walk = (n: ThsTreeNode) => {
    ids.add(n.id);
    for (const c of n.children ?? []) walk(c);
  };
  if (node) walk(node);
  return ids;
}

/** 无树结构时：把板块挂到类型根节点下，便于树形浏览 */
export function buildSyntheticBlockTree(
  rows: Array<{ id?: string; kpl_code?: string; name?: string; node_type?: string }>,
  rootLabel: string,
  rootId = "__synthetic_root__",
): ThsTreeNode {
  const children: ThsTreeNode[] = rows
    .filter((r) => r.node_type !== "branch")
    .map((r) => ({
      id: blockTreeNodeId(r),
      name: r.name || blockTreeNodeId(r),
      node_type: "leaf" as const,
    }));
  return {
    id: rootId,
    name: rootLabel,
    node_type: "branch",
    children,
  };
}

/** 按 parent_id 还原分组树（风格指数等合成层级） */
export function buildParentLinkedTree(
  rows: Array<{
    id?: string;
    kpl_code?: string;
    name?: string;
    node_type?: string;
    parent_id?: string | null;
    style_key?: string;
  }>,
  rootLabel: string,
  rootId: string,
): ThsTreeNode {
  type Linked = ThsTreeNode & { parentId?: string | null };
  const byId = new Map<string, Linked>();
  const order: string[] = [];
  for (const r of rows) {
    const id = blockTreeNodeId(r);
    if (!id || byId.has(id)) continue;
    byId.set(id, {
      id,
      name: r.name || id,
      node_type: r.node_type === "branch" ? "branch" : "leaf",
      children: [],
      parentId: r.parent_id || null,
    });
    order.push(id);
  }
  const roots: ThsTreeNode[] = [];
  for (const id of order) {
    const node = byId.get(id);
    if (!node) continue;
    const pid = node.parentId;
    const parent = pid ? byId.get(pid) : undefined;
    if (parent) {
      parent.node_type = "branch";
      parent.children = parent.children || [];
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  const strip = (n: ThsTreeNode): ThsTreeNode => ({
    id: n.id,
    name: n.name,
    node_type: n.node_type,
    children: n.children?.length ? n.children.map(strip) : undefined,
  });
  return {
    id: rootId,
    name: rootLabel,
    node_type: "branch",
    children: roots.map(strip),
  };
}

/** 把未入树的叶子挂到根节点下（开盘啦独有等） */
export function attachOrphanLeavesToTree(
  tree: ThsTreeNode,
  orphans: Array<{ id?: string; kpl_code?: string; name?: string; node_type?: string }>,
): ThsTreeNode {
  if (!orphans.length) return tree;
  const existing = collectThsNodeIds(tree);
  const extra: ThsTreeNode[] = [];
  for (const r of orphans) {
    if (r.node_type === "branch") continue;
    const id = blockTreeNodeId(r);
    if (!id || existing.has(id)) continue;
    existing.add(id);
    extra.push({ id, name: r.name || id, node_type: "leaf" });
  }
  if (!extra.length) return tree;
  return {
    ...tree,
    children: [...(tree.children ?? []), ...extra],
  };
}

/** 板块映射成功时的标签样式 */
export function blockMatchedClass(matched?: boolean): string {
  return matched
    ? "border-blue-500/40 bg-blue-500/10 font-medium text-blue-800 ring-1 ring-blue-500/25 dark:text-blue-300"
    : "";
}

export function isBlockMatched(item?: BlockResolveItem | null): boolean {
  return item?.status === "matched" && !!item.block;
}

/** 展示用主代码：行情 code 优先于本地 id */
export function thsBlockPrimaryCode(row: { id: string; code?: string | null }): string {
  const code = (row.code || "").trim();
  return code || row.id;
}

/** 详情副标题：有行情代码时突出 code，本地 id 次要 */
export function thsBlockCodeSubtitle(row: {
  id: string;
  code?: string | null;
}): { primary: string; secondary?: string } {
  const code = (row.code || "").trim();
  if (code) return { primary: code, secondary: row.id };
  return { primary: row.id };
}
