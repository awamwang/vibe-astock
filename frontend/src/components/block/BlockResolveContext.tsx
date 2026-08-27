import {
  createContext, useContext, useEffect, useMemo, useState, type ReactNode,
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

  useEffect(() => {
    const list = key ? key.split("\0") : [];
    if (!list.length) {
      setByRaw({});
      return;
    }
    let cancelled = false;
    api.thsBlocksResolve(list)
      .then((data) => { if (!cancelled) setByRaw(data.by_raw || {}); })
      .catch(() => { if (!cancelled) setByRaw({}); });
    return () => { cancelled = true; };
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
