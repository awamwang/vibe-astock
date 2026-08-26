// 消息关注词 —— 存于本机后端配置（~/.duanxian-agents/config/message_follow_keywords.json）。
// 无内置默认词，用于消息分析页命中筛选。

let _cache: string[] = [];

function normalizeTag(raw: string): string {
  return raw.replace(/\s+/g, "").trim();
}

export function sanitizeMessageFollowKeywords(list: unknown): string[] {
  if (!Array.isArray(list)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    if (typeof item !== "string") continue;
    const t = normalizeTag(item);
    if (!t || t.length > 20 || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

export function loadMessageFollowKeywords(): string[] {
  return [..._cache];
}

export function setMessageFollowKeywordsCache(tags: string[]): string[] {
  _cache = sanitizeMessageFollowKeywords(tags);
  return [..._cache];
}

export function addMessageFollowKeyword(
  list: string[],
  raw: string,
): { next: string[]; ok: boolean; reason?: string } {
  const t = normalizeTag(raw);
  if (!t) return { next: list, ok: false, reason: "关注词不能为空" };
  if (t.length > 20) return { next: list, ok: false, reason: "关注词不超过 20 个字" };
  if (list.includes(t)) return { next: list, ok: false, reason: "已存在" };
  return { next: sanitizeMessageFollowKeywords([...list, t]), ok: true };
}

export function removeMessageFollowKeyword(
  list: string[],
  tag: string,
): { next: string[]; ok: boolean; reason?: string } {
  if (!list.includes(tag)) return { next: list, ok: false, reason: "不在列表中" };
  return { next: list.filter((x) => x !== tag), ok: true };
}
