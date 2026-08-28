import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertCircle, Check, ChevronDown, ChevronUp, Copy, FileText,
  Loader2, Send, Settings, Sparkles, Newspaper, ArrowRightLeft,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import {
  api, ApiError,
  type ArticleDraftPayload, type ArticleMeta,
} from "@/lib/api";
import { hasLlm, chatStream, type ChatMsg } from "@/lib/llm";
import { buildArticlePrompt, parseArticleJson, type ArticleDraftFile } from "@/lib/articles";

export function Articles() {
  const navigate = useNavigate();
  const [root, setRoot] = useState("");
  const [articles, setArticles] = useState<ArticleMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedBody, setSelectedBody] = useState("");
  const [converting, setConverting] = useState(false);
  const [note, setNote] = useState("");
  const [organizing, setOrganizing] = useState(false);
  const [drafts, setDrafts] = useState<ArticleDraftFile[] | null>(null);
  const [draftTab, setDraftTab] = useState(0);
  const [committing, setCommitting] = useState(false);
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
      const meta = await api.articlesMeta();
      setRoot(meta.root);
      setArticles(meta.articles || []);
      setLoadErr(null);
    } catch (e) {
      setLoadErr(e instanceof ApiError ? e.message : "加载文章库失败");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setSelectedBody("");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const t = await api.articlesItem(selected);
        if (!cancelled) setSelectedBody(t.content || "");
      } catch (e) {
        if (!cancelled) {
          setSelectedBody("");
          toast.error(e instanceof ApiError ? e.message : "读取文章失败");
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
      toast.success("已复制文章库路径");
    } catch {
      toast.error("复制失败");
    }
  };

  const toMessage = async () => {
    if (!selected) {
      toast.error("请先选择一篇文章");
      return;
    }
    setConverting(true);
    try {
      const res = await api.articlesToMessage(selected);
      toast.success(
        `已转入消息分析（产生时间 ${res.produced_at || "刚刚"}）`,
        {
          action: {
            label: "去消息分析",
            onClick: () => { navigate("/messages"); },
          },
        },
      );
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "转为消息失败");
    } finally {
      setConverting(false);
    }
  };

  const organize = async () => {
    const text = note.trim();
    if (!text) {
      toast.error("请先粘贴研报或文章原文");
      return;
    }
    if (!hasLlm()) {
      toast.error("请先在「接入 AI」配置模型");
      return;
    }
    setOrganizing(true);
    setDrafts(null);
    try {
      const meta = await api.articlesMeta();
      const prompt = buildArticlePrompt(text, meta.articles || []);
      const result = await chatStream(
        [{ role: "user", content: prompt }],
        "你只输出合法 JSON，不要调用工具，不要解释。",
      );
      const files = parseArticleJson(result.content, text);
      setDrafts(files);
      setDraftTab(0);
      toast.success(`已整理 ${files.length} 篇，请预览确认`);
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
      const payload: ArticleDraftPayload[] = drafts.map((d) => ({
        title: d.title,
        summary: d.summary,
        date: d.date,
        filename: d.filename,
        original: d.original,
        stocks: d.stocks,
        sectors: d.sectors,
      }));
      const res = await api.articlesCommit(payload);
      setArticles(res.articles || []);
      setRoot(res.root || root);
      setDrafts(null);
      setNote("");
      const n = res.written?.length || 0;
      toast.success(`已写入 ${n} 篇文章（已解析个股/板块）`);
      await refresh();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "写入失败");
    } finally {
      setCommitting(false);
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
      let articleCtx = "";
      try {
        const r = await api.articlesRetrieve(q, 3);
        articleCtx = r.context || "";
      } catch {
        /* 检索失败仍可问答 */
      }
      const context = [
        "你是研报文章问答助手。优先依据【研报文章】作答；资料不足时再给一般性说明，并注明依据有限。",
        "只做信息整理，不构成投资建议。",
        articleCtx,
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

  const updateDraft = (patch: Partial<ArticleDraftFile>) => {
    setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, ...patch } : f)) ?? null);
  };

  return (
    <div className="-mx-6 -my-6 flex h-[calc(100vh-1rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <PageHeader
          title="研报文章"
          subtitle="粘贴文字版研报或文章：保留原文，提取摘要与标题，建立索引，并用个股/板块处理器解析标的"
        />

        {loadErr && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" /> {loadErr}
          </div>
        )}

        <GlassCard className="mb-4">
          <h3 className="mb-2 text-sm font-semibold">粘贴研报 / 文章原文</h3>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={8}
            placeholder="粘贴文字版研报、深度文章或资讯全文……"
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
          </div>
        </GlassCard>

        {drafts && draft && (
          <GlassCard className="mb-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">预览将写入的文章</h3>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setDrafts(null)}
                  className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
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
            {drafts.length > 1 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
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
            <div className="mb-3 flex flex-wrap gap-2">
              <input
                value={draft.title}
                onChange={(e) => updateDraft({ title: e.target.value })}
                className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              />
              <input
                value={draft.filename || `${draft.title}-${draft.date || ""}.md`}
                onChange={(e) => updateDraft({ filename: e.target.value })}
                className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 font-mono text-sm outline-none focus:border-primary/50"
              />
              <input
                value={draft.date || ""}
                onChange={(e) => updateDraft({ date: e.target.value })}
                placeholder="YYYY-MM-DD"
                className="w-36 rounded-lg border border-border bg-black/20 px-3 py-1.5 font-mono text-sm outline-none focus:border-primary/50"
              />
            </div>
            <label className="mb-1 block text-[11px] text-muted-foreground">一句话摘要</label>
            <input
              value={draft.summary}
              onChange={(e) => updateDraft({ summary: e.target.value })}
              className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
            <label className="mb-1 block text-[11px] text-muted-foreground">
              个股候选（写入时经个股处理器解析）
            </label>
            <input
              value={draft.stocks.map((s) => [s.code, s.name].filter(Boolean).join(" ")).join("；")}
              onChange={(e) => {
                const stocks = e.target.value.split(/[；;、]/).map((part) => {
                  const t = part.trim();
                  if (!t) return null;
                  const m = t.match(/^(\d{6})\s*(.*)$/);
                  if (m) return { code: m[1], name: m[2].trim() || null };
                  return { code: null, name: t };
                }).filter(Boolean) as ArticleDraftFile["stocks"];
                updateDraft({ stocks });
              }}
              placeholder="600519 贵州茅台；平安银行"
              className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
            <label className="mb-1 block text-[11px] text-muted-foreground">
              板块候选（写入时经板块处理器解析）
            </label>
            <input
              value={draft.sectors.map((s) => s.name).join("；")}
              onChange={(e) => {
                const sectors = e.target.value
                  .split(/[；;、,，]/)
                  .map((x) => x.trim())
                  .filter(Boolean)
                  .map((name) => ({ name }));
                updateDraft({ sectors });
              }}
              placeholder="白酒；创新药"
              className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
            <label className="mb-1 block text-[11px] text-muted-foreground">原文（只读预览，落盘时原样保留）</label>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
              {draft.original}
            </pre>
          </GlassCard>
        )}

        <GlassCard className="mb-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">文章库路径</h3>
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
            外部 Agent 可直接读取该目录下的 <code className="text-foreground/80">index.md</code> 与各文章 <code className="text-foreground/80">.md</code>
          </p>
        </GlassCard>

        <GlassCard className="mb-2">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <FileText className="h-4 w-4 text-primary" /> 文章列表（只读）
            </h3>
            <button
              type="button"
              onClick={() => void toMessage()}
              disabled={!selected || converting}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary/40 hover:text-primary disabled:opacity-40"
              title="把当前文章插入消息分析；产生时间为转换时刻，原文末尾保留文章文件关联"
            >
              {converting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRightLeft className="h-3.5 w-3.5" />}
              转为消息
            </button>
          </div>
          {articles.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无文章。粘贴原文后点「AI 整理」开始归档。</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              <ul className="space-y-1">
                {articles.map((t) => (
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
                      <div className="font-medium">{t.title}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{t.summary || t.filename}</div>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex min-h-0 flex-col gap-2">
                <pre className="max-h-72 flex-1 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  {selected ? (selectedBody || "加载中…") : "点击左侧文章查看正文"}
                </pre>
                {selected && (
                  <p className="text-[11px] text-muted-foreground">
                    「转为消息」会以当前时刻作为产生时间写入消息分析，并在原文末尾附上文件关联：
                    <code className="mx-1 text-foreground/80">{selected}</code>
                  </p>
                )}
              </div>
            </div>
          )}
        </GlassCard>
      </div>

      <div className="shrink-0 border-t border-border/60 bg-background/95 backdrop-blur">
        <button
          type="button"
          onClick={() => setQaOpen((o) => !o)}
          className="flex w-full items-center justify-between px-6 py-2.5 text-sm font-medium"
        >
          <span className="flex items-center gap-2">
            <Newspaper className="h-4 w-4 text-primary" />
            文章问答
            <span className="text-xs font-normal text-muted-foreground">始终使用文章库</span>
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
                      基于已归档的研报文章回答。例如：「最近归档了哪些白酒相关文章？」「某篇摘要里提到哪些个股？」
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
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> 检索文章并作答…
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
                    placeholder="就研报文章提问…"
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
  );
}
