import { apiUrl } from "./base";
// 用户 LLM 配置（只存本地 localStorage，不上传、不进仓库）+ 系统 AI 对话调用。

import { ApiError, authHeaders } from "./api";
import { apiModels, blockedReason, cliAvailability, cliKindOf, isCliProvider, serverAllowsCli,
  subscriptionModels, type ProviderId } from "./ai-models";

export interface LlmConfig {
  provider: ProviderId;
  baseURL: string; // CLI 订阅时留空
  apiKey: string;  // CLI 订阅时留空
  model: string;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResult {
  content: string;
  trace: { tool: string; args: Record<string, unknown> }[];
  rounds: number;
}

const KEY = "vr-llm";

export function staleBlockedProvider(): string | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const p = (JSON.parse(raw) as LlmConfig).provider;
    if (serverAllowsCli(p) !== false) return null;   // 能用 / 还不知道 → 不报
    const st = cliAvailability()?.clis.find((c) => c.kind === cliKindOf(p));
    if (st && !st.allowed) return blockedReason(p) ?? st.reason ?? "已禁用";
    if (st && !st.installed) return "本机未安装这个命令";
    return blockedReason(p) ?? "不可用";
  } catch {
    return null;
  }
}

/** 一条配置当前能不能拿来调模型（CLI 被闸 / 缺 key 都不算）。 */
export function llmCfgUsable(c: LlmConfig | null | undefined): c is LlmConfig {
  if (!c?.model) return false;
  if (serverAllowsCli(c.provider) === false) return false;
  return !!(isCliProvider(c.provider) || (c.baseURL && c.apiKey));
}

export function loadLlm(): LlmConfig | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const c = JSON.parse(raw) as LlmConfig;
    if (serverAllowsCli(c.provider) === false) return null;
    // 订阅(CLI)：有 model 即可，免 key；API：需 baseURL + key + model。
    const ok = c.model && (isCliProvider(c.provider) || (c.baseURL && c.apiKey));
    return ok ? c : null;
  } catch {
    return null;
  }
}

export function saveLlm(cfg: LlmConfig, label?: string) {
  localStorage.setItem(KEY, JSON.stringify(cfg));
  upsertSavedLlm(cfg, label);
  _overrideId = null; // 新保存的即全局默认，清掉本次会话的临时选择
  notifyLlmChange();
}

export function clearLlm() {
  localStorage.removeItem(KEY);
  notifyLlmChange();
}

export function hasLlm(): boolean {
  return resolveLlm() !== null;
}

const SAVED_KEY = "vr-llm-saved";

/** 已保存模型条目：与全局默认分开存，重启后可点选切换默认、或在问 AI 下拉里临时选用。 */
export interface SavedLlmEntry {
  id: string;
  cfg: LlmConfig;
  label: string;
  savedAt: number;
}

/** 同一端点 + 同一 model 视为同一条（API key 变更时覆盖更新）。 */
export function llmFingerprint(cfg: LlmConfig): string {
  if (isCliProvider(cfg.provider)) return `cli:${cfg.provider}:${cfg.model}`;
  return `api:${cfg.provider}:${cfg.baseURL}:${cfg.model}`;
}

/** 未填写自定义名称时的建议显示名（用于区分已保存条目）。 */
export function suggestSavedLabel(cfg: LlmConfig): string {
  if (isCliProvider(cfg.provider)) {
    return subscriptionModels.find((m) => m.id === cfg.model)?.name ?? cfg.model;
  }
  const preset = apiModels.find((m) => m.id === cfg.model);
  if (preset) return preset.name;
  const host = (() => {
    try { return new URL(cfg.baseURL).host; } catch { return cfg.baseURL || ""; }
  })();
  return host ? `${cfg.model} · ${host}` : cfg.model;
}

function readSavedRaw(): SavedLlmEntry[] {
  try {
    const raw = localStorage.getItem(SAVED_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as SavedLlmEntry[];
    if (!Array.isArray(arr)) return [];
    return arr.filter((e) => e && e.id && e.cfg && e.cfg.model);
  } catch {
    return [];
  }
}

function writeSaved(list: SavedLlmEntry[]) {
  localStorage.setItem(SAVED_KEY, JSON.stringify(list));
}

/** 各「问 AI」面板临时选用的模型（不改全局默认；刷新页面后回到默认）。 */
let _overrideId: string | null = null;

export const LLM_CHANGE_EVENT = "vr-llm-change";

function notifyLlmChange() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(LLM_CHANGE_EVENT));
}

export function llmOverrideId(): string | null {
  return _overrideId;
}

/** 本次会话临时选用；传 null 则回到全局默认。不写入 localStorage。 */
export function setLlmOverride(id: string | null) {
  _overrideId = id;
  notifyLlmChange();
}

/** 读取已保存列表；若仅有当前生效配置、列表为空，则自动迁移进去。 */
export function loadSavedLlms(): SavedLlmEntry[] {
  let list = readSavedRaw();
  if (list.length === 0) {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const c = JSON.parse(raw) as LlmConfig;
        if (c?.model) {
          const entry: SavedLlmEntry = {
            id: llmFingerprint(c),
            cfg: c,
            label: suggestSavedLabel(c),
            savedAt: Date.now(),
          };
          writeSaved([entry]);
          list = [entry];
        }
      }
    } catch { /* ignore */ }
  }
  return list;
}

/** 写入/覆盖一条已保存配置（按 fingerprint 去重）。 */
export function upsertSavedLlm(cfg: LlmConfig, label?: string): SavedLlmEntry[] {
  const id = llmFingerprint(cfg);
  const list = readSavedRaw();
  const trimmed = label?.trim() ?? "";
  const prev = list.find((e) => e.id === id);
  const next: SavedLlmEntry = {
    id,
    cfg,
    // 显式传入（含空串）以传入值为准；未传则保留原名，都没有则用建议名
    label: label !== undefined
      ? (trimmed || suggestSavedLabel(cfg))
      : (prev?.label || suggestSavedLabel(cfg)),
    savedAt: Date.now(),
  };
  const i = list.findIndex((e) => e.id === id);
  if (i >= 0) list[i] = next;
  else list.unshift(next);
  writeSaved(list);
  return list;
}

/** 仅修改已保存条目的显示名称。 */
export function renameSavedLlm(id: string, label: string): SavedLlmEntry[] {
  const list = readSavedRaw();
  const i = list.findIndex((e) => e.id === id);
  if (i < 0) return list;
  const trimmed = label.trim();
  list[i] = {
    ...list[i],
    label: trimmed || suggestSavedLabel(list[i].cfg),
  };
  writeSaved(list);
  notifyLlmChange();
  return list;
}

/** 从已保存列表删除；若删的是当前生效项，同时清掉当前配置。 */
export function removeSavedLlm(id: string): SavedLlmEntry[] {
  const list = readSavedRaw().filter((e) => e.id !== id);
  writeSaved(list);
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const c = JSON.parse(raw) as LlmConfig;
      if (c && llmFingerprint(c) === id) localStorage.removeItem(KEY);
    }
  } catch { /* ignore */ }
  if (_overrideId === id) _overrideId = null;
  notifyLlmChange();
  return list;
}

/** 将已保存条目设为全局默认模型。 */
export function activateSavedLlm(id: string): LlmConfig | null {
  const entry = readSavedRaw().find((e) => e.id === id);
  if (!entry) return null;
  const cfg = entry.cfg;
  if (!llmCfgUsable(cfg)) return null;
  localStorage.setItem(KEY, JSON.stringify(cfg));
  _overrideId = null;
  notifyLlmChange();
  return cfg;
}

/** 全局默认模型的 fingerprint；未设或已失效则为 null。 */
export function defaultLlmId(): string | null {
  const cfg = loadLlm();
  return cfg ? llmFingerprint(cfg) : null;
}

export function savedLlmLabel(entry: SavedLlmEntry): string {
  return entry.label?.trim() || suggestSavedLabel(entry.cfg);
}

/** 当前可实际调用的已保存模型（被闸的 CLI / 缺 key 的 API 排除）。 */
export function usableSavedLlms(): SavedLlmEntry[] {
  return loadSavedLlms().filter((e) => llmCfgUsable(e.cfg));
}

/**
 * 解析本次调用该用哪条配置。
 * 优先：显式 id → 会话临时选择 → 全局默认 → 列表里第一条可用。
 */
export function resolveLlm(id?: string | null): LlmConfig | null {
  const pick = (want: string | null | undefined): LlmConfig | null => {
    if (!want) return null;
    const entry = loadSavedLlms().find((e) => e.id === want);
    return entry && llmCfgUsable(entry.cfg) ? entry.cfg : null;
  };
  const fromArg = pick(id);
  if (fromArg) return fromArg;
  const fromOverride = pick(_overrideId);
  if (fromOverride) return fromOverride;
  const def = loadLlm();
  if (def) return def;
  return usableSavedLlms()[0]?.cfg ?? null;
}

export function resolveLlmId(id?: string | null): string | null {
  const cfg = resolveLlm(id);
  return cfg ? llmFingerprint(cfg) : null;
}

export interface ChatHandlers {
  onDelta?: (text: string) => void;             // 答案逐块吐字
  onTool?: (tool: string, args: Record<string, unknown>) => void; // AI 调了某数据工具
}

// 流式调后端 /api/chat（NDJSON：每行一个事件 {type: tool|delta|done|error}）。
// 边流边回调 onDelta/onTool；返回累积的最终 {content, trace, rounds}。
// signal：调用方可传 AbortController.signal，用户关面板/换问题时中止请求（省订阅/API 额度）。
export async function chatStream(
  messages: ChatMsg[],
  context: string,
  handlers: ChatHandlers = {},
  signal?: AbortSignal,
  llmOverride?: LlmConfig | null,
): Promise<ChatResult> {
  const llm = llmCfgUsable(llmOverride) ? llmOverride : resolveLlm();
  if (!llm) throw new ApiError("尚未接入 AI，请先在「接入 AI」里配置", 400);

  let resp: Response;
  try {
    resp = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ messages, context, llm }),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e; // 主动中止，原样抛给调用方
    throw new ApiError("连接不到后端，请先在项目根目录启动：.venv/bin/python server.py（默认 8910）", 0);
  }
  // 配置错误（缺 key / 未装 CLI）在流开始前以 HTTP 400 返回
  if (!resp.ok) {
    let body: any = null;
    try { body = await resp.json(); } catch { /* ignore */ }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(body?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let content = "";
  let trace: ChatResult["trace"] = [];
  let rounds = 0;
  let errMsg: string | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      let ev: any;
      try { ev = JSON.parse(t); } catch { continue; }
      if (ev.type === "delta") { content += ev.text; handlers.onDelta?.(ev.text); }
      else if (ev.type === "tool") { handlers.onTool?.(ev.tool, ev.args || {}); }
      else if (ev.type === "done") { trace = ev.trace || []; rounds = ev.rounds || 0; }
      else if (ev.type === "error") { errMsg = ev.message; }
    }
  }
  if (errMsg) throw new ApiError(errMsg, 502);
  return { content, trace, rounds };
}

// 非流式便捷包装（不需要逐字 UI 的调用方用它）。
export function chat(messages: ChatMsg[], context: string, llm?: LlmConfig | null): Promise<ChatResult> {
  return chatStream(messages, context, {}, undefined, llm);
}
