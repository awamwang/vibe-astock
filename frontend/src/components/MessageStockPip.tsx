import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ExternalLink, Loader2, PictureInPicture2, X } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, type AnalyzedMessage } from "@/lib/api";
import { getDefaultEndDays, IMPACT_LABEL, targetTitle } from "@/lib/messages";
import { usePluginCurrentStock } from "@/lib/currentStockStream";
import { openSectionPopup, appUrl } from "@/lib/sectionPopup";
import { StockResolveScope, useStockResolve } from "@/components/stock/StockResolveContext";
import { cn } from "@/lib/utils";

const LIST_LIMIT = 80;
const REFRESH_MS = 15_000;
export const MESSAGE_STOCK_POPUP_NAME = "va-message-stock-popup";
export const MESSAGE_STOCK_POPUP_PATH = "/messages/pip";

const IMPACT_BADGE: Record<string, string> = {
  critical: "bg-danger/15 text-danger border-danger/30",
  high: "bg-primary/15 text-primary border-primary/30",
  medium: "bg-muted text-foreground border-border",
  low: "bg-muted/60 text-muted-foreground border-border/60",
  noise: "bg-muted/40 text-muted-foreground border-border/40",
};

const IMPACT_TITLE: Record<string, string> = {
  critical: "text-danger",
  high: "text-primary",
};

declare global {
  interface DocumentPictureInPictureOptions {
    width?: number;
    height?: number;
    disallowReturnToOpener?: boolean;
  }

  interface DocumentPictureInPicture {
    requestWindow(options?: DocumentPictureInPictureOptions): Promise<Window>;
    readonly window: Window | null;
  }

  interface Window {
    documentPictureInPicture?: DocumentPictureInPicture;
  }
}

export function isDocumentPipSupported(): boolean {
  return typeof window !== "undefined" && !!window.documentPictureInPicture;
}

/** 弹窗页完整 URL（含 basename） */
export function messageStockPopupUrl(): string {
  return appUrl(MESSAGE_STOCK_POPUP_PATH);
}

/** 把主文档样式复制到 PiP 窗口，保证 Tailwind / 主题变量生效 */
function copyStylesToPip(pipWindow: Window) {
  const pipHead = pipWindow.document.head;
  pipWindow.document.documentElement.className = document.documentElement.className;
  pipWindow.document.documentElement.lang = document.documentElement.lang || "zh-CN";

  for (const node of Array.from(document.querySelectorAll('link[rel="stylesheet"], style'))) {
    pipHead.appendChild(node.cloneNode(true));
  }

  const body = pipWindow.document.body;
  body.className = document.body.className;
  body.style.margin = "0";
  body.style.minHeight = "100%";
  body.style.backgroundColor = getComputedStyle(document.body).backgroundColor;
  body.style.color = getComputedStyle(document.body).color;
}

function PipTargets({
  targets,
  stockHitBlockNames,
}: {
  targets: AnalyzedMessage["targets"];
  stockHitBlockNames?: string[];
}) {
  if (!targets.length) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {targets.map((t, i) => {
        const blockName = (t.name || "").replace(/\s+/g, "").trim();
        const isStockHitBlock =
          (t.kind === "sector" || t.kind === "theme") &&
          !!blockName &&
          (stockHitBlockNames?.some((n) => (n || "").replace(/\s+/g, "").trim() === blockName) ?? false);
        return (
          <span
            key={`${t.kind}-${t.name}-${t.code ?? ""}-${i}`}
            className={cn(
              "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
              t.kind === "stock"
                ? "border-sky-500/30 bg-sky-500/10 text-foreground"
                : "border-amber-500/30 bg-amber-500/10 text-foreground",
              isStockHitBlock && "ring-2 ring-danger/70 border-danger/60",
            )}
            title={targetTitle(t)}
          >
            {t.name || t.code || "—"}
          </span>
        );
      })}
    </div>
  );
}

function StockCodeHint({
  code,
  status,
  error,
}: {
  code: string | null;
  status: string;
  error: string | null;
}) {
  const resolved = useStockResolve({ code });
  const name = resolved?.stock?.name?.trim() || "";
  if (code) {
    return <>{name ? `${name}（${code}）` : code}</>;
  }
  if (status === "connecting") return <>连接中…</>;
  if (status === "connected") return <>等待焦点股…</>;
  if (status === "error") return <>{error || "未连接"}</>;
  return <>等待插件…</>;
}

/** 焦点股消息列表（PiP / 独立窗口共用） */
export function MessageStockLinkPanel({
  items,
  loading,
  code,
  status,
  error,
  total,
  onClose,
  title = "消息联动",
}: {
  items: AnalyzedMessage[];
  loading: boolean;
  code: string | null;
  status: string;
  error: string | null;
  total: number;
  onClose?: () => void;
  title?: string;
}) {
  const listScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listScrollRef.current?.scrollTo({ top: 0 });
  }, [code]);

  const body = (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
        <PictureInPicture2 className="h-3.5 w-3.5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-semibold text-foreground">{title}</p>
          <p className="truncate text-[11px] tabular-nums text-muted-foreground">
            <StockCodeHint code={code} status={status} error={error} />
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

      <div ref={listScrollRef} className="min-h-0 flex-1 overflow-auto">
        {!code && (
          <p className="p-4 text-center text-xs text-muted-foreground">
            请在同花顺中切换股票；需启用 vibe-ths-linker
          </p>
        )}
        {code && items.length === 0 && !loading && (
          <p className="p-4 text-center text-xs text-muted-foreground">暂无与当前股票相关的消息</p>
        )}
        {code && items.length > 0 && (
          <ul className="divide-y divide-border/40">
            {items.map((item) => (
              <li key={item.id} className="space-y-1.5 px-3 py-2.5">
                <div className="flex items-start gap-2">
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold",
                      IMPACT_BADGE[item.impact_level] || IMPACT_BADGE.medium,
                    )}
                  >
                    {IMPACT_LABEL[item.impact_level] || item.impact_level}
                  </span>
                  <p
                    className={cn(
                      "min-w-0 flex-1 text-xs font-semibold leading-snug",
                      IMPACT_TITLE[item.impact_level] || "text-foreground",
                    )}
                  >
                    {item.title || "—"}
                  </p>
                </div>
                <PipTargets
                  targets={item.targets}
                  stockHitBlockNames={item.matched_current_stock_blocks}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );

  return (
    <StockResolveScope queries={code ? [{ code }] : []}>
      {body}
    </StockResolveScope>
  );
}

/** 订阅焦点股并拉取按股票过滤的消息列表 */
export function useMessageStockLinkList(enabled: boolean, defaultEndDays?: number) {
  const [items, setItems] = useState<AnalyzedMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const { code, status, error } = usePluginCurrentStock(enabled);
  const days = defaultEndDays ?? getDefaultEndDays();

  const loadList = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const data = await api.messageAnalyzedList({
        match_current_stock: "yes",
        default_end_days: days,
        sort: "produced_at",
        order: "desc",
        limit: LIST_LIMIT,
        offset: 0,
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "联动消息加载失败", {
        position: "top-center",
        duration: 4000,
      });
    } finally {
      setLoading(false);
    }
  }, [enabled, days, code]);

  useEffect(() => {
    if (!enabled) {
      setItems([]);
      setTotal(0);
      return;
    }
    void loadList();
  }, [enabled, loadList]);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      void loadList();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [enabled, loadList]);

  return { items, total, loading, code, status, error, reload: loadList };
}

/** Document Picture-in-Picture 联动弹窗（依赖父页） */
export function MessageStockPipButton({ defaultEndDays }: { defaultEndDays: number }) {
  const [pipWindow, setPipWindow] = useState<Window | null>(null);
  const [portalEl, setPortalEl] = useState<HTMLElement | null>(null);
  const pipActive = !!pipWindow;
  const { items, total, loading, code, status, error } = useMessageStockLinkList(pipActive, defaultEndDays);
  const openingRef = useRef(false);
  const pipWindowRef = useRef<Window | null>(null);

  const closePip = useCallback(() => {
    const w = pipWindowRef.current;
    pipWindowRef.current = null;
    setPipWindow(null);
    setPortalEl(null);
    try {
      w?.close();
    } catch {
      /* 已关闭 */
    }
  }, []);

  useEffect(() => {
    if (!pipWindow) return;
    const onPageHide = () => {
      if (pipWindowRef.current === pipWindow) pipWindowRef.current = null;
      setPipWindow(null);
      setPortalEl(null);
    };
    pipWindow.addEventListener("pagehide", onPageHide);
    return () => pipWindow.removeEventListener("pagehide", onPageHide);
  }, [pipWindow]);

  const openPip = async () => {
    if (openingRef.current) return;
    const existing = pipWindowRef.current;
    if (existing && !existing.closed) {
      existing.focus();
      return;
    }
    if (!isDocumentPipSupported()) {
      toast.error("当前浏览器不支持 Document Picture-in-Picture（请用 Chrome / Edge 116+）", {
        position: "top-center",
        duration: 5000,
      });
      return;
    }
    openingRef.current = true;
    try {
      const w = await window.documentPictureInPicture!.requestWindow({
        width: 400,
        height: 560,
      });
      copyStylesToPip(w);
      const root = w.document.createElement("div");
      root.id = "message-stock-pip-root";
      root.style.height = "100%";
      w.document.body.appendChild(root);
      pipWindowRef.current = w;
      setPipWindow(w);
      setPortalEl(root);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "无法打开联动弹窗", {
        position: "top-center",
        duration: 5000,
      });
    } finally {
      openingRef.current = false;
    }
  };

  return (
    <>
      <button
        type="button"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors",
          pipActive
            ? "border-primary/50 bg-primary/10 text-primary"
            : "border-border bg-background text-muted-foreground hover:text-foreground",
        )}
        title="打开 Picture-in-Picture 窗口（依赖本页未关闭），仅展示与插件焦点股相关的消息"
        onClick={() => {
          if (pipActive) closePip();
          else void openPip();
        }}
      >
        <PictureInPicture2 className="h-3.5 w-3.5" />
        <span>PiP 弹窗</span>
      </button>
      {pipWindow && portalEl &&
        createPortal(
          <MessageStockLinkPanel
            items={items}
            loading={loading}
            code={code}
            status={status}
            error={error}
            total={total}
            onClose={closePip}
            title="消息联动 · PiP"
          />,
          portalEl,
        )}
    </>
  );
}

/** 独立路由弹窗：window.open('/messages/pip')，不依赖父页 */
export function MessageStockPopupButton() {
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
    const w = openSectionPopup(MESSAGE_STOCK_POPUP_PATH, MESSAGE_STOCK_POPUP_NAME, [
      "popup=yes",
      "width=420",
      "height=640",
      "left=80",
      "top=80",
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
      title={`独立窗口 ${MESSAGE_STOCK_POPUP_PATH}，关闭消息分析页后仍可继续使用`}
      onClick={() => {
        if (active) closePopup();
        else openPopup();
      }}
    >
      <ExternalLink className="h-3.5 w-3.5" />
      <span>独立弹窗</span>
    </button>
  );
}
