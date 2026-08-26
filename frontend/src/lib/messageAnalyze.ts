/** 消息 AI 批量分析 —— 复用 /api/messages/analyze/run（NDJSON 流 + 用户 LLM 配置） */

import { apiUrl } from "./base";
import { ApiError, authHeaders, type AnalyzedMessage } from "./api";
import { hasLlm, loadLlm } from "./llm";

export interface MessageAnalyzeProgress {
  current: number;
  total: number;
  id: string;
  kind: string;
}

export interface MessageAnalyzeRunResult {
  total: number;
  ok: number;
  failed: number;
  items: AnalyzedMessage[];
  errors: { id: string; message: string }[];
}

export interface MessageAnalyzeHandlers {
  onProgress?: (p: MessageAnalyzeProgress) => void;
  onItem?: (item: AnalyzedMessage) => void;
  onItemError?: (id: string, message: string) => void;
}

export async function messageAnalyzeRun(
  analyzedIds: string[],
  rawIds: string[] = [],
  handlers: MessageAnalyzeHandlers = {},
  signal?: AbortSignal,
): Promise<MessageAnalyzeRunResult> {
  const llm = loadLlm();
  if (!llm) throw new ApiError("尚未接入 AI，请先在「接入 AI」里配置", 400);

  let resp: Response;
  try {
    resp = await fetch(apiUrl("/api/messages/analyze/run"), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ llm, raw_ids: rawIds, analyzed_ids: analyzedIds }),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("连接不到后端", 0);
  }

  if (!resp.ok) {
    let body: { detail?: string } | null = null;
    try {
      body = await resp.json();
    } catch {
      /* ignore */
    }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权：请在「接入 AI」页填写访问密钥", 401);
    }
    throw new ApiError(body?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const items: AnalyzedMessage[] = [];
  const errors: { id: string; message: string }[] = [];
  let total = 0;
  let ok = 0;
  let failed = 0;
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
      let ev: {
        type: string;
        current?: number;
        total?: number;
        id?: string;
        kind?: string;
        data?: AnalyzedMessage;
        message?: string;
        ok?: number;
        failed?: number;
      };
      try {
        ev = JSON.parse(t);
      } catch {
        continue;
      }
      if (ev.type === "progress" && ev.current != null && ev.total != null && ev.id) {
        handlers.onProgress?.({
          current: ev.current,
          total: ev.total,
          id: ev.id,
          kind: ev.kind || "analyzed",
        });
      } else if (ev.type === "item" && ev.data) {
        items.push(ev.data);
        handlers.onItem?.(ev.data);
      } else if (ev.type === "item_error" && ev.id) {
        errors.push({ id: ev.id, message: ev.message || "分析失败" });
        handlers.onItemError?.(ev.id, ev.message || "分析失败");
      } else if (ev.type === "done") {
        total = ev.total ?? items.length + errors.length;
        ok = ev.ok ?? items.length;
        failed = ev.failed ?? errors.length;
      } else if (ev.type === "error") {
        errMsg = ev.message || "分析失败";
      }
    }
  }
  if (errMsg) throw new ApiError(errMsg, 502);
  return { total, ok, failed, items, errors };
}

export { hasLlm };
