import { useCallback, useEffect, useRef, useState } from "react";
import { BookMarked, ExternalLink, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, type AnalyzedMessage, type RawMessageDraft } from "@/lib/api";
import { getDefaultEndDays } from "@/lib/messages";
import { usePluginCurrentStock } from "@/lib/currentStockStream";
import { openMessageDetailPopup } from "@/components/MessageDetailPanel";
import { openSectionPopup } from "@/lib/sectionPopup";
import { setMessageManualMarksCache } from "@/lib/message-manual-marks";
import { cn } from "@/lib/utils";

const LIST_LIMIT = 80;
const TITLE_MAX = 50;
export const MESSAGE_DIARY_POPUP_NAME = "va-message-diary-popup";
export const MESSAGE_DIARY_POPUP_PATH = "/messages/diary";

/** 标题前缀：股票名称（无名称则用代码）+ 中文冒号 */
function diaryTitlePrefix(code: string | null, stockName?: string): string {
  if (!code) return "";
  const name = (stockName || "").trim();
  return `${name || code}：`;
}

/** 去掉已有股票名前缀，得到用户填写的标题正文 */
function diaryTitleBody(title: string, prefix: string): string {
  const t = title.trim();
  if (!prefix) return t;
  if (t.startsWith(prefix)) return t.slice(prefix.length).trim();
  // 兼容半角冒号
  const half = prefix.replace(/：$/, ":");
  if (half !== prefix && t.startsWith(half)) return t.slice(half.length).trim();
  return t;
}

/** 保证标题带股票名前缀，总长不超过 TITLE_MAX */
function withDiaryTitlePrefix(title: string, prefix: string): string {
  const body = diaryTitleBody(title, prefix);
  if (!prefix) return body.slice(0, TITLE_MAX);
  const room = Math.max(0, TITLE_MAX - prefix.length);
  return `${prefix}${body.slice(0, room)}`;
}

function formatStockLabel(
  code: string | null,
  name: string | undefined,
  status: string,
  error: string | null,
): string {
  if (code) {
    const n = (name || "").trim();
    return n ? `${n}（${code}）` : code;
  }
  if (status === "connecting") return "连接中…";
  if (status === "connected") return "等待焦点股…";
  if (status === "error") return error || "未连接";
  return "等待插件…";
}

function newDraftKey(): string {
  return `draft_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

/** 订阅焦点股并拉取该股的个股日记消息 */
export function useMessageDiaryList(enabled: boolean, defaultEndDays?: number) {
  const [items, setItems] = useState<AnalyzedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [stockName, setStockName] = useState("");
  const { code: streamCode, status, error } = usePluginCurrentStock(enabled);
  const days = defaultEndDays ?? getDefaultEndDays();
  const streamCodeRef = useRef<string | null>(null);
  const fetchSeqRef = useRef(0);

  const loadList = useCallback(async () => {
    if (!enabled) return;
    const seq = ++fetchSeqRef.current;
    setLoading(true);
    try {
      const data = await api.messageAnalyzedList({
        source: "manual_mark",
        match_current_stock: "yes",
        default_end_days: days,
        sort: "produced_at",
        order: "desc",
        limit: LIST_LIMIT,
        offset: 0,
      });
      if (seq !== fetchSeqRef.current) return;
      setItems(data.items || []);
      setTotal(data.total || 0);
      setCode(data.current_stock_code ?? null);
      setStockName((data.current_stock_name || "").trim());
    } catch (e) {
      if (seq !== fetchSeqRef.current) return;
      toast.error(e instanceof ApiError ? e.message : "个股日记加载失败", {
        position: "top-center",
        duration: 4000,
      });
    } finally {
      if (seq === fetchSeqRef.current) setLoading(false);
    }
  }, [enabled, days]);

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      setTotal(0);
      setCode(null);
      setStockName("");
      streamCodeRef.current = null;
      return;
    }
    void loadList();
  }, [enabled, loadList]);

  useEffect(() => {
    if (!enabled || !streamCode) return;
    if (streamCodeRef.current === streamCode) return;
    streamCodeRef.current = streamCode;
    void loadList();
  }, [enabled, streamCode, loadList]);

  return { items, total, loading, code, stockName, status, error, reload: loadList };
}

export function MessageDiaryPanel({
  items,
  loading,
  code,
  stockName,
  status,
  error,
  total,
  onClose,
  onAdded,
}: {
  items: AnalyzedMessage[];
  loading: boolean;
  code: string | null;
  stockName?: string;
  status: string;
  error: string | null;
  total: number;
  onClose?: () => void;
  onAdded?: () => void;
}) {
  const listScrollRef = useRef<HTMLDivElement>(null);
  const label = formatStockLabel(code, stockName, status, error);
  const titlePrefix = diaryTitlePrefix(code, stockName);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [quickMarks, setQuickMarks] = useState<string[]>([]);
  const [activeMark, setActiveMark] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    listScrollRef.current?.scrollTo({ top: 0 });
  }, [code]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await api.messageManualMarks();
        if (!cancelled) {
          setQuickMarks(setMessageManualMarksCache(cfg.marks || []));
        }
      } catch {
        if (!cancelled) setQuickMarks([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 换股后重置为「股票名：」前缀，避免把上只股票的草稿带到新股
  useEffect(() => {
    setTitle(diaryTitlePrefix(code, stockName));
    setContent("");
    setActiveMark(null);
    // 仅随焦点股代码切换重置；名称迟到时由下方 effect 补齐前缀
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 刻意只依赖 code
  }, [code]);

  // 焦点股名称晚于代码到达时，若标题仍是「代码：」则换成「名称：」
  useEffect(() => {
    const name = (stockName || "").trim();
    if (!code || !name) return;
    const codePrefix = `${code}：`;
    setTitle((prev) => {
      const trimmed = prev.trim();
      if (!trimmed || trimmed === codePrefix || trimmed === `${code}:`) {
        return `${name}：`;
      }
      return prev;
    });
  }, [code, stockName]);

  const applyQuickMark = (mark: string) => {
    setTitle(withDiaryTitlePrefix(mark, titlePrefix));
    setActiveMark(mark);
  };

  const submit = async () => {
    if (!code) {
      toast.error("请先在同花顺中切换到目标个股", { position: "top-center" });
      return;
    }
    const bodyPart = diaryTitleBody(title, titlePrefix);
    if (!bodyPart) {
      toast.error("请填写标题", { position: "top-center" });
      return;
    }
    const t = withDiaryTitlePrefix(title, titlePrefix);
    if (t.length > TITLE_MAX) {
      toast.error(`标题不超过 ${TITLE_MAX} 字`, { position: "top-center" });
      return;
    }
    const body = content.trim();
    const marks = activeMark && bodyPart === activeMark ? [activeMark] : [];
    const draft: RawMessageDraft = {
      draft_key: newDraftKey(),
      source_id: "manual_mark",
      source_label: "个股日记",
      title: t,
      content: body || t,
      keywords: [],
      url: "",
      marks,
      external_ref: `manual_mark_${code}_${Date.now()}`,
      targets: [
        {
          kind: "stock",
          code,
          name: (stockName || "").trim() || code,
        },
      ],
      meta: {
        manual_mark: true,
        summary: body ? body.slice(0, 120) : t,
      },
    };
    setSubmitting(true);
    try {
      await api.messageIngestCommit([draft]);
      toast.success("已添加个股日记", { position: "top-center", duration: 2500 });
      setTitle(titlePrefix);
      setContent("");
      setActiveMark(null);
      onAdded?.();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "添加失败", {
        position: "top-center",
        duration: 4000,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
        <BookMarked className="h-3.5 w-3.5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-foreground">个股日记</p>
          <p className="truncate text-[11px] text-muted-foreground" title={label}>
            {label}
            {total > 0 ? ` · ${total} 条` : ""}
          </p>
        </div>
        {loading && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />}
        {onClose && (
          <button
            type="button"
            className="rounded-md p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            title="关闭"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </header>

      <div className="shrink-0 space-y-3 border-b border-border/60 px-3 py-3">
        {!code && (
          <p className="text-center text-xs text-muted-foreground">
            请在同花顺中切换股票；需启用 vibe-ths-linker
          </p>
        )}
        {quickMarks.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {quickMarks.map((mark) => (
              <button
                key={mark}
                type="button"
                disabled={!code || submitting}
                onClick={() => applyQuickMark(mark)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors disabled:opacity-40",
                  activeMark === mark
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border bg-background text-muted-foreground hover:text-foreground",
                )}
                title={`快捷标题「${mark}」，确认后写入标记字段`}
              >
                {mark}
              </button>
            ))}
          </div>
        )}
        <div className="space-y-1.5">
          <label className="text-[11px] font-semibold text-muted-foreground">
            标题 <span className="text-danger">*</span>
            <span className="ml-1 font-normal tabular-nums">
              {title.trim().length}/{TITLE_MAX}
            </span>
          </label>
          <input
            value={title}
            onChange={(e) => {
              const next = withDiaryTitlePrefix(e.target.value, titlePrefix).slice(0, TITLE_MAX);
              setTitle(next);
              const body = diaryTitleBody(next, titlePrefix);
              if (activeMark && body !== activeMark) setActiveMark(null);
            }}
            maxLength={TITLE_MAX}
            disabled={!code || submitting}
            placeholder={titlePrefix ? `${titlePrefix}必填后缀` : "必填，50 字以内"}
            className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] font-semibold text-muted-foreground">内容（可留空）</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            disabled={!code || submitting}
            rows={3}
            placeholder="可选备注…"
            className="w-full resize-y rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-primary/50 disabled:opacity-50"
          />
        </div>
        <button
          type="button"
          disabled={!code || submitting || !diaryTitleBody(title, titlePrefix)}
          onClick={() => void submit()}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary/15 px-3 py-2 text-sm font-semibold text-primary hover:bg-primary/25 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          确认添加
        </button>
      </div>

      <div ref={listScrollRef} className="min-h-0 flex-1 overflow-auto">
        {code && items.length === 0 && !loading && (
          <p className="p-4 text-center text-xs text-muted-foreground">该股暂无个股日记</p>
        )}
        <ul className="divide-y divide-border/50">
          {items.map((msg) => (
            <li key={msg.id}>
              <button
                type="button"
                className="w-full px-3 py-2.5 text-left hover:bg-muted/40"
                onClick={() => openMessageDetailPopup(msg.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                    {msg.title || "（无标题）"}
                  </p>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {(msg.produced_at || "").slice(5, 16)}
                  </span>
                </div>
                {(msg.detail || msg.summary) && (msg.detail || msg.summary) !== msg.title && (
                  <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                    {msg.detail || msg.summary}
                  </p>
                )}
                {msg.marks.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {msg.marks.map((m) => (
                      <span
                        key={m}
                        className="rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** 独立路由弹窗：window.open('/messages/diary') */
export function MessageDiaryPopupButton() {
  const popupRef = useRef<Window | null>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const w = popupRef.current;
      if (w && w.closed) {
        popupRef.current = null;
        setActive(false);
      }
    }, 800);
    return () => window.clearInterval(timer);
  }, []);

  const openPopup = () => {
    const existing = popupRef.current;
    if (existing && !existing.closed) {
      existing.focus();
      setActive(true);
      return;
    }
    const w = openSectionPopup(MESSAGE_DIARY_POPUP_PATH, MESSAGE_DIARY_POPUP_NAME, [
      "popup=yes",
      "width=420",
      "height=720",
      "left=120",
      "top=60",
      "resizable=yes",
      "scrollbars=yes",
    ].join(","));
    if (!w) return;
    popupRef.current = w;
    setActive(true);
  };

  const closePopup = () => {
    const w = popupRef.current;
    popupRef.current = null;
    setActive(false);
    try {
      w?.close();
    } catch {
      /* 已关闭 */
    }
  };

  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors",
        active
          ? "border-primary/50 bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:text-foreground",
      )}
      title={`独立窗口 ${MESSAGE_DIARY_POPUP_PATH}，跟随焦点股添加个股日记`}
      onClick={() => {
        if (active) closePopup();
        else openPopup();
      }}
    >
      <ExternalLink className="h-3.5 w-3.5" />
      <span>个股日记</span>
    </button>
  );
}
