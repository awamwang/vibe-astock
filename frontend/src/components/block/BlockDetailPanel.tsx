import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Star } from "lucide-react";
import { toast } from "sonner";
import { BlockStocksTable } from "@/components/block/BlockStocksTable";
import { api, ApiError, type Quote, type ThsBlockStocksDetail } from "@/lib/api";
import {
  isBlockFollowed, setFollowBlocksCache, type FollowBlock,
} from "@/lib/message-follow-blocks";
import { thsBlockCodeSubtitle, thsBlockKindLabel } from "@/lib/thsBlocks";
import { cn } from "@/lib/utils";

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
  /** 行情板块代码（88xxxx），有则优先展示 */
  code?: string;
}

/** 同花顺板块详情：元数据 + 成分股行情 */
export function BlockDetailPanel({ kind, blockId, name, code }: Props) {
  const [detail, setDetail] = useState<ThsBlockStocksDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [followBlocks, setFollowBlocks] = useState<FollowBlock[]>([]);
  const [followBusy, setFollowBusy] = useState(false);

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

  useEffect(() => {
    let cancelled = false;
    api.messageFollowBlocks()
      .then((data) => {
        if (!cancelled) setFollowBlocks(setFollowBlocksCache(data.blocks || []));
      })
      .catch(() => { /* 关注列表失败不阻断详情 */ });
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
  const displayCode = (detail?.code || code || "").trim();
  const codeSub = thsBlockCodeSubtitle({ id: blockId, code: displayCode || null });
  const followed = isBlockFollowed(kind, blockId, followBlocks);

  const toggleFollow = useCallback(async () => {
    setFollowBusy(true);
    try {
      const data = await api.toggleMessageFollowBlock({
        kind,
        id: blockId,
        name: displayName,
        follow: !followed,
      });
      setFollowBlocks(setFollowBlocksCache(data.blocks || []));
      toast.success(!followed ? `已关注「${displayName}」` : `已取消关注「${displayName}」`, {
        position: "top-center",
        duration: 3500,
      });
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "更新关注失败", {
        position: "top-center",
        duration: 5000,
      });
    } finally {
      setFollowBusy(false);
    }
  }, [kind, blockId, displayName, followed]);

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-foreground">{displayName}</h2>
          <button
            type="button"
            disabled={followBusy}
            title={followed ? "取消关注" : "关注板块"}
            onClick={() => void toggleFollow()}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-semibold transition-colors disabled:opacity-50",
              followed
                ? "border-amber-500/40 bg-amber-500/15 text-amber-700 dark:text-amber-300"
                : "border-border bg-background text-muted-foreground hover:border-amber-500/35 hover:text-amber-700 dark:hover:text-amber-300",
            )}
          >
            <Star className={cn("h-4 w-4", followed && "fill-current")} />
            {followed ? "已关注" : "关注"}
          </button>
        </div>
        <p className="mt-1 font-mono text-xs">
          <span className="font-medium text-foreground">{codeSub.primary}</span>
          {codeSub.secondary && (
            <span className="text-muted-foreground"> · {codeSub.secondary}</span>
          )}
        </p>
      </div>

      <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
          <dt className="text-muted-foreground">类型</dt>
          <dd className="text-foreground">{thsBlockKindLabel(kind)}</dd>
          {displayCode && (
            <>
              <dt className="text-muted-foreground">行情代码</dt>
              <dd className="font-mono text-foreground">{displayCode}</dd>
            </>
          )}
          <dt className="text-muted-foreground">本地 ID</dt>
          <dd className="font-mono text-muted-foreground">{blockId}</dd>
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
