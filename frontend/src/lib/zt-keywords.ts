// 上涨/涨停原因关键词标签 —— 只存本地 localStorage，不上传、不进仓库。
// 首板深入分析必须从该列表中选一个；「无原因」「其他」为兜底标签，不可删除。

const KEY = "vr-zt-keywords";

/** 内置默认标签（含兜底） */
export const DEFAULT_ZT_KEYWORDS: readonly string[] = [
  "并购", "重组", "涨价", "借壳", "业绩", "政策", "创新", "增持",
  "高送转", "次新", "国际局势", "自然", "订单", "无原因", "其他",
];

/** 语义兜底：无明确驱动 / 列表未覆盖，不允许从配置里删掉 */
export const LOCKED_ZT_KEYWORDS: readonly string[] = ["无原因", "其他"];

function normalizeTag(raw: string): string {
  return raw.replace(/\s+/g, "").trim();
}

function sanitizeList(list: unknown): string[] {
  if (!Array.isArray(list)) return [...DEFAULT_ZT_KEYWORDS];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    if (typeof item !== "string") continue;
    const t = normalizeTag(item);
    if (!t || t.length > 10 || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  // 兜底标签始终保留在末尾（若用户曾挪到中间则按已有顺序，缺则补上）
  for (const locked of LOCKED_ZT_KEYWORDS) {
    if (!seen.has(locked)) {
      out.push(locked);
      seen.add(locked);
    }
  }
  return out.length ? out : [...DEFAULT_ZT_KEYWORDS];
}

/** 读取当前上涨关键词列表；未配置或损坏时回落默认 */
export function loadZtKeywords(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [...DEFAULT_ZT_KEYWORDS];
    return sanitizeList(JSON.parse(raw));
  } catch {
    return [...DEFAULT_ZT_KEYWORDS];
  }
}

export function saveZtKeywords(tags: string[]): string[] {
  const next = sanitizeList(tags);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* 隐私模式等：本次会话仍可用，关掉页面后不保留 */
  }
  return next;
}

export function addZtKeyword(list: string[], raw: string): { next: string[]; ok: boolean; reason?: string } {
  const t = normalizeTag(raw);
  if (!t) return { next: list, ok: false, reason: "标签不能为空" };
  if (t.length > 10) return { next: list, ok: false, reason: "标签不超过 10 个字" };
  if (list.includes(t)) return { next: list, ok: false, reason: "已存在" };
  // 新标签插在兜底标签之前
  const head = list.filter((x) => !LOCKED_ZT_KEYWORDS.includes(x));
  const next = saveZtKeywords([...head, t, ...LOCKED_ZT_KEYWORDS]);
  return { next, ok: true };
}

export function removeZtKeyword(list: string[], tag: string): { next: string[]; ok: boolean; reason?: string } {
  if (LOCKED_ZT_KEYWORDS.includes(tag)) {
    return { next: list, ok: false, reason: `「${tag}」为兜底标签，不可删除` };
  }
  if (!list.includes(tag)) return { next: list, ok: false, reason: "不在列表中" };
  return { next: saveZtKeywords(list.filter((x) => x !== tag)), ok: true };
}

export function resetZtKeywords(): string[] {
  return saveZtKeywords([...DEFAULT_ZT_KEYWORDS]);
}

/**
 * 把模型抽出的原文归一到当前标签列表：精确匹配优先，否则取被包含的最长标签，
 * 再否则归到「其他」（列表里没有「其他」时原样截断返回）。
 */
export function resolveZtKeyword(raw: string | null | undefined, allowed?: string[]): string | null {
  if (raw == null) return null;
  const v = normalizeTag(raw);
  if (!v) return null;
  const list = allowed ?? loadZtKeywords();
  if (list.includes(v)) return v;
  let best: string | null = null;
  for (const tag of list) {
    if (LOCKED_ZT_KEYWORDS.includes(tag)) continue;
    if (v.includes(tag) && (!best || tag.length > best.length)) best = tag;
  }
  if (best) return best;
  if (list.includes("其他")) return "其他";
  return v.slice(0, 10);
}
