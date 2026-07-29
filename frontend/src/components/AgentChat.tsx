import { useState } from "react";
import { Send, Loader2, MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { agentPost, type ChatMsg } from "@/lib/agent";

interface Props {
  endpoint: string;
  placeholder?: string;
  suggestions?: string[];
}

export function AgentChat({ endpoint, placeholder = "就上面的结论追问…", suggestions = [] }: Props) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function send(q?: string) {
    const text = (q ?? input).trim();
    if (!text || loading) return;
    const next: ChatMsg[] = [...msgs, { role: "user", content: text }];
    setMsgs(next);
    setInput("");
    setLoading(true);
    try {
      const r = await agentPost<{ answer?: string; error?: string }>(endpoint, { messages: next });
      setMsgs([...next, { role: "assistant", content: r.answer || `出错：${r.error || "未知"}` }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", content: `请求失败：${e instanceof Error ? e.message : ""}` }]);
    }
    setLoading(false);
  }

  return (
    <section>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.2em] text-primary">
        <MessageCircle className="h-3.5 w-3.5" /> 追问 · Ask
      </div>
      <div className="glass rounded-2xl p-4">
        {msgs.length === 0 && suggestions.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {suggestions.map((s, i) => (
              <button key={i} onClick={() => send(s)}
                className="rounded-full border border-border bg-muted/40 px-3 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.length > 0 && (
          <div className="mb-3 space-y-3">
            {msgs.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cn("max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                  m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground")}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 思考中…</div>}
          </div>
        )}
        <div className="flex items-center gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder={placeholder}
            className="flex-1 rounded-lg border border-border bg-card px-3 py-2 text-sm" />
          <button onClick={() => send()} disabled={loading}
            className="flex items-center gap-1 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
}
