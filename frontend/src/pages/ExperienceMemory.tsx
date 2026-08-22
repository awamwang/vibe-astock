import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle, BookMarked, Check, ChevronDown, ChevronUp, Copy, FileText,
  Loader2, Send, Settings, Sparkles,
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
import { buildOrganizePrompt, parseOrganizeJson } from "@/lib/experience";

export function ExperienceMemory() {
  const [root, setRoot] = useState("");
  const [topics, setTopics] = useState<ExperienceTopicMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedBody, setSelectedBody] = useState("");
  const [note, setNote] = useState("");
  const [organizing, setOrganizing] = useState(false);
  const [drafts, setDrafts] = useState<ExperienceDraftFile[] | null>(null);
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
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const t = await api.experienceTopic(selected);
        if (!cancelled) setSelectedBody(t.content || "");
      } catch (e) {
        if (!cancelled) {
          setSelectedBody("");
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
      toast.success(`已归纳为 ${files.length} 个主题，请预览确认`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "归纳失败"));
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
      toast.success(`已写入 ${res.written?.length || 0} 个主题`);
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

  return (
    <div className="-mx-6 -my-6 flex h-[calc(100vh-1rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
        <PageHeader
          title="经验记忆"
          subtitle="把交易心得归纳成可检索的主题 Markdown，供本页问答与全局「问 AI」调取"
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
              AI 归纳
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
              <h3 className="text-sm font-semibold">预览将写入的主题</h3>
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
            <label className="mb-1 block text-[11px] text-muted-foreground">主题名 / 文件名</label>
            <div className="mb-3 flex flex-wrap gap-2">
              <input
                value={draft.title}
                onChange={(e) => {
                  const title = e.target.value;
                  setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, title } : f)) ?? null);
                }}
                className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
              />
              <input
                value={draft.filename || `${draft.title}.md`}
                onChange={(e) => {
                  const filename = e.target.value;
                  setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, filename } : f)) ?? null);
                }}
                className="min-w-[8rem] flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 font-mono text-sm outline-none focus:border-primary/50"
              />
            </div>
            <label className="mb-1 block text-[11px] text-muted-foreground">一句话摘要</label>
            <input
              value={draft.summary}
              onChange={(e) => {
                const summary = e.target.value;
                setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, summary } : f)) ?? null);
              }}
              className="mb-3 w-full rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
            <label className="mb-1 block text-[11px] text-muted-foreground">Markdown 正文</label>
            <textarea
              value={draft.content}
              onChange={(e) => {
                const content = e.target.value;
                setDrafts((ds) => ds?.map((f, i) => (i === draftTab ? { ...f, content } : f)) ?? null);
              }}
              rows={12}
              className="w-full resize-y rounded-lg border border-border bg-black/20 px-3 py-2 font-mono text-xs leading-relaxed outline-none focus:border-primary/50"
            />
          </GlassCard>
        )}

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
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold">
            <FileText className="h-4 w-4 text-primary" /> 主题列表（只读）
          </h3>
          {topics.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无主题。输入经验后点「AI 归纳」开始沉淀。</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              <ul className="space-y-1">
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
                      <div className="font-medium">{t.title}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">{t.summary || t.filename}</div>
                    </button>
                  </li>
                ))}
              </ul>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                {selected ? (selectedBody || "加载中…") : "点击左侧主题查看正文"}
              </pre>
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
                      基于已归纳的经验主题回答。例如：「连板掉下来怎么处理？」「我总结过哪些情绪周期规律？」
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
  );
}
