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
