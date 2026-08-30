// 消息关注板块 —— 存于本机后端配置（~/.duanxian-agents/config/message_follow_blocks.json）。
// 用于消息分析：目标板块命中时与关注词共用一次影响等级升档。

export interface FollowBlock {
  kind: string;
  id: string;
  name: string;
}

let _cache: FollowBlock[] = [];

function normalizeText(raw: string): string {
  return raw.replace(/\s+/g, "").trim();
}

export function sanitizeFollowBlocks(list: unknown): FollowBlock[] {
  if (!Array.isArray(list)) return [];
  const out: FollowBlock[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const raw = item as Record<string, unknown>;
    const kind = normalizeText(String(raw.kind || ""));
    const id = String(raw.id || "").trim();
    const name = normalizeText(String(raw.name || "")) || id;
    if (!kind || !id) continue;
    const key = `${kind}|${id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ kind, id, name });
  }
  return out;
}

export function loadFollowBlocks(): FollowBlock[] {
  return _cache.map((b) => ({ ...b }));
}

export function setFollowBlocksCache(blocks: FollowBlock[]): FollowBlock[] {
  _cache = sanitizeFollowBlocks(blocks);
  return loadFollowBlocks();
}

export function followBlockKey(kind: string, id: string): string {
  return `${normalizeText(kind)}|${String(id || "").trim()}`;
}

export function isBlockFollowed(kind: string, id: string, list?: FollowBlock[]): boolean {
  const items = list ?? _cache;
  const key = followBlockKey(kind, id);
  return items.some((b) => followBlockKey(b.kind, b.id) === key);
}
