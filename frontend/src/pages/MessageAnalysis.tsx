import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Search, RefreshCw, Loader2, ChevronDown, ChevronUp, Plus, Trash2,
  ExternalLink, Sparkles, Check,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type AnalyzedMessage, type MessageSourceInfo, type RawMessageDraft,
} from "@/lib/api";
import {
  EFFECT_LABEL, FRESHNESS_LABEL, IMPACT_LABEL, STATUS_LABEL, targetTitle,
} from "@/lib/messages";

const SORT_OPTIONS = [
  { value: "produced_at", label: "产生时间" },
  { value: "impact_level", label: "影响级别" },
  { value: "title", label: "标题" },
];

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
        limit: 80,
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

  const runPreview = async () => {
    setPreviewLoading(true);
    setErr(null);
    try {
      let items: Record<string, unknown>[] | undefined;
      if (ingestFormat !== "plain" && ingestText.trim()) {
        items = JSON.parse(ingestText) as Record<string, unknown>[];
        if (!Array.isArray(items)) items = [items];
      }
      const rows = await api.messageIngestPreview({
        format: ingestFormat,
        source_id: ingestFormat === "calendar" ? "calendar" : ingestFormat === "structured" ? "structured" : "paste",
        text: ingestFormat === "plain" ? ingestText : undefined,
        items,
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
      setPollMsg(`拉取 ${r.fetched} 条，新增 ${r.inserted} 条`);
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

  const queueAnalyze = async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    try {
      await api.messageAnalyzeQueue([], ids);
      setPollMsg(`已入队 ${ids.length} 条分析任务（Phase 2 执行）`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "入队失败");
    }
  };

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
    <div className="mx-auto max-w-6xl space-y-4 p-4 pb-16">
      <PageHeader
        title="消息分析"
        subtitle="多源快讯归集与标注，辅助信息整理，不构成投资建议"
      />
      <Disclaimer />

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {err}
        </div>
      )}
      {pollMsg && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          {pollMsg}
        </div>
      )}

      <GlassCard className="p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-zinc-500" />
            <input
              className="w-full rounded-lg border border-zinc-700/60 bg-zinc-900/60 py-2 pl-9 pr-3 text-sm"
              placeholder="搜索标题、摘要、关键词…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadList()}
            />
          </div>
          <select
            className="rounded-lg border border-zinc-700/60 bg-zinc-900/60 px-2 py-2 text-sm"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">全部来源</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <select
            className="rounded-lg border border-zinc-700/60 bg-zinc-900/60 px-2 py-2 text-sm"
            value={impactLevel}
            onChange={(e) => setImpactLevel(e.target.value)}
          >
            <option value="">全部级别</option>
            {Object.entries(IMPACT_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select
            className="rounded-lg border border-zinc-700/60 bg-zinc-900/60 px-2 py-2 text-sm"
            value={effectStatus}
            onChange={(e) => setEffectStatus(e.target.value)}
          >
            <option value="">全部生效</option>
            {Object.entries(EFFECT_LABEL).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <select
            className="rounded-lg border border-zinc-700/60 bg-zinc-900/60 px-2 py-2 text-sm"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            type="button"
            className="rounded-lg border border-zinc-600 px-2 py-2 text-sm hover:bg-zinc-800"
            onClick={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}
          >
            {order === "desc" ? "↓" : "↑"}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-lg bg-zinc-800 px-3 py-2 text-sm hover:bg-zinc-700"
            onClick={() => loadList()}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-lg bg-indigo-600/80 px-3 py-2 text-sm hover:bg-indigo-600"
            onClick={pollXgb}
          >
            <RefreshCw className="h-4 w-4" />
            拉选股宝
          </button>
          {selectedIds.size > 0 && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-lg bg-violet-600/80 px-3 py-2 text-sm"
              onClick={queueAnalyze}
            >
              <Sparkles className="h-4 w-4" />
              分析 ({selectedIds.size})
            </button>
          )}
        </div>
        {xgbSource && (
          <p className="text-xs text-zinc-500">
            选股宝轮询：{xgbSource.last_poll_at || "—"}
            {xgbSource.last_error && (
              <span className="text-amber-400 ml-2">最近错误：{xgbSource.last_error}</span>
            )}
          </p>
        )}
        <p className="text-xs text-zinc-500">共 {total} 条</p>
      </GlassCard>

      <GlassCard className="overflow-hidden">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-zinc-800/40"
          onClick={() => setIngestOpen((v) => !v)}
        >
          <span className="inline-flex items-center gap-2">
            <Plus className="h-4 w-4" />
            录入消息
          </span>
          {ingestOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {ingestOpen && (
          <div className="space-y-3 border-t border-zinc-800 px-4 py-3">
            <div className="flex flex-wrap gap-2">
              {(["plain", "structured", "calendar"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-xs border",
                    ingestFormat === f ? "border-indigo-500 bg-indigo-500/20" : "border-zinc-700",
                  )}
                  onClick={() => setIngestFormat(f)}
                >
                  {f === "plain" ? "文字粘贴" : f === "structured" ? "JSON" : "财经日历"}
                </button>
              ))}
            </div>
            <textarea
              className="min-h-[120px] w-full rounded-lg border border-zinc-700/60 bg-zinc-900/60 p-3 text-sm font-mono"
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
            <div className="flex gap-2">
              <button
                type="button"
                disabled={previewLoading || !ingestText.trim()}
                className="rounded-lg bg-zinc-700 px-3 py-2 text-sm disabled:opacity-40"
                onClick={runPreview}
              >
                {previewLoading ? <Loader2 className="h-4 w-4 animate-spin inline" /> : null}
                预览拆分
              </button>
              {drafts.length > 0 && (
                <button
                  type="button"
                  disabled={commitLoading}
                  className="rounded-lg bg-emerald-600/80 px-3 py-2 text-sm disabled:opacity-40"
                  onClick={runCommit}
                >
                  确认入库 ({drafts.length})
                </button>
              )}
            </div>
            {drafts.length > 0 && (
              <div className="max-h-64 overflow-auto rounded border border-zinc-800">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-zinc-900 text-zinc-400">
                    <tr>
                      <th className="p-2 text-left">标题</th>
                      <th className="p-2 text-left">内容预览</th>
                      <th className="p-2 w-8" />
                    </tr>
                  </thead>
                  <tbody>
                    {drafts.map((d) => (
                      <tr key={d.draft_key} className="border-t border-zinc-800/80">
                        <td className="p-2 align-top">{d.title || "—"}</td>
                        <td className="p-2 align-top text-zinc-400">{d.content.slice(0, 120)}</td>
                        <td className="p-2 align-top">
                          <button type="button" onClick={() => removeDraft(d.draft_key)}>
                            <Trash2 className="h-3.5 w-3.5 text-zinc-500 hover:text-red-400" />
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
      </GlassCard>

      <div className="grid gap-4 lg:grid-cols-5">
        <GlassCard className="lg:col-span-3 overflow-hidden">
          <div className="max-h-[calc(100vh-280px)] overflow-auto">
            {items.length === 0 && !loading && (
              <p className="p-6 text-center text-sm text-zinc-500">暂无消息，可粘贴录入或拉取选股宝</p>
            )}
            <ul className="divide-y divide-zinc-800/80">
              {items.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "cursor-pointer px-4 py-3 hover:bg-zinc-800/30",
                    selected?.id === item.id && "bg-indigo-500/10",
                  )}
                  onClick={() => setSelected(item)}
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={selectedIds.has(item.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        toggleSelect(item.id);
                      }}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {item.marks.includes("highlight") && (
                          <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-300">标红</span>
                        )}
                        <span className="font-medium text-sm truncate">{item.title || item.summary || "—"}</span>
                        <span className="text-[10px] text-zinc-500">{item.source_label}</span>
                      </div>
                      <p className="mt-1 text-xs text-zinc-400 line-clamp-2">{item.summary || item.detail}</p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px]">
                          {IMPACT_LABEL[item.impact_level] || item.impact_level}
                        </span>
                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px]">
                          {EFFECT_LABEL[item.effect_status] || item.effect_status}
                        </span>
                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px]">
                          {FRESHNESS_LABEL[item.freshness] || item.freshness}
                        </span>
                        {item.keywords.slice(0, 3).map((k) => (
                          <span key={k} className="rounded bg-indigo-900/40 px-1.5 py-0.5 text-[10px] text-indigo-200">
                            {k}
                          </span>
                        ))}
                        {item.targets.slice(0, 4).map((t, i) => (
                          <span
                            key={`${t.name}-${i}`}
                            className="rounded bg-amber-900/30 px-1.5 py-0.5 text-[10px] text-amber-100"
                            title={t.code ? `代码：${t.code}` : undefined}
                            data-code={t.code || undefined}
                          >
                            {targetTitle(t)}
                          </span>
                        ))}
                      </div>
                      <p className="mt-1 text-[10px] text-zinc-600">{item.produced_at}</p>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </GlassCard>

        <GlassCard className="lg:col-span-2 p-4 space-y-3 max-h-[calc(100vh-280px)] overflow-auto">
          {!selected ? (
            <p className="text-sm text-zinc-500">选择一条消息查看详情</p>
          ) : (
            <>
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold leading-snug">{selected.title || "—"}</h3>
                {selected.status !== "confirmed" && (
                  <button
                    type="button"
                    className="shrink-0 inline-flex items-center gap-1 rounded bg-emerald-700/60 px-2 py-1 text-xs"
                    onClick={() => confirmItem(selected)}
                  >
                    <Check className="h-3 w-3" /> 确认
                  </button>
                )}
              </div>
              <p className="text-xs text-zinc-500">
                {selected.source_label} · {STATUS_LABEL[selected.status] || selected.status}
              </p>
              {selected.url && (
                <a
                  href={selected.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-indigo-300 hover:underline"
                >
                  <ExternalLink className="h-3 w-3" /> 链接
                </a>
              )}
              {selected.marks.length > 0 && (
                <p className="text-xs text-zinc-400">标记：{selected.marks.join("、")}</p>
              )}
              {selected.keywords.length > 0 && (
                <p className="text-xs text-zinc-400">关键词：{selected.keywords.join("、")}</p>
              )}
              <div>
                <p className="text-xs font-medium text-zinc-400 mb-1">摘要</p>
                <p className="text-sm">{selected.summary || "—"}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-zinc-400 mb-1">详情</p>
                <p className="text-sm whitespace-pre-wrap text-zinc-300">{selected.detail || "—"}</p>
              </div>
              <div className="text-xs space-y-1 text-zinc-400">
                <p>产生：{selected.produced_at}</p>
                <p>
                  生效：
                  {selected.effective_mode === "scheduled" && selected.effective_at
                    ? selected.effective_at
                    : "立即（回测按产生时间）"}
                </p>
                <p>级别：{IMPACT_LABEL[selected.impact_level]}</p>
                <p>新旧：{FRESHNESS_LABEL[selected.freshness]}</p>
                <p>炒作：{EFFECT_LABEL[selected.effect_status]}</p>
              </div>
              {selected.targets.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-zinc-400 mb-1">影响标的</p>
                  <div className="flex flex-wrap gap-1">
                    {selected.targets.map((t, i) => (
                      <span
                        key={i}
                        className="rounded border border-zinc-700 px-2 py-0.5 text-xs"
                        title={t.code ? `代码：${t.code}` : t.kind}
                      >
                        {targetTitle(t)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
