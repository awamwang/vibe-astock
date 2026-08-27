import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { BlockStocksTable } from "@/components/block/BlockStocksTable";
import { api, ApiError, type Quote, type ThsBlockStocksDetail } from "@/lib/api";
import { thsBlockKindLabel } from "@/lib/thsBlocks";

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

const POLL_MS = 2000;
const MAX_WAIT_MS = 120_000;

interface Props {
  kind: string;
  blockId: string;
  name?: string;
}

/** 同花顺板块详情：元数据 + 成分股行情 */
export function BlockDetailPanel({ kind, blockId, name }: Props) {
  const [detail, setDetail] = useState<ThsBlockStocksDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    setQuotes({});
    setError(null);

    const load = async () => {
      const started = Date.now();
      while (!cancelled) {
        try {
          const data = await api.thsBlockStocks(kind, blockId);
          if (!cancelled) {
            setDetail(data);
            setError(null);
          }
          return;
        } catch (e) {
          const retry = e instanceof ApiError && e.status === 409 && Date.now() - started < MAX_WAIT_MS;
          if (retry) {
            try {
              await api.thsBlocksIndexInfo();
            } catch {
              /* 触发后端异步补拉即可 */
            }
            await new Promise((r) => setTimeout(r, POLL_MS));
            continue;
          }
          if (!cancelled) {
            setDetail(null);
            setError(e instanceof ApiError ? e.message : "加载失败");
          }
          return;
        }
      }
    };

    load().finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [kind, blockId]);

  const codes = useMemo(
    () => (detail?.stocks || []).map((s) => s.code).filter(Boolean),
    [detail?.stocks],
  );

  useEffect(() => {
    if (!codes.length) {
      setQuotes({});
      return;
    }
    let cancelled = false;
    const batches = chunk(codes, 80);
    Promise.all(batches.map((batch) => api.quote(batch.join(","))))
      .then((rows) => {
        if (cancelled) return;
        const merged: Record<string, Quote> = {};
        for (const row of rows) Object.assign(merged, row);
        setQuotes(merged);
      })
      .catch(() => { if (!cancelled) setQuotes({}); });
    return () => { cancelled = true; };
  }, [codes.join(",")]);

  const displayName = name || detail?.name || blockId;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-foreground">{displayName}</h2>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{blockId}</p>
      </div>

      <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
          <dt className="text-muted-foreground">类型</dt>
          <dd className="text-foreground">{thsBlockKindLabel(kind)}</dd>
          {detail?.count != null && (
            <>
              <dt className="text-muted-foreground">成分数</dt>
              <dd className="text-foreground">{detail.count}</dd>
            </>
          )}
        </dl>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">成分股</p>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载成分股…
          </div>
        ) : detail ? (
          <>
            <p className="mb-2 text-xs text-muted-foreground">
              共 <strong className="text-foreground">{detail.count}</strong> 只
            </p>
            {detail.count === 0 ? (
              <p className="text-sm text-muted-foreground">暂无成分股数据</p>
            ) : (
              <BlockStocksTable
                key={`${kind}-${blockId}`}
                stocks={detail.stocks}
                quotes={quotes}
              />
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{error || "—"}</p>
        )}
      </div>
    </div>
  );
}
