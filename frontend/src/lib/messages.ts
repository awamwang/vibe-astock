export const IMPACT_LABEL: Record<string, string> = {
  critical: "重大",
  high: "高",
  medium: "中",
  low: "低",
  noise: "噪声",
};

/** 重要程度从高到低，用于日历日内排序 */
export const IMPACT_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  noise: 4,
};

/** 日历事件条背景色（按重要程度） */
export const IMPACT_EVENT_BG: Record<string, string> = {
  critical: "bg-danger/90 text-danger-foreground",
  high: "bg-primary/85 text-primary-foreground",
  medium: "bg-amber-500/75 text-amber-950 dark:text-amber-50",
  low: "bg-muted text-muted-foreground",
  noise: "bg-muted/50 text-muted-foreground/80",
};

export function impactSortKey(level: string): number {
  return IMPACT_ORDER[level] ?? IMPACT_ORDER.medium;
}

/** 回测口径：定时生效取 effective_at，立即生效取 produced_at */
export function effectiveAt(item: {
  effective_mode?: string;
  effective_at?: string | null;
  produced_at: string;
}): string {
  if (item.effective_mode === "scheduled" && item.effective_at) {
    return item.effective_at;
  }
  return item.produced_at;
}

export function dateKeyFromEffective(item: {
  effective_mode?: string;
  effective_at?: string | null;
  produced_at: string;
}): string {
  return effectiveAt(item).slice(0, 10);
}

export function monthRange(year: number, month: number): { from_dt: string; to_dt: string } {
  const m = String(month + 1).padStart(2, "0");
  const lastDay = new Date(year, month + 1, 0).getDate();
  const d = String(lastDay).padStart(2, "0");
  return {
    from_dt: `${year}-${m}-01 00:00:00`,
    to_dt: `${year}-${m}-${d} 23:59:59`,
  };
}

export const FRESHNESS_LABEL: Record<string, string> = {
  new: "全新",
  follow_up: "续报",
  duplicate: "重复",
  rumor: "传闻",
};

export const EFFECT_LABEL: Record<string, string> = {
  not_erupted: "未爆发",
  pending_verify: "待验证",
  ongoing_hype: "持续炒作",
  already_hyped: "已炒过",
  invalid: "证伪/过期",
  // 历史数据兼容
  early_hype: "刚开始炒",
  faded: "退潮",
};

/** 筛选与编辑可选的生效情况 */
export const EFFECT_STATUS_OPTIONS = [
  "not_erupted",
  "pending_verify",
  "ongoing_hype",
  "already_hyped",
  "invalid",
] as const;

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

/** 选股宝 keywords = SubjIds 主题分类 ID；财联社 = 题材名；其它来源为自定义关键词 */
export function keywordHint(sourceId: string): string {
  if (sourceId === "xgb_msgs") return "选股宝 SubjIds（主题/频道分类编号）";
  if (sourceId === "cls_telegraph") return "财联社题材标签";
  return "关键词";
}

export function formatMarkLabel(mark: string): string {
  if (mark.startsWith("impact:")) return `影响方向 ${mark.slice(7)}`;
  if (mark === "highlight") return "标红";
  if (mark === "withdrawn") return "已撤回";
  return mark;
}
