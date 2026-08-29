/** 插件当前股票 —— SSE 推送 + 短轮询兜底（Vite 代理下 SSE 常只收到首包） */

import { useEffect, useState } from "react";
import { apiUrl } from "./base";
import { api, authHeaders, type CurrentStockInfo } from "./api";

export type CurrentStockStreamStatus = "idle" | "connecting" | "connected" | "error";

const RECONNECT_MS = 3000;
/** 与后端 get_current 对齐；弹窗/代理下 SSE 不可靠时靠此驱动界面 */
const POLL_MS = 1500;

function parseSseData(block: string): CurrentStockInfo | null {
  for (const line of block.split("\n")) {
    if (!line.startsWith("data:")) continue;
    const raw = line.slice(5).trim();
    if (!raw) continue;
    try {
      return JSON.parse(raw) as CurrentStockInfo;
    } catch {
      return null;
    }
  }
  return null;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function applyStock(
  prev: CurrentStockInfo | null,
  next: CurrentStockInfo | null,
): CurrentStockInfo | null {
  if (!next?.code) return next;
  if (prev?.code === next.code && prev?.updated_at === next.updated_at) return prev;
  return next;
}

/** 订阅插件推送的当前股票变化（经系统 SSE，不直连 ths-linker） */
export function usePluginCurrentStock(enabled: boolean): {
  stock: CurrentStockInfo | null;
  code: string | null;
  status: CurrentStockStreamStatus;
  error: string | null;
} {
  const [stock, setStock] = useState<CurrentStockInfo | null>(null);
  const [status, setStatus] = useState<CurrentStockStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // 短轮询：保证 code 与后端焦点股一致，界面可响应式跟随
  useEffect(() => {
    if (!enabled) {
      setStock(null);
      setStatus("idle");
      setError(null);
      return;
    }
    let cancelled = false;
    const tick = async () => {
      try {
        const cur = await api.pluginsCurrentStock();
        if (cancelled) return;
        setStock((prev) => applyStock(prev, cur));
        setStatus((s) => (s === "idle" || s === "error" ? "connected" : s));
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        setError(e instanceof Error ? e.message : "读取焦点股失败");
      }
    };
    void tick();
    const timer = window.setInterval(() => {
      void tick();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  // SSE：有推送时更快更新（失败不影响轮询）
  useEffect(() => {
    if (!enabled) return;

    const ac = new AbortController();
    let cancelled = false;

    const consumeStream = async (resp: Response) => {
      if (!resp.body) throw new Error("无响应流");
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const block of parts) {
          if (!block.trim() || block.trim().startsWith(":")) continue;
          const parsed = parseSseData(block);
          if (parsed?.code && !cancelled) {
            setStock((prev) => applyStock(prev, parsed));
            setStatus("connected");
          }
        }
      }
    };

    const run = async () => {
      while (!cancelled) {
        try {
          const resp = await fetch(apiUrl("/api/plugins/current-stock/stream"), {
            headers: { ...authHeaders(), Accept: "text/event-stream" },
            signal: ac.signal,
          });
          if (!resp.ok) {
            throw new Error(resp.status === 401 ? "需要填写后端访问密钥" : `HTTP ${resp.status}`);
          }
          setStatus("connected");
          await consumeStream(resp);
        } catch (e) {
          if (cancelled || (e instanceof DOMException && e.name === "AbortError")) return;
        }
        if (cancelled) return;
        try {
          await sleep(RECONNECT_MS, ac.signal);
        } catch {
          return;
        }
      }
    };

    void run();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [enabled]);

  return {
    stock,
    code: stock?.code ?? null,
    status,
    error,
  };
}
