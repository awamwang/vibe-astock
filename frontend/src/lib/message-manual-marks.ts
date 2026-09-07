// 自定义消息标记 —— 个股日记快捷标题。
// 存于本机后端配置（~/.duanxian-agents/config/message_manual_marks.json）。
// 无内置默认项，单条不超过 10 个字。

export const MESSAGE_MANUAL_MARK_MAX_LEN = 10;

let _cache: string[] = [];

function normalizeTag(raw: string): string {
  return raw.replace(/\s+/g, "").trim();
}

export function sanitizeMessageManualMarks(list: unknown): string[] {
  if (!Array.isArray(list)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    if (typeof item !== "string") continue;
    const t = normalizeTag(item);
    if (!t || t.length > MESSAGE_MANUAL_MARK_MAX_LEN || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
}

export function loadMessageManualMarks(): string[] {
  return [..._cache];
}

export function setMessageManualMarksCache(tags: string[]): string[] {
  _cache = sanitizeMessageManualMarks(tags);
  return [..._cache];
}

export function addMessageManualMark(
  list: string[],
  raw: string,
): { next: string[]; ok: boolean; reason?: string } {
  const t = normalizeTag(raw);
  if (!t) return { next: list, ok: false, reason: "标记不能为空" };
  if (t.length > MESSAGE_MANUAL_MARK_MAX_LEN) {
    return { next: list, ok: false, reason: `标记不超过 ${MESSAGE_MANUAL_MARK_MAX_LEN} 个字` };
  }
  if (list.includes(t)) return { next: list, ok: false, reason: "已存在" };
  return { next: sanitizeMessageManualMarks([...list, t]), ok: true };
}

export function removeMessageManualMark(
  list: string[],
  tag: string,
): { next: string[]; ok: boolean; reason?: string } {
  if (!list.includes(tag)) return { next: list, ok: false, reason: "不在列表中" };
  return { next: list.filter((x) => x !== tag), ok: true };
}
