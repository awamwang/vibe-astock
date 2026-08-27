/** 同花顺板块类型与展示文案 */

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
