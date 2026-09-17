import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle, BookMarked, Check, ChevronDown, ChevronUp, Copy, FileText, Trash2,
  Loader2, Send, Settings, Sparkles, X,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type ExperienceDraftFile, type ExperienceTopicMeta,
} from "@/lib/api";
import { hasLlm, chatStream, type ChatMsg } from "@/lib/llm";
import {
  buildOrganizePrompt, parseOrganizeJson, suffixTitleDate,
  EXPERIENCE_CATEGORIES,
} from "@/lib/experience";
import { StockResolveScope } from "@/components/stock/StockResolveContext";
import { BlockResolveScope } from "@/components/block/BlockResolveContext";
import { StockBlockTagRows } from "@/components/TargetTags";

export function ExperienceMemory() {
  const [root, setRoot] = useState("");
  const [topics, setTopics] = useState<ExperienceTopicMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedBody, setSelectedBody] = useState("");
  const [selectedMeta, setSelectedMeta] = useState<ExperienceTopicMeta | null>(null);
  const [note, setNote] = useState("");
  const [organizing, setOrganizing] = useState(false);
  const [drafts, setDrafts] = useState<ExperienceDraftFile[] | null>(null);
  const [draftTab, setDraftTab] = useState(0);
  const [committing, setCommitting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [qaOpen, setQaOpen] = useState(false);
  const [qaConfigured, setQaConfigured] = useState(false);
  const [qaMsgs, setQaMsgs] = useState<ChatMsg[]>([]);
  const [qaInput, setQaInput] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaErr, setQaErr] = useState<string | null>(null);
  const qaScrollRef = useRef<HTMLDivElement>(null);
  const qaAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try {
      const meta = await api.experienceMeta();
      setRoot(meta.root);
      setTopics(meta.topics || []);
      setLoadErr(null);
    } catch (e) {
      setLoadErr(e instanceof ApiError ? e.message : "加载经验库失败");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setSelectedBody("");
      setSelectedMeta(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const t = await api.experienceTopic(selected);
        if (!cancelled) {
          setSelectedBody(t.content || "");
          setSelectedMeta(t);
        }
      } catch (e) {
        if (!cancelled) {
          setSelectedBody("");
          setSelectedMeta(null);
          toast.error(e instanceof ApiError ? e.message : "读取主题失败");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  useEffect(() => {
    if (qaOpen) setQaConfigured(hasLlm());
  }, [qaOpen]);

  useEffect(() => () => qaAbortRef.current?.abort(), []);

  useEffect(() => {
    qaScrollRef.current?.scrollTo({ top: qaScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [qaMsgs, qaLoading]);

  const copyRoot = async () => {
    if (!root) return;
    try {
      await navigator.clipboard.writeText(root);
      toast.success("已复制记忆库路径");
    } catch {
      toast.error("复制失败");
    }
  };

  const organize = async () => {
    const text = note.trim();
    if (!text) {
      toast.error("请先输入一段经验文字");
      return;
    }
    if (!hasLlm()) {
      toast.error("请先在「接入 AI」配置模型");
      return;
    }
    setOrganizing(true);
    setDrafts(null);
    try {
      const meta = await api.experienceMeta();
      const hits = (await api.experienceRetrieve(text.slice(0, 200), 5)).hits || [];
      const bodies = hits.map((h) => ({
        filename: h.filename,
        title: h.title,
        content: h.content,
      }));
      const prompt = buildOrganizePrompt(text, meta.topics || [], bodies);
      const result = await chatStream(
        [{ role: "user", content: prompt }],
        "你只输出合法 JSON，不要调用工具，不要解释。",
      );
      const files = parseOrganizeJson(result.content);
      setDrafts(files);
      setDraftTab(0);
      toast.success(`已整理为 ${files.length} 个主题，请预览确认`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "整理失败"));
    } finally {
      setOrganizing(false);
    }
  };

  const commit = async () => {
    if (!drafts?.length) return;
    setCommitting(true);
    try {
      const res = await api.experienceCommit(drafts);
      setTopics(res.topics || []);
      setRoot(res.root || root);
      setDrafts(null);
      setNote("");
      const pick = res.written?.[0]?.filename || res.topics?.[0]?.filename;
      if (pick) setSelected(pick);
      toast.success(`已写入 ${res.written?.length || 0} 个主题（已解析个股/板块）`);
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "写入失败");
    } finally {
      setCommitting(false);
    }
  };

  const deleteTopic = async () => {
    if (!selected) return;
    const meta = topics.find((t) => t.filename === selected);
    const label = meta?.title || selected;
    if (!window.confirm(`确定删除主题「${label}」？此操作不可恢复。`)) return;
    setDeleting(true);
    try {
      const res = await api.experienceDelete(selected);
      setTopics(res.topics || []);
      setRoot(res.root || root);
      setSelected(null);
      setSelectedBody("");
      setSelectedMeta(null);
      toast.success("已删除主题");
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  };

  const sendQa = async (text: string) => {
    const q = text.trim();
    if (!q || qaLoading) return;
    setQaInput("");
    setQaErr(null);
    const history: ChatMsg[] = [...qaMsgs, { role: "user", content: q }];
    setQaMsgs([...history, { role: "assistant", content: "" }]);
    setQaLoading(true);
    qaAbortRef.current?.abort();
    const ac = new AbortController();
    qaAbortRef.current = ac;
    const alive = () => qaAbortRef.current === ac && !ac.signal.aborted;
    const patchLast = (fn: (c: string) => string) =>
      setQaMsgs((m) => m.map((msg, i) => (
        i === m.length - 1 && msg.role === "assistant"
          ? { ...msg, content: fn(msg.content) }
          : msg
      )));
    try {
      let memoryCtx = "";
      try {
        const r = await api.experienceRetrieve(q, 3);
        memoryCtx = r.context || "";
      } catch {
        /* 检索失败仍可问答 */
      }
      const context = [
        "你是交易经验问答助手。优先依据【经验记忆】作答；记忆不足时再给一般性短线思路，并说明依据有限。",
        "不构成投资建议。",
        memoryCtx,
      ].filter(Boolean).join("\n\n");
      await chatStream(history, context, {
        onDelta: (t) => { if (alive()) patchLast((c) => c + t); },
      }, ac.signal);
    } catch (e) {
      setQaMsgs((m) => m.filter((msg, i) => !(i === m.length - 1 && msg.role === "assistant" && !msg.content)));
      if (!ac.signal.aborted) setQaErr(e instanceof ApiError ? e.message : "问答失败");
    } finally {
      if (qaAbortRef.current === ac) {
        qaAbortRef.current = null;
        setQaLoading(false);
      }
    }
  };

  const draft = drafts?.[draftTab];

  const updateDraft = (patch: Partial<ExperienceDraftFile>) => {
    setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, ...patch } : f)) ?? null);
  };

  const applyDate = (date: string) => {
    if (!draft) return;
    const title = suffixTitleDate(draft.title || "", date);
    const filename = `${suffixTitleDate((draft.filename || title).replace(/\.md$/i, ""), date)}.md`;
    updateDraft({ date, title, filename });
  };

  const stockQueries = useMemo(() => {
    const out: { code?: string | null; name?: string | null }[] = [];
    for (const t of topics) {
      for (const s of t.stocks || []) {
        if (s.name || s.code) out.push({ code: s.code, name: s.name });
      }
    }
    for (const s of selectedMeta?.stocks || []) {
      if (s.name || s.code) out.push({ code: s.code, name: s.name });
    }
    for (const d of drafts || []) {
      for (const s of d.stocks || []) {
        if (s.name || s.code) out.push({ code: s.code, name: s.name });
      }
    }
    return out;
  }, [topics, selectedMeta, drafts]);

  const blockNames = useMemo(() => {
    const names: string[] = [];
    for (const t of topics) {
      for (const s of t.sectors || []) {
        if (s.name) names.push(s.name);
      }
    }
    for (const s of selectedMeta?.sectors || []) {
      if (s.name) names.push(s.name);
    }
    for (const d of drafts || []) {
      for (const s of d.sectors || []) {
        if (s.name) names.push(s.name);
      }
    }
    return names;
  }, [topics, selectedMeta, drafts]);

  return (
    <StockResolveScope queries={stockQueries}>
    <BlockResolveScope names={blockNames}>
    <div className="-mx-6 -my-6 flex h-[calc(100vh-1rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <PageHeader
          title="经验记忆"
          subtitle="把交易心得整理成可检索的主题 Markdown，提取日期、分类与个股/板块，供本页问答与全局「问 AI」调取"
        />

        {loadErr && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {loadErr}
          </div>
        )}

        <GlassCard className="mb-4">
          <h3 className="mb-2 text-sm font-semibold">记录一段经验</h3>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={6}
            placeholder="例如：连板高度掉下来后，宁可等二波也不要硬核接力……"
            className="mb-3 w-full resize-y rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void organize()}
              disabled={organizing || !note.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-40"
            >
              {organizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              AI 整理
            </button>
            {!hasLlm() && (
              <Link to="/settings" className="text-xs text-muted-foreground hover:text-primary">
                尚未接入 AI → 去配置
              </Link>
            )}
            <span className="text-[11px] text-muted-foreground">
              将提取日期、经验分类、个股与板块，弹出预览后再写入
            </span>
          </div>
        </GlassCard>

        <GlassCard className="mb-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">记忆库路径</h3>
            <button
              type="button"
              onClick={() => void copyRoot()}
              disabled={!root}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              <Copy className="h-3 w-3" /> 复制
            </button>
          </div>
          <code className="block break-all rounded-lg bg-black/30 px-3 py-2 font-mono text-xs text-muted-foreground">
            {root || "加载中…"}
          </code>
          <p className="mt-2 text-[11px] text-muted-foreground">
            外部 Agent 可直接读取该目录下的 <code className="text-foreground/80">index.md</code> 与各主题 <code className="text-foreground/80">.md</code>
          </p>
        </GlassCard>

        <GlassCard className="mb-2">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <FileText className="h-4 w-4 text-primary" /> 主题列表（只读）
            </h3>
            <button
              type="button"
              onClick={() => void deleteTopic()}
              disabled={!selected || deleting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 disabled:opacity-40"
              title="从记忆库删除当前主题"
            >
              {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              删除
            </button>
          </div>
          {topics.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无主题。输入经验后点「AI 整理」开始沉淀。</p>
          ) : (
            <div className="grid gap-3 lg:grid-cols-[minmax(0,22rem)_1fr] xl:grid-cols-[minmax(0,28rem)_1fr]">
              <ul className="max-h-[36rem] space-y-1.5 overflow-y-auto pr-1">
                {topics.map((t) => (
                  <li key={t.filename}>
                    <button
                      type="button"
                      onClick={() => setSelected(t.filename)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                        selected === t.filename
                          ? "border-primary/40 bg-primary/10 text-foreground"
                          : "border-border/60 hover:border-primary/30",
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-1.5">
                        {t.category && (
                          <span className="rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {t.category}
                          </span>
                        )}
                        {t.date && (
                          <span className="text-[10px] text-muted-foreground">{t.date}</span>
                        )}
                      </div>
                      <div className="mt-0.5 font-medium">{t.title}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{t.summary || t.filename}</div>
                      <StockBlockTagRows stocks={t.stocks} sectors={t.sectors} />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="min-h-0">
                {selected && selectedMeta && (
                  <div className="mb-2 rounded-lg border border-border/50 bg-black/20 px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {selectedMeta.category && (
                        <span className="rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          {selectedMeta.category}
                        </span>
                      )}
                      {selectedMeta.date && (
                        <span className="text-[11px] text-muted-foreground">{selectedMeta.date}</span>
                      )}
                    </div>
                    <StockBlockTagRows
                      stocks={selectedMeta.stocks}
                      sectors={selectedMeta.sectors}
                      showEmpty
                    />
                  </div>
                )}
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  {selected ? (selectedBody || "加载中…") : "点击左侧主题查看正文"}
                </pre>
              </div>
            </div>
          )}
        </GlassCard>
      </div>

      {drafts && draft && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4"
          onClick={() => { if (!committing) setDrafts(null); }}
        >
          <div
            className="glass flex max-h-[min(92vh,900px)] w-full max-w-4xl flex-col p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex shrink-0 items-center justify-between gap-3">
              <h2 className="text-base font-semibold">预览将写入的主题</h2>
              <button
                type="button"
                disabled={committing}
                onClick={() => setDrafts(null)}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-auto pr-1">
              {drafts.length > 1 && (
                <div className="flex flex-wrap gap-1.5">
                  {drafts.map((f, i) => (
                    <button
                      key={`${f.title}-${i}`}
                      type="button"
                      onClick={() => setDraftTab(i)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs",
                        i === draftTab
                          ? "border-primary/40 bg-primary/15 text-primary"
                          : "border-border text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {f.title}
                    </button>
                  ))}
                </div>
              )}
              <label className="mb-1 block text-[11px] text-muted-foreground">标题 / 文件名 / 日期</label>
              <div className="flex flex-wrap gap-2">
                <input
                  value={draft.title}
                  onChange={(e) => updateDraft({ title: e.target.value })}
                  className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
                />
                <input
                  value={draft.filename || `${draft.title}.md`}
                  onChange={(e) => updateDraft({ filename: e.target.value })}
                  className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 font-mono text-sm outline-none focus:border-primary/50"
                />
                <input
                  value={draft.date || ""}
                  onChange={(e) => applyDate(e.target.value)}
                  placeholder="YYYY-MM-DD"
                  className="w-36 rounded-lg border border-border bg-black/20 px-3 py-1.5 font-mono text-sm outline-none focus:border-primary/50"
                />
              </div>
              <label className="mb-1 block text-[11px] text-muted-foreground">经验分类</label>
              <select
                value={draft.category || "方法论"}
                onChange={(e) => updateDraft({ category: e.target.value })}
                className="mb-1 w-full max-w-xs rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              >
                {EXPERIENCE_CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <label className="mb-1 block text-[11px] text-muted-foreground">一句话摘要</label>
              <input
                value={draft.summary}
                onChange={(e) => updateDraft({ summary: e.target.value })}
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              />
              <label className="mb-1 block text-[11px] text-muted-foreground">
                个股候选（写入时按消息分析口径扫描正文并匹配）
              </label>
              <input
                value={(draft.stocks || []).map((s) => [s.code, s.name].filter(Boolean).join(" ")).join("；")}
                onChange={(e) => {
                  const stocks = e.target.value.split(/[；;、]/).map((part) => {
                    const t = part.trim();
                    if (!t) return null;
                    const m = t.match(/^(\d{6})\s*(.*)$/);
                    if (m) return { code: m[1], name: m[2].trim() || null };
                    return { code: null, name: t };
                  }).filter(Boolean) as NonNullable<ExperienceDraftFile["stocks"]>;
                  updateDraft({ stocks });
                }}
                placeholder="600519 贵州茅台；平安银行"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              />
              <label className="mb-1 block text-[11px] text-muted-foreground">
                板块候选（写入时按消息分析口径扫描正文并匹配）
              </label>
              <input
                value={(draft.sectors || []).map((s) => s.name).join("；")}
                onChange={(e) => {
                  const sectors = e.target.value
                    .split(/[；;、,，]/)
                    .map((x) => x.trim())
                    .filter(Boolean)
                    .map((name) => ({ name }));
                  updateDraft({ sectors });
                }}
                placeholder="连板；新能源"
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              />
              <StockBlockTagRows stocks={draft.stocks} sectors={draft.sectors} showEmpty />
              <label className="mb-1 block text-[11px] text-muted-foreground">Markdown 正文</label>
              <textarea
                value={draft.content}
                onChange={(e) => updateDraft({ content: e.target.value })}
                rows={10}
                className="w-full resize-y rounded-lg border border-border bg-black/20 px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-primary/50"
              />
            </div>
            <div className="mt-3 flex shrink-0 justify-end gap-2">
              <button
                type="button"
                onClick={() => setDrafts(null)}
                disabled={committing}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void commit()}
                disabled={committing}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-40"
              >
                {committing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                确认写入
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="shrink-0 border-t border-border/60 bg-background/95 backdrop-blur">
        <button
          type="button"
          onClick={() => setQaOpen((o) => !o)}
          className="flex w-full items-center justify-between px-6 py-2.5 text-sm font-medium"
        >
          <span className="flex items-center gap-2">
            <BookMarked className="h-4 w-4 text-primary" />
            经验问答
            <span className="text-xs font-normal text-muted-foreground">始终使用记忆库</span>
          </span>
          {qaOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </button>

        {qaOpen && (
          <div className="flex h-[min(40vh,22rem)] flex-col border-t border-border/40 px-6 pb-3">
            {!qaConfigured ? (
              <div className="flex flex-1 flex-col items-start justify-center gap-3 text-sm">
                <p className="text-muted-foreground">问答需要先接入你的 AI 模型。</p>
                <Link to="/settings" className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-primary hover:bg-primary/25">
                  <Settings className="h-4 w-4" /> 去接入 AI
                </Link>
              </div>
            ) : (
              <>
                <div ref={qaScrollRef} className="min-h-0 flex-1 space-y-2 overflow-auto py-2 text-sm">
                  {qaMsgs.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      基于已整理的经验主题回答。例如：「连板掉下来怎么处理？」「我总结过哪些情绪周期规律？」
                    </p>
                  )}
                  {qaMsgs.map((m, i) => (
                    <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                      <div className={cn(
                        "max-w-[90%] rounded-2xl px-3 py-2 leading-relaxed",
                        m.role === "user" ? "bg-primary/20" : "bg-muted/40",
                      )}>
                        <p className="whitespace-pre-wrap">{m.content}</p>
                      </div>
                    </div>
                  ))}
                  {qaLoading && (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> 检索记忆并作答…
                    </div>
                  )}
                  {qaErr && (
                    <div className="flex items-center gap-2 text-xs text-destructive">
                      <AlertCircle className="h-3.5 w-3.5" /> {qaErr}
                    </div>
                  )}
                </div>
                <div className="flex items-end gap-2 pt-1">
                  <textarea
                    value={qaInput}
                    onChange={(e) => setQaInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void sendQa(qaInput);
                      }
                    }}
                    rows={1}
                    placeholder="就经验记忆提问…"
                    className="flex-1 resize-none rounded-lg border border-border bg-black/20 px-3 py-2 text-sm outline-none focus:border-primary/50"
                  />
                  <button
                    type="button"
                    onClick={() => void sendQa(qaInput)}
                    disabled={qaLoading || !qaInput.trim()}
                    className="rounded-lg bg-primary/15 p-2 text-primary hover:bg-primary/25 disabled:opacity-40"
                  >
                    <Send className="h-4 w-4" />
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
    </BlockResolveScope>
    </StockResolveScope>
  );
}
