import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Boxes } from "lucide-react";
import { cn } from "@/lib/utils";
import { blockMatchedClass, isBlockMatched } from "@/lib/thsBlocks";
import { useBlockPanelOptional } from "./BlockPanelContext";
import { useBlockResolve, useBlockResolveOptional } from "./BlockResolveContext";
import type { BlockResolveItem } from "@/lib/api";

interface Props {
  name: string;
  /** 若上层已解析可直传，否则从 BlockResolveScope 读取 */
  resolved?: BlockResolveItem | null;
  variant?: "text" | "tag" | "chip";
  className?: string;
  children?: ReactNode;
}

/**
 * 板块名称展示：映射成功时高亮，右键在右侧栏打开板块详情。
 */
export function BlockLabel({
  name,
  resolved: resolvedProp,
  variant = "text",
  className,
  children,
}: Props) {
  const panel = useBlockPanelOptional();
  const fromCtx = useBlockResolve(name);
  const hasScope = !!useBlockResolveOptional();
  const resolved = resolvedProp ?? fromCtx;
  const matched = isBlockMatched(resolved);
  const block = matched ? resolved!.block! : null;

  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const n = (name || "").trim();
  const canOpen = !!panel && !!block;

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    const onDown = (e: Event) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) close();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", close, true);
    };
  }, [menu]);

  const onContextMenu = (e: MouseEvent) => {
    if (!canOpen) return;
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY });
  };

  const baseVariant = variant === "tag"
    ? "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px]"
    : variant === "chip"
      ? "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs"
      : "inline";

  const body = children ?? (
    <span className={variant === "text" ? undefined : "truncate"}>{n || "—"}</span>
  );

  const title = canOpen
    ? `已映射同花顺${block?.kind_label || "板块"} · 右键查看详情`
    : hasScope && resolved?.status === "unmatched"
      ? "未映射到同花顺板块"
      : undefined;

  return (
    <>
      <span
        onContextMenu={onContextMenu}
        className={cn(
          baseVariant,
          canOpen && "cursor-context-menu",
          matched && blockMatchedClass(true),
          !matched && variant !== "text" && "border-border/50 bg-muted/20 text-foreground",
          className,
        )}
        title={title}
      >
        {body}
      </span>
      {menu && panel && block && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[80] min-w-[10.5rem] overflow-hidden rounded-lg border border-border bg-card py-1 text-sm text-foreground shadow-lg"
          style={{
            left: Math.min(menu.x, window.innerWidth - 180),
            top: Math.min(menu.y, window.innerHeight - 80),
          }}
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/60"
            onClick={() => { panel.openRef(block); setMenu(null); }}
          >
            <Boxes className="h-3.5 w-3.5 text-primary" /> 查看板块详情
          </button>
        </div>,
        document.body,
      )}
    </>
  );
}
