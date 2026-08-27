import {
  createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import { api, type StockResolveItem, type StockResolveQuery } from "@/lib/api";
import { stockQueryKey } from "@/lib/stocks";

interface StockResolveCtx {
  byKey: Record<string, StockResolveItem>;
  get: (query: StockResolveQuery) => StockResolveItem | undefined;
}

const Ctx = createContext<StockResolveCtx | null>(null);

const POLL_MS = 2000;

function dedupeQueries(queries: StockResolveQuery[]): StockResolveQuery[] {
  const seen = new Set<string>();
  const out: StockResolveQuery[] = [];
  for (const q of queries) {
    const key = stockQueryKey(q);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(q);
  }
  return out;
}

/** 批量解析股票名称或代码，供 StockLabel 读取映射结果 */
export function StockResolveScope({ queries, children }: { queries: StockResolveQuery[]; children: ReactNode }) {
  const [byKey, setByKey] = useState<Record<string, StockResolveItem>>({});
  const list = useMemo(() => dedupeQueries(queries), [queries]);
  const key = useMemo(
    () => list.map((q) => stockQueryKey(q)).sort().join("\0"),
    [list],
  );
  const indexAtRef = useRef<string | null>(null);

  useEffect(() => {
    if (!list.length) {
      setByKey({});
      indexAtRef.current = null;
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const applyResolve = (data: Awaited<ReturnType<typeof api.stocksResolve>>) => {
      if (cancelled) return;
      setByKey(data.by_key || {});
      indexAtRef.current = data.index?.updated_at ?? null;
    };

    const needsPoll = (index: Awaited<ReturnType<typeof api.stocksResolve>>["index"]) =>
      !index?.ready || !!index?.refreshing;

    const poll = async () => {
      if (cancelled) return;
      try {
        const info = await api.stocksIndexInfo();
        if (cancelled) return;
        const ts = info.updated_at ?? null;
        if (ts !== indexAtRef.current || info.ready) {
          const data = await api.stocksResolve(list);
          applyResolve(data);
          if (!needsPoll(data.index)) return;
        }
      } catch {
        /* 轮询失败时静默，下次继续 */
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };

    api.stocksResolve(list)
      .then((data) => {
        applyResolve(data);
        if (!cancelled && needsPoll(data.index)) poll();
      })
      .catch(() => { if (!cancelled) setByKey({}); });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [key, list]);

  const value = useMemo<StockResolveCtx>(() => ({
    byKey,
    get: (query: StockResolveQuery) => byKey[stockQueryKey(query)],
  }), [byKey]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStockResolveOptional(): StockResolveCtx | null {
  return useContext(Ctx);
}

export function useStockResolve(query: StockResolveQuery): StockResolveItem | undefined {
  const ctx = useContext(Ctx);
  return ctx?.get(query);
}
