export const IMPACT_LABEL: Record<string, string> = {
  critical: "重大",
  high: "高",
  medium: "中",
  low: "低",
  noise: "噪声",
};

export const FRESHNESS_LABEL: Record<string, string> = {
  new: "全新",
  follow_up: "续报",
  duplicate: "重复",
  rumor: "传闻",
};

export const EFFECT_LABEL: Record<string, string> = {
  not_erupted: "未爆发",
  early_hype: "刚开始炒",
  ongoing_hype: "持续炒作",
  already_hyped: "已炒过",
  faded: "退潮",
  invalid: "证伪/过期",
};

export const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  confirmed: "已确认",
  archived: "归档",
};

export const TARGET_KIND_LABEL: Record<string, string> = {
  stock: "个股",
  sector: "板块",
  theme: "题材",
  market: "大盘",
  other: "其他",
};

export function targetTitle(t: { kind: string; name: string; code?: string | null }) {
  const prefix = TARGET_KIND_LABEL[t.kind];
  const label = t.name || t.code || t.kind;
  return prefix && t.kind !== "other" ? `${label}` : label;
}

export function targetHint(t: { kind: string; name: string; code?: string | null }) {
  const kind = TARGET_KIND_LABEL[t.kind] || t.kind;
  return t.code ? `${kind} · 代码 ${t.code}` : kind;
}

/** 选股宝 keywords = SubjIds 主题分类 ID；其它来源为自定义关键词 */
export function keywordHint(sourceId: string): string {
  if (sourceId === "xgb_msgs") return "选股宝 SubjIds（主题/频道分类编号）";
  return "关键词";
}

export function formatMarkLabel(mark: string): string {
  if (mark.startsWith("impact:")) return `影响方向 ${mark.slice(7)}`;
  if (mark === "highlight") return "标红";
  if (mark === "withdrawn") return "已撤回";
  return mark;
}
