// 通用 NDJSON 流读取器 —— 后端 /api/debate 等用「每行一个 JSON 事件」推送。

import { ApiError, authHeaders } from "@/lib/api";
import { apiUrl } from "@/lib/base";

export type NdjsonEvent = Record<string, any>;

/**
 * POST 一个 JSON body，按行消费 NDJSON 事件流。
 * - 配置类错误（400/401）在流开始前抛 ApiError。
 * - 流内 {type:"error"} 交给 onEvent 自行处理。
 */
export async function streamNdjson(
  url: string,
  body: unknown,
  onEvent: (ev: NdjsonEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(apiUrl(url), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("连接不到后端，请先在项目根目录启动：.venv/bin/python server.py（默认 8910）", 0);
  }

  if (!resp.ok) {
    let detail: any = null;
    try { detail = await resp.json(); } catch { /* 无 JSON body 就用状态码兜底 */ }
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(detail?.detail || `HTTP ${resp.status}`, resp.status);
  }
  if (!resp.body) throw new ApiError("后端无响应流", 502);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      try { onEvent(JSON.parse(t)); } catch { /* 半截行或脏行，跳过 */ }
    }
  }
}
