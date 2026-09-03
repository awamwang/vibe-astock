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

/** 日历「待验证」事件条背景色 */
export const PENDING_VERIFY_EVENT_BG =
  "bg-violet-300/75 text-violet-950 dark:bg-violet-400/40 dark:text-violet-100";

export function impactSortKey(level: string): number {
  return IMPACT_ORDER[level] ?? IMPACT_ORDER.medium;
}

/** 日历日内优先档：收藏、待验证高于其他 */
export function calendarDayPriority(item: {
  favorited?: boolean;
  effect_status?: string;
}): number {
  if (item.favorited || item.effect_status === "pending_verify") return 0;
  return 1;
}

/** 日历同一天内排序：优先档 → 重要程度 → 生效时间新到旧 */
export function compareCalendarDayItems(
  a: {
    favorited?: boolean;
    effect_status?: string;
    impact_level: string;
    effective_mode?: string;
    effective_at?: string | null;
    produced_at: string;
  },
  b: {
    favorited?: boolean;
    effect_status?: string;
    impact_level: string;
    effective_mode?: string;
    effective_at?: string | null;
    produced_at: string;
  },
): number {
  const pa = calendarDayPriority(a);
  const pb = calendarDayPriority(b);
  if (pa !== pb) return pa - pb;
  const ia = impactSortKey(a.impact_level);
  const ib = impactSortKey(b.impact_level);
  if (ia !== ib) return ia - ib;
  return effectiveAt(b).localeCompare(effectiveAt(a));
}

export const DEFAULT_END_DAYS = 5;
const DEFAULT_END_DAYS_KEY = "va-message-default-end-days";

/** 消息默认有效期（天），仅用于未设 end_at 时的计算，不写入消息记录 */
export function getDefaultEndDays(): number {
  try {
    const raw = localStorage.getItem(DEFAULT_END_DAYS_KEY);
    if (raw == null) return DEFAULT_END_DAYS;
    const n = Number.parseInt(raw, 10);
    if (Number.isFinite(n) && n >= 1 && n <= 15) return n;
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
  return DEFAULT_END_DAYS;
}

/** 写入本地缓存（正式落盘走后端配置 API） */
export function setDefaultEndDays(days: number): void {
  const n = Math.min(15, Math.max(1, Math.round(days)));
  try {
    localStorage.setItem(DEFAULT_END_DAYS_KEY, String(n));
  } catch {
    /* 忽略 */
  }
}

/** 清洗为 1–15 的有效天数 */
export function clampDefaultEndDays(days: number): number {
  if (!Number.isFinite(days)) return DEFAULT_END_DAYS;
  return Math.min(15, Math.max(1, Math.round(days)));
}

/** 将存储时间字符串加上指定天数 */
export function addDaysToStorageDatetime(dt: string, days: number): string {
  const m = dt.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!m) return dt;
  const d = new Date(
    Number(m[1]),
    Number(m[2]) - 1,
    Number(m[3]),
    Number(m[4]),
    Number(m[5]),
    Number(m[6] ?? "0"),
  );
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
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

/** 结束时间：有 end_at 取 end_at，否则生效时间 + defaultDays */
export function endAt(
  item: {
    effective_mode?: string;
    effective_at?: string | null;
    produced_at: string;
    end_at?: string | null;
  },
  defaultDays?: number,
): string {
  if (item.end_at?.trim()) return item.end_at.trim();
  const days = defaultDays ?? getDefaultEndDays();
  return addDaysToStorageDatetime(effectiveAt(item), days);
}

export function hasExplicitEndAt(item: { end_at?: string | null }): boolean {
  return Boolean(item.end_at?.trim());
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
  if (mark === "must_watch") return "必看大事";
  if (mark === "key_data") return "关键数据";
  if (mark === "industry_exhibition") return "行业会展";
  if (mark === "flame") return "火焰";
  if (mark.startsWith("level:")) return `财联社 ${mark.slice(6).toUpperCase()} 级`;
  return mark;
}

/** 消息列表「标记」筛选选项 */
export const MARK_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: "highlight", label: "标红" },
  { value: "must_watch", label: "必看大事" },
  { value: "key_data", label: "关键数据" },
  { value: "industry_exhibition", label: "行业会展" },
  { value: "flame", label: "火焰" },
  { value: "level:a", label: "财联社 A 级" },
  { value: "level:b", label: "财联社 B 级" },
  { value: "level:c", label: "财联社 C 级" },
  { value: "withdrawn", label: "已撤回" },
];

/** 将消息结构化信息打包为「问 AI」上下文 */
export function buildMessageAiContext(
  msg: {
    title: string;
    source_label: string;
    source_id: string;
    status: string;
    url?: string;
    keywords: string[];
    marks: string[];
    summary: string;
    detail: string;
    produced_at: string;
    effective_mode?: string;
    effective_at?: string | null;
    end_at?: string | null;
    impact_level: string;
    initial_impact_level?: string;
    impact_manual?: boolean;
    freshness: string;
    effect_status: string;
    targets: { kind: string; name: string; code?: string | null }[];
    favorited?: boolean;
    followed?: boolean;
    matched_follow_keywords?: string[];
    matched_follow_blocks?: string[];
    matched_current_stock_blocks?: string[];
  },
  opts?: {
    defaultEndDays?: number;
    rawMessages?: { source_label: string; title: string; content: string; produced_at: string }[];
  },
): string {
  const lines: string[] = [];
  const endDays = opts?.defaultEndDays ?? getDefaultEndDays();

  lines.push("【消息分析】");
  lines.push(`标题：${msg.title || "—"}`);
  lines.push(`来源：${msg.source_label}（${msg.source_id}）· 状态：${STATUS_LABEL[msg.status] || msg.status}`);
  if (msg.url) lines.push(`链接：${msg.url}`);

  lines.push("");
  lines.push("【分级标注】");
  lines.push(`级别：${IMPACT_LABEL[msg.impact_level] || msg.impact_level}${msg.impact_manual ? "（手动指定）" : ""}`);
  if (msg.initial_impact_level && msg.initial_impact_level !== msg.impact_level) {
    lines.push(`初始级别：${IMPACT_LABEL[msg.initial_impact_level] || msg.initial_impact_level}`);
  }
  lines.push(`新旧：${FRESHNESS_LABEL[msg.freshness] || msg.freshness}`);
  lines.push(`炒作阶段：${EFFECT_LABEL[msg.effect_status] || msg.effect_status}`);
  if (msg.favorited) lines.push("已收藏");
  if (msg.followed) {
    const parts: string[] = [];
    if (msg.matched_follow_keywords?.length) parts.push(`关键词 ${msg.matched_follow_keywords.join("、")}`);
    if (msg.matched_follow_blocks?.length) parts.push(`板块 ${msg.matched_follow_blocks.join("、")}`);
    lines.push(`关注命中：${parts.length ? parts.join("；") : "是"}`);
  }

  lines.push("");
  lines.push("【时间】");
  lines.push(`产生：${msg.produced_at}`);
  lines.push(
    `生效：${msg.effective_mode === "scheduled" && msg.effective_at ? msg.effective_at : "立即（回测按产生时间）"}`,
  );
  lines.push(
    `结束：${hasExplicitEndAt(msg) ? msg.end_at : `${endAt(msg, endDays)}（默认 ${endDays} 天）`}`,
  );

  if (msg.keywords.length) lines.push(`\n【关键词】${msg.keywords.join("、")}`);
  if (msg.marks.length) lines.push(`【标记】${msg.marks.map(formatMarkLabel).join("、")}`);

  if (msg.targets.length) {
    lines.push("\n【影响标的】");
    for (const t of msg.targets) {
      const kind = TARGET_KIND_LABEL[t.kind] || t.kind;
      lines.push(`- ${kind}：${t.name}${t.code ? `（${t.code}）` : ""}`);
    }
  }
  if (msg.matched_current_stock_blocks?.length) {
    lines.push(`焦点股关联板块：${msg.matched_current_stock_blocks.join("、")}`);
  }

  if (msg.summary) lines.push(`\n【摘要】\n${msg.summary}`);
  if (msg.detail) lines.push(`\n【详情】\n${msg.detail}`);

  const raw = opts?.rawMessages;
  if (raw?.length) {
    lines.push(`\n【原始消息 ${raw.length} 条】`);
    for (const r of raw.slice(0, 5)) {
      lines.push(`--- ${r.source_label} · ${r.produced_at}`);
      if (r.title) lines.push(`标题：${r.title}`);
      const content = r.content.trim();
      lines.push(content.length > 800 ? `${content.slice(0, 800)}…` : content);
    }
    if (raw.length > 5) lines.push(`（另有 ${raw.length - 5} 条未展示）`);
  }

  return lines.join("\n");
}
