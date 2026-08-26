import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Search, RefreshCw, Loader2, ChevronDown, ChevronUp, Plus, Trash2,
  ExternalLink, Sparkles, Check, Newspaper, ArrowUpDown,
} from "lucide-react";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type AnalyzedMessage, type MessageSourceInfo, type RawMessageDraft,
} from "@/lib/api";
import {
  EFFECT_LABEL, FRESHNESS_LABEL, IMPACT_LABEL, STATUS_LABEL,
  formatMarkLabel, keywordHint, targetHint, targetTitle,
} from "@/lib/messages";
import { hasLlm, messageAnalyzeRun } from "@/lib/messageAnalyze";
import { Link } from "react-router-dom";

const SORTABLE_COLS = new Set(["produced_at", "title", "impact_level"]);

function SortTh({
  col,
  label,
  hint,
  sort,
  order,
  onSort,
  className,
}: {
  col: string;
  label: string;
  hint?: string;
  sort: string;
  order: "asc" | "desc";
  onSort: (col: string) => void;
  className?: string;
}) {
  const active = sort === col;
  const sortable = SORTABLE_COLS.has(col);
  return (
    <th className={cn("px-3 py-2.5 text-left align-middle", className)}>
      {sortable ? (
        <button
          type="button"
          title={hint}
          className={cn(
            "inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide transition-colors",
            active ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => onSort(col)}
        >
          {label}
          <ArrowUpDown className={cn("h-3 w-3", active && "text-primary")} />
          {active && <span className="tabular-nums">{order === "desc" ? "↓" : "↑"}</span>}
        </button>
      ) : (
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground" title={hint}>
          {label}
        </span>
      )}
    </th>
  );
}

const IMPACT_BADGE: Record<string, string> = {
  critical: "bg-danger/15 text-danger border-danger/30",
  high: "bg-primary/15 text-primary border-primary/30",
  medium: "bg-muted text-foreground border-border",
  low: "bg-muted/60 text-muted-foreground border-border/60",
  noise: "bg-muted/40 text-muted-foreground border-border/40",
};

const selectCls =
  "rounded-lg border border-border bg-background px-2.5 py-2 text-sm font-medium text-foreground";
const inputCls =
  "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground";

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
      {children}
    </span>
  );
}

function Badge({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
}

function MessageTags({ item }: { item: AnalyzedMessage }) {
  return (
    <div className="flex flex-wrap gap-1">
      <Badge className={IMPACT_BADGE[item.impact_level] || IMPACT_BADGE.medium}>
        {IMPACT_LABEL[item.impact_level] || item.impact_level}
      </Badge>
      <Badge className="border-border bg-muted/50 text-foreground">
        {EFFECT_LABEL[item.effect_status] || item.effect_status}
      </Badge>
      <Badge className="border-border bg-muted/30 text-muted-foreground">
        {FRESHNESS_LABEL[item.freshness] || item.freshness}
      </Badge>
    </div>
  );
}

function MessageKeywords({ item }: { item: AnalyzedMessage }) {
  if (!item.keywords.length) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1" title={keywordHint(item.source_id)}>
      {item.keywords.slice(0, 6).map((k) => (
        <Badge key={k} className="border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-200">
          {k}
        </Badge>
      ))}
    </div>
  );
}

function MessageTargets({ item, max = 4 }: { item: AnalyzedMessage; max?: number }) {
  if (!item.targets.length) return <span className="text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {item.targets.slice(0, max).map((t, i) => (
        <Badge
          key={`${t.name}-${i}`}
          className={cn(
            "text-foreground",
            t.kind === "stock"
              ? "border-primary/30 bg-primary/10"
              : t.kind === "sector"
                ? "border-amber-500/30 bg-amber-500/10"
                : "border-border bg-background",
          )}
          title={targetHint(t)}
        >
          {targetTitle(t)}
        </Badge>
      ))}
    </div>
  );
}

export function MessageAnalysis() {
  const [sources, setSources] = useState<MessageSourceInfo[]>([]);
  const [items, setItems] = useState<AnalyzedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pollMsg, setPollMsg] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [impactLevel, setImpactLevel] = useState("");
  const [effectStatus, setEffectStatus] = useState("");
  const [sort, setSort] = useState("produced_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestFormat, setIngestFormat] = useState<"plain" | "structured" | "calendar">("plain");
  const [ingestText, setIngestText] = useState("");
  const [drafts, setDrafts] = useState<RawMessageDraft[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [commitLoading, setCommitLoading] = useState(false);

  const [selected, setSelected] = useState<AnalyzedMessage | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeProgress, setAnalyzeProgress] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const data = await api.messageAnalyzedList({
        q: q.trim() || undefined,
        source: source || undefined,
        impact_level: impactLevel || undefined,
        effect_status: effectStatus || undefined,
        sort,
        order,
        limit: 100,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [q, source, impactLevel, effectStatus, sort, order]);

  const loadSources = useCallback(async () => {
    try {
      setSources(await api.messageSources());
    } catch {
      /* 来源列表失败不阻塞主列表 */
    }
  }, []);

  useEffect(() => {
    loadSources();
  }, [loadSources]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const xgbSource = useMemo(() => sources.find((s) => s.id === "xgb_msgs"), [sources]);

  const toggleSort = (col: string) => {
    if (!SORTABLE_COLS.has(col)) return;
    if (sort === col) setOrder((o) => (o === "desc" ? "asc" : "desc"));
    else {
      setSort(col);
      setOrder("desc");
    }
  };

  const runPreview = async () => {
    setPreviewLoading(true);
    setErr(null);
    try {
      let parsedItems: Record<string, unknown>[] | undefined;
      if (ingestFormat !== "plain" && ingestText.trim()) {
        parsedItems = JSON.parse(ingestText) as Record<string, unknown>[];
        if (!Array.isArray(parsedItems)) parsedItems = [parsedItems];
      }
      const rows = await api.messageIngestPreview({
        format: ingestFormat,
        source_id: ingestFormat === "calendar" ? "calendar" : ingestFormat === "structured" ? "structured" : "paste",
        text: ingestFormat === "plain" ? ingestText : undefined,
        items: parsedItems,
        options: { split_mode: "auto" },
      });
      setDrafts(rows);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "解析预览失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const runCommit = async () => {
    if (!drafts.length) return;
    setCommitLoading(true);
    setErr(null);
    try {
      await api.messageIngestCommit(drafts);
      setDrafts([]);
      setIngestText("");
      setIngestOpen(false);
      await loadList();
      await loadSources();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "入库失败");
    } finally {
      setCommitLoading(false);
    }
  };

  const removeDraft = (key: string) => setDrafts((d) => d.filter((x) => x.draft_key !== key));

  const pollXgb = async () => {
    setPollMsg(null);
    try {
      const r = await api.messagePollXgb();
      const synced = await api.messageXgbResyncTargets();
      setPollMsg(`拉取 ${r.fetched} 条，入库/更新 ${r.inserted} 条，同步标的 ${synced.synced} 条`);
      await loadList();
      await loadSources();
    } catch (e) {
      setPollMsg(e instanceof ApiError ? e.message : "轮询失败");
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runAnalyze = async (ids: string[]) => {
    if (!ids.length) return;
    if (!hasLlm()) {
      setErr("请先在「接入 AI」配置模型后再分析");
      return;
    }
    setAnalyzing(true);
    setAnalyzeProgress(null);
    setErr(null);
    try {
      const result = await messageAnalyzeRun(ids, [], {
        onProgress: (p) => setAnalyzeProgress(`${p.current} / ${p.total}`),
        onItem: (item) => {
          setItems((list) => list.map((x) => (x.id === item.id ? item : x)));
          setSelected((cur) => (cur?.id === item.id ? item : cur));
        },
      });
      setPollMsg(`AI 分析完成：成功 ${result.ok} 条${result.failed ? `，失败 ${result.failed} 条` : ""}`);
      if (result.failed) {
        setErr(result.errors.map((e) => `${e.id}: ${e.message}`).join("；"));
      }
      setSelectedIds(new Set());
      await loadList();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
      setAnalyzeProgress(null);
    }
  };

  const queueAnalyze = () => runAnalyze(Array.from(selectedIds));

  const confirmItem = async (item: AnalyzedMessage) => {
    try {
      const updated = await api.messageAnalyzedPatch(item.id, { status: "confirmed" });
      setItems((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      if (selected?.id === updated.id) setSelected(updated);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "更新失败");
    }
  };

  return (
    <div className="w-full min-w-0 space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
            <Newspaper className="h-6 w-6 text-primary" />
            消息分析
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            多源快讯归集与标注 · 辅助信息整理，不构成投资建议
            {xgbSource?.last_poll_at && ` · 选股宝同步 ${xgbSource.last_poll_at}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={pollXgb}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground transition-opacity hover:bg-muted/50"
          >
            <RefreshCw className="h-4 w-4" />
            拉选股宝
          </button>
          <button
            type="button"
            onClick={() => loadList()}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {loading ? "加载中…" : "刷新列表"}
          </button>
        </div>
      </div>

      <Disclaimer />

      {err && (
        <div className="glass rounded-xl px-4 py-3 text-sm text-danger">
          {err}
        </div>
      )}
      {pollMsg && (
        <div className="glass rounded-xl border-l-4 border-l-success px-4 py-3 text-sm text-foreground">
          {pollMsg}
        </div>
      )}

      <section className="w-full min-w-0">
        <div className="mb-2">
          <SectionLabel>筛选 · Filter</SectionLabel>
        </div>
        <div className="glass w-full rounded-2xl p-4 lg:p-5">
          <div className="flex flex-wrap items-center gap-2 lg:gap-3">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                className={inputCls}
                placeholder="搜索标题、摘要、关键词…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadList()}
              />
            </div>
            <select className={selectCls} value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">全部来源</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
            <select className={selectCls} value={impactLevel} onChange={(e) => setImpactLevel(e.target.value)}>
              <option value="">全部级别</option>
              {Object.entries(IMPACT_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            <select className={selectCls} value={effectStatus} onChange={(e) => setEffectStatus(e.target.value)}>
              <option value="">全部生效</option>
              {Object.entries(EFFECT_LABEL).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
            {selectedIds.size > 0 && (
              <button
                type="button"
                disabled={analyzing}
                className="flex items-center gap-1.5 rounded-lg bg-primary/90 px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
                onClick={queueAnalyze}
              >
                {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                AI 分析 ({selectedIds.size})
              </button>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>共 <strong className="text-foreground">{total}</strong> 条</span>
            {analyzeProgress && (
              <span className="text-primary">AI 分析进度 {analyzeProgress}</span>
            )}
            {!hasLlm() && (
              <Link to="/settings" className="text-primary hover:underline">
                尚未接入 AI → 去配置
              </Link>
            )}
            {xgbSource?.last_error && (
              <span className="text-danger">选股宝：{xgbSource.last_error}</span>
            )}
          </div>
        </div>
      </section>

      <section className="w-full min-w-0">
        <div className="mb-2">
          <SectionLabel>录入 · Ingest</SectionLabel>
        </div>
        <div className="glass overflow-hidden rounded-2xl">
          <button
            type="button"
            className="flex w-full items-center justify-between px-5 py-3.5 text-left text-sm font-semibold text-foreground hover:bg-muted/30"
            onClick={() => setIngestOpen((v) => !v)}
          >
            <span className="inline-flex items-center gap-2">
              <Plus className="h-4 w-4 text-primary" />
              录入消息
            </span>
            {ingestOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          {ingestOpen && (
            <div className="space-y-4 border-t border-border/60 px-5 py-4">
              <div className="flex flex-wrap gap-2">
                {(["plain", "structured", "calendar"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors",
                      ingestFormat === f
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:text-foreground",
                    )}
                    onClick={() => setIngestFormat(f)}
                  >
                    {f === "plain" ? "文字粘贴" : f === "structured" ? "JSON" : "财经日历"}
                  </button>
                ))}
              </div>
              <textarea
                className="min-h-[120px] w-full rounded-xl border border-border bg-background p-3 text-sm font-mono text-foreground placeholder:text-muted-foreground"
                placeholder={
                  ingestFormat === "plain"
                    ? "粘贴大段文字，系统将按空行/分隔符拆分…"
                    : ingestFormat === "calendar"
                      ? '[{"title":"美联储议息","effective_at":"2026-09-17 02:00:00","content":"…"}]'
                      : '[{"title":"…","content":"…","url":"…","keywords":["…"],"marks":["highlight"]}]'
                }
                value={ingestText}
                onChange={(e) => setIngestText(e.target.value)}
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={previewLoading || !ingestText.trim()}
                  className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground disabled:opacity-40"
                  onClick={runPreview}
                >
                  {previewLoading && <Loader2 className="mr-1 inline h-4 w-4 animate-spin" />}
                  预览拆分
                </button>
                {drafts.length > 0 && (
                  <button
                    type="button"
                    disabled={commitLoading}
                    className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-40"
                    onClick={runCommit}
                  >
                    确认入库 ({drafts.length})
                  </button>
                )}
              </div>
              {drafts.length > 0 && (
                <div className="max-h-64 overflow-auto rounded-xl border border-border/60">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-muted/50 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">标题</th>
                        <th className="p-3 text-left">内容预览</th>
                        <th className="w-10 p-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {drafts.map((d) => (
                        <tr key={d.draft_key} className="border-t border-border/60">
                          <td className="p-3 align-top font-medium text-foreground">{d.title || "—"}</td>
                          <td className="p-3 align-top text-muted-foreground">{d.content.slice(0, 160)}</td>
                          <td className="p-3 align-top">
                            <button type="button" onClick={() => removeDraft(d.draft_key)} aria-label="删除">
                              <Trash2 className="h-4 w-4 text-muted-foreground hover:text-danger" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="w-full min-w-0">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <SectionLabel>消息列表 · Messages</SectionLabel>
          <p className="text-xs text-muted-foreground">
            橘黄数字 = <code className="text-foreground">keywords</code>（选股宝 SubjIds 主题频道 ID）；
            详情里 <code className="text-foreground">impact:N</code> = 选股宝 Impact 方向，存于 marks
          </p>
        </div>
        <div className="grid w-full min-w-0 gap-4 xl:grid-cols-3">
          <div className="glass min-w-0 overflow-hidden rounded-2xl xl:col-span-2">
            <div className="max-h-[calc(100vh-220px)] overflow-auto">
              {items.length === 0 && !loading && (
                <p className="p-8 text-center text-sm text-muted-foreground">
                  暂无消息，可粘贴录入或拉取选股宝
                </p>
              )}
              {loading && items.length === 0 && (
                <div className="flex items-center justify-center gap-2 p-12 text-sm text-muted-foreground">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  加载消息…
                </div>
              )}
              {items.length > 0 && (
                <table className="w-full min-w-[960px] border-collapse text-sm">
                  <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
                    <tr className="border-b border-border/60">
                      <th className="w-10 px-3 py-2.5">
                        <span className="sr-only">选择</span>
                      </th>
                      <SortTh col="title" label="标题" sort={sort} order={order} onSort={toggleSort} className="min-w-[220px]" />
                      <SortTh col="source" label="来源" sort={sort} order={order} onSort={toggleSort} className="w-24" />
                      <SortTh col="impact_level" label="级别/状态" sort={sort} order={order} onSort={toggleSort} className="w-36" />
                      <SortTh col="keywords" label="分类ID" hint="选股宝=SubjIds" sort={sort} order={order} onSort={toggleSort} className="w-28" />
                      <SortTh col="targets" label="关联标的" sort={sort} order={order} onSort={toggleSort} className="min-w-[160px]" />
                      <SortTh col="produced_at" label="产生时间" sort={sort} order={order} onSort={toggleSort} className="w-36" />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr
                        key={item.id}
                        className={cn(
                          "cursor-pointer border-b border-border/40 transition-colors hover:bg-muted/25",
                          selected?.id === item.id && "bg-primary/8",
                        )}
                        onClick={() => setSelected(item)}
                      >
                        <td className="px-3 py-3 align-top" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[hsl(var(--primary))]"
                            checked={selectedIds.has(item.id)}
                            onChange={() => toggleSelect(item.id)}
                          />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <div className="space-y-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              {item.marks.includes("highlight") && (
                                <Badge className="border-danger/40 bg-danger/15 text-danger">标红</Badge>
                              )}
                              <span className="font-semibold leading-snug text-foreground line-clamp-2">
                                {item.title || item.summary || "—"}
                              </span>
                            </div>
                            <p className="text-xs leading-relaxed text-muted-foreground line-clamp-2">
                              {item.summary || item.detail}
                            </p>
                          </div>
                        </td>
                        <td className="px-3 py-3 align-top text-xs text-muted-foreground">
                          {item.source_label}
                        </td>
                        <td className="px-3 py-3 align-top">
                          <MessageTags item={item} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <MessageKeywords item={item} />
                        </td>
                        <td className="px-3 py-3 align-top">
                          <MessageTargets item={item} max={3} />
                        </td>
                        <td className="px-3 py-3 align-top text-xs tabular-nums text-muted-foreground whitespace-nowrap">
                          {item.produced_at}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="glass min-w-0 rounded-2xl p-4 xl:col-span-1 max-h-[calc(100vh-220px)] overflow-auto">
            {!selected ? (
              <p className="py-12 text-center text-sm text-muted-foreground">选择左侧消息查看详情</p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3 border-b border-border/60 pb-4">
                  <div className="min-w-0 flex-1">
                    <h2 className="text-base font-bold leading-snug text-foreground line-clamp-3">
                      {selected.title || "—"}
                    </h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {selected.source_label} · {STATUS_LABEL[selected.status] || selected.status}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {selected.status !== "confirmed" && (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground"
                        onClick={() => confirmItem(selected)}
                      >
                        <Check className="h-3.5 w-3.5" /> 确认
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={analyzing || !hasLlm()}
                      className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold text-foreground disabled:opacity-40"
                      onClick={() => runAnalyze([selected.id])}
                    >
                      {analyzing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      AI 分析
                    </button>
                  </div>
                </div>

                {selected.url && (
                  <a
                    href={selected.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
                  >
                    <ExternalLink className="h-4 w-4" /> 原文链接
                  </a>
                )}

                {(selected.marks.length > 0 || selected.keywords.length > 0) && (
                  <div className="flex flex-wrap gap-2">
                    {selected.marks.map((m) => (
                      <Badge key={m} className="border-muted-foreground/30 bg-muted/40 text-foreground" title={formatMarkLabel(m)}>
                        {formatMarkLabel(m)}
                      </Badge>
                    ))}
                    {selected.keywords.map((k) => (
                      <Badge
                        key={k}
                        className="border-amber-500/35 bg-amber-500/12 text-amber-800 dark:text-amber-200"
                        title={keywordHint(selected.source_id)}
                      >
                        {k}
                      </Badge>
                    ))}
                  </div>
                )}

                <div>
                  <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">摘要</p>
                  <p className="text-sm leading-relaxed text-foreground">{selected.summary || "—"}</p>
                </div>

                <div>
                  <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-muted-foreground">详情</p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                    {selected.detail || "—"}
                  </p>
                </div>

                <div className="glass rounded-xl bg-muted/20 p-4 text-sm">
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
                    <dt className="text-muted-foreground">产生</dt>
                    <dd className="font-medium tabular-nums text-foreground">{selected.produced_at}</dd>
                    <dt className="text-muted-foreground">生效</dt>
                    <dd className="text-foreground">
                      {selected.effective_mode === "scheduled" && selected.effective_at
                        ? selected.effective_at
                        : "立即（回测按产生时间）"}
                    </dd>
                    <dt className="text-muted-foreground">级别</dt>
                    <dd className="text-foreground">{IMPACT_LABEL[selected.impact_level]}</dd>
                    <dt className="text-muted-foreground">新旧</dt>
                    <dd className="text-foreground">{FRESHNESS_LABEL[selected.freshness]}</dd>
                    <dt className="text-muted-foreground">炒作</dt>
                    <dd className="text-foreground">{EFFECT_LABEL[selected.effect_status]}</dd>
                  </dl>
                </div>

                {selected.targets.length > 0 && (
                  <div>
                    <p className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      影响标的
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {selected.targets.map((t, i) => (
                        <Badge
                          key={i}
                          className={cn(
                            "px-2.5 py-1 text-sm text-foreground",
                            t.kind === "stock"
                              ? "border-primary/30 bg-primary/10"
                              : t.kind === "sector"
                                ? "border-amber-500/30 bg-amber-500/10"
                                : "border-border bg-background",
                          )}
                          title={targetHint(t)}
                        >
                          {targetTitle(t)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
