// 关注股票（自选股）—— 本地 localStorage 为主；服务端 ~/.vibe-research/watchlist.json
// 供插件钩子与多设备同步，经 /api/watchlist 读写。

const KEY = "vr-watchlist";
const META_KEY = "vr-watchlist-meta";
const UPDATED_KEY = "vr-watchlist-server-at";

export interface WatchItem {
  code: string;
  source: string;
  updated_at: string | null;
}

const SOURCE_MANUAL = "手动添加";

function normalizeItem(raw: Partial<WatchItem> | string): WatchItem | null {
  const code = typeof raw === "string" ? raw : String(raw.code || "").trim();
  if (!/^\d{6}$/.test(code)) return null;
  if (typeof raw === "string") {
    return { code, source: SOURCE_MANUAL, updated_at: null };
  }
  return {
    code,
    source: String(raw.source || SOURCE_MANUAL),
    updated_at: raw.updated_at ?? null,
  };
}

function loadMetaRaw(): WatchItem[] {
  try {
    const v = JSON.parse(localStorage.getItem(META_KEY) || "[]");
    if (!Array.isArray(v)) return [];
    return v.map((it) => normalizeItem(it)).filter((it): it is WatchItem => !!it);
  } catch {
    return [];
  }
}

function saveMeta(items: WatchItem[]) {
  try {
    localStorage.setItem(META_KEY, JSON.stringify(items));
    localStorage.setItem(KEY, JSON.stringify(items.map((it) => it.code)));
  } catch {
    /* 存储不可用 */
  }
}

export function loadWatchItems(): WatchItem[] {
  const meta = loadMetaRaw();
  if (meta.length > 0) return meta;
  return loadWatch().map((code) => ({ code, source: SOURCE_MANUAL, updated_at: null }));
}

export function loadWatch(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((c) => /^\d{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

export function saveWatchItems(items: WatchItem[]) {
  saveMeta(items);
}

export function saveWatch(codes: string[]) {
  const prev = new Map(loadWatchItems().map((it) => [it.code, it]));
  const items = codes
    .filter((c) => /^\d{6}$/.test(c))
    .map((code) => prev.get(code) ?? { code, source: SOURCE_MANUAL, updated_at: null });
  saveMeta(items);
}

// 从任意文本里抽取 6 位 A 股代码（逗号 / 空格 / 换行 / 顿号分隔都行，方便一次粘贴一串）。
export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

// 把用户输入的一串代码并入已有自选，返回去重后的新列表 + 实际新增数量。
export function addCodes(existing: WatchItem[], raw: string): { next: WatchItem[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.some((it) => it.code === c));
  const stamp = new Date().toLocaleString("zh-CN", { hour12: false }).slice(0, 16);
  const addedItems = incoming.map((code) => ({
    code,
    source: SOURCE_MANUAL,
    updated_at: stamp,
  }));
  return { next: [...existing, ...addedItems], added: incoming.length };
}

// 从自选中批量移除指定代码，返回剩余列表（不改动保留项的来源与时间）。
export function removeCodes(existing: WatchItem[], toRemove: string[]): WatchItem[] {
  if (toRemove.length === 0) return existing;
  const drop = new Set(toRemove);
  return existing.filter((it) => !drop.has(it.code));
}

function loadServerStamp(): string | null {
  try {
    return localStorage.getItem(UPDATED_KEY);
  } catch {
    return null;
  }
}

function saveServerStamp(stamp: string | null) {
  try {
    if (stamp) localStorage.setItem(UPDATED_KEY, stamp);
    else localStorage.removeItem(UPDATED_KEY);
  } catch {
    /* 存储不可用 */
  }
}

function pickItem(local: WatchItem, remote: WatchItem | undefined): WatchItem {
  if (!remote) return local;
  if (remote.source.startsWith("插件：") && !local.source.startsWith("插件：")) return remote;
  if (local.source.startsWith("插件：") && !remote.source.startsWith("插件：")) return local;
  if (remote.updated_at && (!local.updated_at || remote.updated_at >= local.updated_at)) return remote;
  return local;
}

function itemsEqual(a: WatchItem[], b: WatchItem[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((it, i) => {
    const other = b[i];
    return it.code === other.code && it.source === other.source && it.updated_at === other.updated_at;
  });
}

function remoteItemsOf(remote: { codes: string[]; items?: WatchItem[]; updated_at: string | null }): WatchItem[] {
  return (remote.items?.length ? remote.items : remote.codes.map((code) => ({
    code,
    source: SOURCE_MANUAL,
    updated_at: remote.updated_at,
  })))
    .map((it) => normalizeItem(it))
    .filter((it): it is WatchItem => !!it);
}

/** 首次进入页面时合并服务端元数据（来源 / 导入时间）。 */
export async function hydrateFromServer(
  fetcher: () => Promise<{ codes: string[]; items?: WatchItem[]; updated_at: string | null }>,
): Promise<WatchItem[] | null> {
  try {
    const remote = await fetcher();
    const remoteItems = remoteItemsOf(remote);
    if (!remoteItems.length) return null;

    const local = loadWatchItems();
    const remoteByCode = new Map(remoteItems.map((it) => [it.code, it]));
    const merged: WatchItem[] = [];
    const seen = new Set<string>();

    for (const it of local) {
      merged.push(pickItem(it, remoteByCode.get(it.code)));
      seen.add(it.code);
    }
    for (const it of remoteItems) {
      if (!seen.has(it.code)) {
        merged.push(it);
        seen.add(it.code);
      }
    }

    if (itemsEqual(merged, local)) return null;
    saveWatchItems(merged);
    if (remote.updated_at) saveServerStamp(remote.updated_at);
    return merged;
  } catch {
    return null;
  }
}

/** 拉取服务端自选股；有 updated_at 且比本地新时返回 items，否则 null。 */
export async function pullServerWatch(
  fetcher: () => Promise<{ codes: string[]; items?: WatchItem[]; updated_at: string | null }>,
): Promise<WatchItem[] | null> {
  try {
    const remote = await fetcher();
    if (!remote.updated_at) return null;
    if (remote.updated_at === loadServerStamp()) return null;
    const items = remoteItemsOf(remote);
    saveWatchItems(items);
    saveServerStamp(remote.updated_at);
    return items;
  } catch {
    return null;
  }
}

/** 把当前列表同步到服务端（失败静默），并以服务端返回的元数据回写本地。 */
export async function pushServerWatch(
  items: WatchItem[],
  saver: (codes: string[]) => Promise<{ codes: string[]; items?: WatchItem[]; updated_at: string | null }>,
): Promise<WatchItem[] | null> {
  try {
    const out = await saver(items.map((it) => it.code));
    saveServerStamp(out.updated_at);
    const synced = remoteItemsOf(out);
    if (synced.length) {
      saveWatchItems(synced);
      return synced;
    }
    return null;
  } catch {
    /* 同步失败不阻断本地操作 */
    return null;
  }
}
