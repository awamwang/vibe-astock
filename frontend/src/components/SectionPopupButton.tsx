import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import { openSectionPopup } from "@/lib/sectionPopup";
import { cn } from "@/lib/utils";

/** 打开独立路由弹窗的按钮（不依赖父页） */
export function SectionPopupButton({
  path,
  windowName,
  label = "独立弹窗",
  title,
  className,
  compact,
  features,
}: {
  path: string;
  windowName: string;
  label?: string;
  title?: string;
  className?: string;
  /** 仅图标，适合塞进标题行 */
  compact?: boolean;
  features?: string;
}) {
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

  const toggle = () => {
    if (active && popupRef.current && !popupRef.current.closed) {
      try {
        popupRef.current.close();
      } catch {
        /* ignore */
      }
      popupRef.current = null;
      setActive(false);
      return;
    }
    const w = openSectionPopup(path, windowName, features);
    if (w) {
      popupRef.current = w;
      setActive(true);
    }
  };

  return (
    <button
      type="button"
      className={cn(
        compact
          ? "rounded p-1 text-muted-foreground transition-colors hover:text-primary"
          : "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors",
        !compact && (active
          ? "border-primary/50 bg-primary/10 text-primary"
          : "border-border bg-background text-muted-foreground hover:text-foreground"),
        compact && active && "text-primary",
        className,
      )}
      title={title || `独立窗口打开：${path}`}
      onClick={(e) => {
        e.stopPropagation();
        toggle();
      }}
    >
      <ExternalLink className={compact ? "h-3.5 w-3.5" : "h-3 w-3"} />
      {!compact && <span>{label}</span>}
    </button>
  );
}
