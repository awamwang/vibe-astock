import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check, Loader2, Pencil, Plus, Star, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { BlockStocksTable } from "@/components/block/BlockStocksTable";
import {
  api, ApiError,
  type ManagedBlockRow, type Quote, type ThemeAliasEntry, type ThsBlockStocksDetail,
} from "@/lib/api";
import {
  isBlockFollowed, setFollowBlocksCache, type FollowBlock,
} from "@/lib/message-follow-blocks";
import { keywordsSettingsTo } from "@/lib/settingsNav";
import {
  aliasesForBlockName, buildAliasesByCanonical, normalizeThemeTag,
  themeAliasEntriesFromConfig, thsBlockCodeSubtitle, thsBlockKindLabel,
  thsCustomSubtypeLabel, THS_NODE_TYPE_LABEL,
} from "@/lib/thsBlocks";
import { cn } from "@/lib/utils";

const ALIAS_MAX_LEN = 20;
const POLL_MS = 2000;
const MAX_WAIT_MS = 120_000;

const notify = {
  success: (msg: string) => toast.success(msg, { position: "top-center", duration: 3500 }),
  error: (msg: string) => toast.error(msg, { position: "top-center", duration: 5000 }),
};

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function DetailSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}

/** 同花顺成分股 / 关注用的类型：人气页签回退 ths_kind */
export function thsStocksKind(row: Pick<ManagedBlockRow, "kind" | "ths_kind">): string {
  const k = (row.ths_kind || "").trim();
  if (k && k !== "hot") return k;
  if (row.kind && row.kind !== "hot") return row.kind;
  return "";
}

export function SourceBadges({ row }: { row: Pick<ManagedBlockRow, "has_ths" | "has_kpl"> }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {row.has_ths && (
        <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700 dark:text-sky-300">
          同花顺
        </span>
      )}
      {row.has_kpl && (
        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
          开盘啦
        </span>
      )}
      {!row.has_ths && !row.has_kpl && (
        <span className="text-muted-foreground/50">—</span>
      )}
    </span>
  );
}

export function FollowBlockButton({
  followed,
  onToggle,
  size = "sm",
  className,
  disabled,
}: {
  followed: boolean;
  onToggle: () => void;
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
}) {
  const iconCls = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  return (
    <button
      type="button"
      disabled={disabled}
      title={followed ? "取消关注" : "关注板块"}
      aria-label={followed ? "取消关注" : "关注板块"}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md border transition-colors disabled:opacity-50",
        size === "md" ? "h-8 gap-1.5 px-2.5 text-xs font-semibold" : "h-7 w-7",
        followed
          ? "border-amber-500/40 bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 dark:text-amber-300"
          : "border-border bg-background text-muted-foreground hover:border-amber-500/35 hover:text-amber-700 dark:hover:text-amber-300",
        className,
      )}
    >
      <Star className={cn(iconCls, followed && "fill-current")} />
      {size === "md" && (followed ? "已关注" : "关注")}
    </button>
  );
}

interface Props {
  kind: string;
  blockId: string;
  name?: string;
  /** 行情板块代码（88xxxx），有则优先展示 */
  code?: string;
  /** 板块管理融合行；有则展示来源 / 开盘啦等扩展字段 */
  row?: ManagedBlockRow | null;
  /** 受控别名表；不传则组件内自加载 */
  aliasEntries?: ThemeAliasEntry[];
  /** 别名保存成功后同步给父级（列表展示用） */
  onAliasEntriesChange?: (entries: ThemeAliasEntry[]) => void;
  /** 受控关注列表；不传则组件内自加载 */
  followBlocks?: FollowBlock[];
  /** 关注变更后同步给父级（列表星标用） */
  onFollowBlocksChange?: (blocks: FollowBlock[]) => void;
}

/** 同花顺 / 板块管理共用详情：元数据 + 别名增删改 + 成分股 */
export function BlockDetailPanel({
  kind,
  blockId,
  name,
  code,
  row = null,
  aliasEntries: aliasEntriesProp,
  onAliasEntriesChange,
  followBlocks: followBlocksProp,
  onFollowBlocksChange,
}: Props) {
  const controlledAliases = aliasEntriesProp !== undefined;
  const controlledFollow = followBlocksProp !== undefined;
  const [detail, setDetail] = useState<ThsBlockStocksDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [followBlocksLocal, setFollowBlocksLocal] = useState<FollowBlock[]>([]);
  const [followBusy, setFollowBusy] = useState(false);
  const [aliasEntriesLocal, setAliasEntriesLocal] = useState<ThemeAliasEntry[]>([]);
  const [aliasSaving, setAliasSaving] = useState(false);
  const [aliasDraft, setAliasDraft] = useState("");
  const [aliasEditingKey, setAliasEditingKey] = useState<string | null>(null);
  const [aliasEditDraft, setAliasEditDraft] = useState("");

  const aliasEntries = controlledAliases ? aliasEntriesProp : aliasEntriesLocal;
  const setAliasEntries = useCallback((entries: ThemeAliasEntry[]) => {
    if (!controlledAliases) setAliasEntriesLocal(entries);
    onAliasEntriesChange?.(entries);
  }, [controlledAliases, onAliasEntriesChange]);

  const followBlocks = controlledFollow ? followBlocksProp : followBlocksLocal;
  const setFollowBlocks = useCallback((blocks: FollowBlock[]) => {
    if (!controlledFollow) setFollowBlocksLocal(blocks);
    onFollowBlocksChange?.(blocks);
  }, [controlledFollow, onFollowBlocksChange]);

  const stocksKind = row ? thsStocksKind(row) : kind;
  const stocksId = row ? (row.id || "") : blockId;
  /** 热点主题根（非森林虚拟根）可按整主题取成分股 */
  const isThemeRootStocks = !!row
    && row.block_type === "hot-theme"
    && row.id !== "__theme_root__"
    && !!row.has_ths
    && !!stocksId
    && !!stocksKind;
  const canLoadStocks = row
    ? (row.node_type !== "branch" || isThemeRootStocks) && !!row.has_ths && !!stocksId && !!stocksKind
    : !!stocksKind && !!stocksId;
  const isBranch = row?.node_type === "branch" && !isThemeRootStocks;
  const isKplOnly = !!row && (!row.has_ths || !row.id || !stocksKind);

  useEffect(() => {
    let cancelled = false;
    setLoading(false);
    setDetail(null);
    setQuotes({});
    setError(null);

    if (!canLoadStocks) return;

    setLoading(true);
    const load = async () => {
      const started = Date.now();
      while (!cancelled) {
        try {
          const data = await api.thsBlockStocks(stocksKind, stocksId);
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
  }, [canLoadStocks, stocksKind, stocksId]);

  useEffect(() => {
    if (controlledFollow) return;
    let cancelled = false;
    api.messageFollowBlocks()
      .then((data) => {
        if (!cancelled) setFollowBlocksLocal(setFollowBlocksCache(data.blocks || []));
      })
      .catch(() => { /* 关注列表失败不阻断详情 */ });
    return () => { cancelled = true; };
  }, [controlledFollow, kind, blockId, row?.id, row?.kind]);

  useEffect(() => {
    if (controlledAliases) return;
    let cancelled = false;
    api.themeAliases()
      .then((cfg) => {
        if (!cancelled) setAliasEntriesLocal(themeAliasEntriesFromConfig(cfg));
      })
      .catch(() => { /* 别名失败不阻断详情 */ });
    return () => { cancelled = true; };
  }, [controlledAliases, kind, blockId, row?.id, row?.kind]);

  useEffect(() => {
    setAliasDraft("");
    setAliasEditingKey(null);
    setAliasEditDraft("");
  }, [kind, blockId, row?.id, row?.kind, row?.name]);

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
        for (const r of rows) Object.assign(merged, r);
        setQuotes(merged);
      })
      .catch(() => { if (!cancelled) setQuotes({}); });
    return () => { cancelled = true; };
  }, [codes.join(",")]);

  const displayName = (row?.name || name || detail?.name || blockId || "").trim();
  const displayCode = (row?.code || detail?.code || code || "").trim();
  const codeSub = thsBlockCodeSubtitle({ id: stocksId || blockId, code: displayCode || null });
  const followKind = stocksKind || kind;
  const followId = stocksId || blockId;
  const canFollow = !!followKind && !!followId && (!row || (!!row.has_ths && !!row.id));
  const followed = canFollow && isBlockFollowed(followKind, followId, followBlocks);
  const aliasesByCanonical = useMemo(
    () => buildAliasesByCanonical(aliasEntries),
    [aliasEntries],
  );
  const selectedAliases = aliasesForBlockName(displayName, aliasesByCanonical);
  const selectedSubtype = row ? thsCustomSubtypeLabel(row) : null;
  const detailTitle = displayName;
  const kindLabel = row
    ? (thsBlockKindLabel(row.kind) || row.kpl_kind_label || "—")
    : thsBlockKindLabel(kind);

  const persistAliases = useCallback(async (next: ThemeAliasEntry[]) => {
    setAliasSaving(true);
    try {
      const r = await api.saveThemeAliases(next);
      const entries = themeAliasEntriesFromConfig(r);
      setAliasEntries(entries);
      notify.success("板块别名已保存");
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "保存别名失败");
    } finally {
      setAliasSaving(false);
    }
  }, [setAliasEntries]);

  const addAlias = useCallback(async () => {
    const alias = normalizeThemeTag(aliasDraft);
    const canonical = normalizeThemeTag(displayName);
    if (!alias || !canonical) {
      notify.error("请填写别名");
      return;
    }
    if (alias.length > ALIAS_MAX_LEN || canonical.length > ALIAS_MAX_LEN) {
      notify.error(`板块名不超过 ${ALIAS_MAX_LEN} 个字`);
      return;
    }
    if (alias === canonical) {
      notify.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => normalizeThemeTag(e.alias) === alias)) {
      notify.error("该别名已存在");
      return;
    }
    const next = [
      ...aliasEntries,
      { alias, canonical, type: "" },
    ].sort((a, b) => {
      const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
      if (byCanonical !== 0) return byCanonical;
      return a.alias.localeCompare(b.alias, "zh-CN");
    });
    setAliasDraft("");
    await persistAliases(next);
  }, [aliasDraft, displayName, aliasEntries, persistAliases]);

  const removeAlias = useCallback(async (alias: string) => {
    if (aliasEditingKey === alias) {
      setAliasEditingKey(null);
      setAliasEditDraft("");
    }
    const next = aliasEntries.filter((e) => e.alias !== alias);
    await persistAliases(next);
  }, [aliasEditingKey, aliasEntries, persistAliases]);

  const saveEditAlias = useCallback(async () => {
    if (!aliasEditingKey) return;
    const alias = normalizeThemeTag(aliasEditDraft);
    const canonical = normalizeThemeTag(displayName);
    if (!alias || !canonical) {
      notify.error("请填写别名");
      return;
    }
    if (alias.length > ALIAS_MAX_LEN || canonical.length > ALIAS_MAX_LEN) {
      notify.error(`板块名不超过 ${ALIAS_MAX_LEN} 个字`);
      return;
    }
    if (alias === canonical) {
      notify.error("别名与标准板块不能相同");
      return;
    }
    if (aliasEntries.some((e) => e.alias === alias && e.alias !== aliasEditingKey)) {
      notify.error("该别名已存在");
      return;
    }
    const next = aliasEntries
      .map((e) =>
        e.alias === aliasEditingKey
          ? { alias, canonical, type: e.type }
          : e,
      )
      .sort((a, b) => {
        const byCanonical = a.canonical.localeCompare(b.canonical, "zh-CN");
        if (byCanonical !== 0) return byCanonical;
        return a.alias.localeCompare(b.alias, "zh-CN");
      });
    setAliasEditingKey(null);
    setAliasEditDraft("");
    await persistAliases(next);
  }, [aliasEditingKey, aliasEditDraft, displayName, aliasEntries, persistAliases]);

  const toggleFollow = useCallback(async () => {
    if (!canFollow) return;
    setFollowBusy(true);
    try {
      const data = await api.toggleMessageFollowBlock({
        kind: followKind,
        id: followId,
        name: displayName,
        follow: !followed,
      });
      const next = setFollowBlocksCache(data.blocks || []);
      setFollowBlocks(next);
      notify.success(!followed ? `已关注「${displayName}」` : `已取消关注「${displayName}」`);
    } catch (e) {
      notify.error(e instanceof ApiError ? e.message : "更新关注失败");
    } finally {
      setFollowBusy(false);
    }
  }, [canFollow, followKind, followId, displayName, followed, setFollowBlocks]);

  const stockCount = row?.stock_count ?? detail?.count;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-foreground">{displayName || "—"}</h2>
          {row && <SourceBadges row={row} />}
          {row?.node_type && (
            <span className={cn(
              "rounded-md px-2 py-0.5 text-[11px] font-bold",
              row.node_type === "branch"
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                : "bg-primary/15 text-primary",
            )}>
              {THS_NODE_TYPE_LABEL[row.node_type] || row.node_type}
            </span>
          )}
          {canFollow && (
            <FollowBlockButton
              followed={!!followed}
              onToggle={() => void toggleFollow()}
              size="md"
              disabled={followBusy}
            />
          )}
        </div>
        {row?.tree_path ? (
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{row.tree_path}</p>
        ) : (
          <p className="mt-1 font-mono text-xs">
            <span className="font-medium text-foreground">{codeSub.primary}</span>
            {codeSub.secondary && (
              <span className="text-muted-foreground"> · {codeSub.secondary}</span>
            )}
          </p>
        )}
      </div>

      <div className="rounded-xl border border-border/60 bg-muted/15 p-4 text-sm">
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
          <div className="text-muted-foreground">类型</div>
          <div className="text-foreground">{kindLabel}</div>
          {row?.code && row.code !== detailTitle && (
            <>
              <div className="text-muted-foreground">同花顺行情码</div>
              <div className="font-mono text-foreground">{row.code}</div>
            </>
          )}
          {row?.id && row.id !== detailTitle && row.id !== row.code && (
            <>
              <div className="text-muted-foreground">同花顺本地 ID</div>
              <div className="font-mono text-muted-foreground">{row.id}</div>
            </>
          )}
          {row?.kpl_code && row.kpl_code !== detailTitle && (
            <>
              <div className="text-muted-foreground">开盘啦 PlateID</div>
              <div className="font-mono text-foreground">{row.kpl_code}</div>
            </>
          )}
          {row?.kpl_name && (
            <>
              <div className="text-muted-foreground">开盘啦原始名称</div>
              <div className="text-foreground">{row.kpl_name}</div>
            </>
          )}
          {row?.kpl_kind_label
            && row.kpl_kind_label !== (thsBlockKindLabel(row.kind) || "") && (
            <>
              <div className="text-muted-foreground">开盘啦类型</div>
              <div className="text-foreground">{row.kpl_kind_label}</div>
            </>
          )}
          {row?.kpl_power != null && (
            <>
              <div className="text-muted-foreground">开盘啦人气</div>
              <div className="text-foreground">{row.kpl_power}</div>
            </>
          )}
          {row?.kpl_pct != null && (
            <>
              <div className="text-muted-foreground">开盘啦涨幅</div>
              <div className="text-foreground">{row.kpl_pct}%</div>
            </>
          )}
          {selectedSubtype && (
            <>
              <div className="text-muted-foreground">子类型</div>
              <div className="text-foreground">{selectedSubtype}</div>
            </>
          )}
          {row?.hex_id && (
            <>
              <div className="text-muted-foreground">Hex ID</div>
              <div className="font-mono text-foreground">{row.hex_id}</div>
            </>
          )}
          {row?.query_key && (
            <>
              <div className="text-muted-foreground">问财 Key</div>
              <div className="break-all text-foreground">{row.query_key}</div>
            </>
          )}
          {!row && displayCode && (
            <>
              <div className="text-muted-foreground">行情代码</div>
              <div className="font-mono text-foreground">{displayCode}</div>
            </>
          )}
          {!row && (
            <>
              <div className="text-muted-foreground">本地 ID</div>
              <div className="font-mono text-muted-foreground">{blockId}</div>
            </>
          )}
          {stockCount != null && (
            <>
              <div className="text-muted-foreground">成分数</div>
              <div className="text-foreground">{stockCount}</div>
            </>
          )}
        </div>
      </div>

      <DetailSection label="板块别名">
        <p className="mb-2 text-xs text-muted-foreground">
          与配置中的板块别名同源；别名匹配到标准名「{displayName || blockId}」。
          {" "}
          <Link
            to={keywordsSettingsTo("theme-aliases")}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-primary underline-offset-2 hover:underline"
          >
            打开配置 →
          </Link>
        </p>
        {selectedAliases.length === 0 ? (
          <p className="mb-2 text-xs text-muted-foreground">暂无别名，可在下方添加。</p>
        ) : (
          <ul className="mb-3 space-y-1.5">
            {selectedAliases.map((alias) => {
              const editing = aliasEditingKey === alias;
              return (
                <li
                  key={alias}
                  className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border/50 bg-background/60 px-2.5 py-1.5"
                >
                  {editing ? (
                    <>
                      <input
                        className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
                        value={aliasEditDraft}
                        onChange={(e) => setAliasEditDraft(e.target.value)}
                        disabled={aliasSaving}
                        placeholder="别名"
                        maxLength={ALIAS_MAX_LEN}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void saveEditAlias();
                          } else if (e.key === "Escape") {
                            setAliasEditingKey(null);
                            setAliasEditDraft("");
                          }
                        }}
                      />
                      <button
                        type="button"
                        disabled={aliasSaving}
                        onClick={() => void saveEditAlias()}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-primary hover:bg-primary/10 disabled:opacity-50"
                        title="保存"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={aliasSaving}
                        onClick={() => {
                          setAliasEditingKey(null);
                          setAliasEditDraft("");
                        }}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                        title="取消"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        disabled={aliasSaving || aliasEditingKey != null}
                        onClick={() => {
                          setAliasEditingKey(alias);
                          setAliasEditDraft(alias);
                        }}
                        className="min-w-0 flex-1 truncate text-left text-sm font-medium text-foreground hover:text-primary disabled:opacity-50"
                        title={`点击修改「${alias}」`}
                      >
                        {alias}
                      </button>
                      <button
                        type="button"
                        disabled={aliasSaving || aliasEditingKey != null}
                        onClick={() => {
                          setAliasEditingKey(alias);
                          setAliasEditDraft(alias);
                        }}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
                        title={`编辑「${alias}」`}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        disabled={aliasSaving || aliasEditingKey != null}
                        onClick={() => void removeAlias(alias)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                        title={`删除「${alias}」`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm"
            value={aliasDraft}
            onChange={(e) => setAliasDraft(e.target.value)}
            disabled={aliasSaving || aliasEditingKey != null}
            placeholder="新增别名（原始写法）"
            maxLength={ALIAS_MAX_LEN}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void addAlias();
              }
            }}
          />
          <button
            type="button"
            disabled={aliasSaving || aliasEditingKey != null || !aliasDraft.trim()}
            onClick={() => void addAlias()}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs font-semibold text-foreground hover:bg-muted/40 disabled:opacity-50"
          >
            {aliasSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            添加
          </button>
        </div>
      </DetailSection>

      {isBranch ? (
        <p className="rounded-lg bg-muted/25 px-3 py-2 text-sm text-muted-foreground">
          分组节点不含成分股，请展开并选择叶子板块。
        </p>
      ) : isKplOnly ? (
        <p className="rounded-lg bg-muted/25 px-3 py-2 text-sm text-muted-foreground">
          仅开盘啦类型的板块暂无同花顺成分股；可在短线盘面用人气/点查查看。
        </p>
      ) : (
        <DetailSection label="成分股">
          {row && (
            <p className="mb-2 text-xs text-muted-foreground">
              {row.kind === "theme" || row.ths_kind === "theme"
                ? "口径：按同花顺热点主题成分股（ths-theme），不以开盘啦成分为准。"
                : "口径：按同花顺板块成分股（本地 INI），不以开盘啦成分为准。"}
            </p>
          )}
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
                  key={`${stocksKind}-${stocksId}`}
                  stocks={detail.stocks}
                  quotes={quotes}
                />
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{error || "—"}</p>
          )}
        </DetailSection>
      )}
    </div>
  );
}
