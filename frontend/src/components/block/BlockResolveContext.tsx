import {
  createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import { api, type BlockResolveItem } from "@/lib/api";

interface BlockResolveCtx {
  byRaw: Record<string, BlockResolveItem>;
  get: (name: string) => BlockResolveItem | undefined;
}

const Ctx = createContext<BlockResolveCtx | null>(null);

function normKey(name: string): string {
  return (name || "").replace(/\s+/g, "").trim();
}

const POLL_MS = 2000;

/** 批量解析板块名称，供 BlockLabel 读取映射结果 */
export function BlockResolveScope({ names, children }: { names: string[]; children: ReactNode }) {
  const [byRaw, setByRaw] = useState<Record<string, BlockResolveItem>>({});
  const key = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const n of names) {
      const k = normKey(n);
      if (!k || seen.has(k)) continue;
      seen.add(k);
      out.push(k);
    }
    return out.sort().join("\0");
  }, [names]);
  const indexAtRef = useRef<string | null>(null);

  useEffect(() => {
    const list = key ? key.split("\0") : [];
    if (!list.length) {
      setByRaw({});
      indexAtRef.current = null;
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const applyResolve = (data: Awaited<ReturnType<typeof api.thsBlocksResolve>>) => {
      if (cancelled) return;
      setByRaw(data.by_raw || {});
      indexAtRef.current = data.index?.updated_at ?? null;
    };

    const needsPoll = (index: Awaited<ReturnType<typeof api.thsBlocksResolve>>["index"]) =>
      !index?.complete || !index?.ready || !!index?.ensuring;

    const poll = async () => {
      if (cancelled) return;
      try {
        const info = await api.thsBlocksIndexInfo();
        if (cancelled) return;
        const ts = info.updated_at ?? null;
        if (ts !== indexAtRef.current || info.complete) {
          const data = await api.thsBlocksResolve(list);
          applyResolve(data);
          if (!needsPoll(data.index)) return;
        }
      } catch {
        /* 轮询失败时静默，下次继续 */
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };

    api.thsBlocksResolve(list)
      .then((data) => {
        applyResolve(data);
        if (!cancelled && needsPoll(data.index)) poll();
      })
      .catch(() => { if (!cancelled) setByRaw({}); });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [key]);

  const value = useMemo<BlockResolveCtx>(() => ({
    byRaw,
    get: (name: string) => byRaw[normKey(name)],
  }), [byRaw]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBlockResolveOptional(): BlockResolveCtx | null {
  return useContext(Ctx);
}

export function useBlockResolve(name: string): BlockResolveItem | undefined {
  const ctx = useContext(Ctx);
  return ctx?.get(name);
}
