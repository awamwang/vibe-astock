// 关注股票（自选股）—— 本地 localStorage 为主；服务端 ~/.vibe-research/watchlist.json
// 供插件钩子与多设备同步，经 /api/watchlist 读写。

const KEY = "vr-watchlist";
const UPDATED_KEY = "vr-watchlist-server-at";

export function loadWatch(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((c) => /^\d{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

export function saveWatch(codes: string[]) {
  // localStorage 在隐私模式 / 嵌入式浏览器 / 配额写满时会抛异常。
  // 存不下就算了——自选丢失总好过整页崩掉（读取侧同样是 try/catch 兜底）。
  try {
    localStorage.setItem(KEY, JSON.stringify(codes));
  } catch {
    /* 存储不可用：本次会话内仍可正常使用，只是关掉页面后不保留 */
  }
}

// 从任意文本里抽取 6 位 A 股代码（逗号 / 空格 / 换行 / 顿号分隔都行，方便一次粘贴一串）。
export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

// 把用户输入的一串代码并入已有自选，返回去重后的新列表 + 实际新增数量。
export function addCodes(existing: string[], raw: string): { next: string[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.includes(c));
  return { next: [...existing, ...incoming], added: incoming.length };
}

// 从自选中批量移除指定代码，返回剩余列表。
export function removeCodes(existing: string[], toRemove: string[]): string[] {
  if (toRemove.length === 0) return existing;
  const drop = new Set(toRemove);
  return existing.filter((c) => !drop.has(c));
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

/** 拉取服务端自选股；有 updated_at 且比本地新时返回 codes，否则 null。 */
export async function pullServerWatch(
  fetcher: () => Promise<{ codes: string[]; updated_at: string | null }>,
): Promise<string[] | null> {
  try {
    const remote = await fetcher();
    if (!remote.updated_at) return null;
    if (remote.updated_at === loadServerStamp()) return null;
    const codes = remote.codes.filter((c) => /^\d{6}$/.test(c));
    saveWatch(codes);
    saveServerStamp(remote.updated_at);
    return codes;
  } catch {
    return null;
  }
}

/** 把当前列表同步到服务端（失败静默）。 */
export async function pushServerWatch(
  codes: string[],
  saver: (codes: string[]) => Promise<{ updated_at: string | null }>,
) {
  try {
    const out = await saver(codes);
    saveServerStamp(out.updated_at);
  } catch {
    /* 同步失败不阻断本地操作 */
  }
}
