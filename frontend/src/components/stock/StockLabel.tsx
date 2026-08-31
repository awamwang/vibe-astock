import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Database, Swords } from "lucide-react";
import { cn } from "@/lib/utils";
import { stockMatchedClass, isStockMatched } from "@/lib/stocks";
import { useStockPanelOptional } from "./StockPanelContext";
import { useStockResolve, useStockResolveOptional } from "./StockResolveContext";
import type { StockResolveItem } from "@/lib/api";

interface Props {
  code: string;
  name?: string | null;
  /** 若上层已解析可直传，否则从 StockResolveScope 读取 */
  resolved?: StockResolveItem | null;
  /** inline = 名称+代码同行；nameOnly / codeOnly = 仅展示一侧但仍可右键 */
  variant?: "inline" | "nameOnly" | "codeOnly";
  className?: string;
  nameClassName?: string;
  codeClassName?: string;
  children?: ReactNode;
}

interface MenuState {
  x: number;
  y: number;
}

/**
 * 统一股票名称/代码展示，右键打开「个股数据 / 多空辩论」菜单。
 */
export function StockLabel({
  code,
  name,
  resolved: resolvedProp,
  variant = "inline",
  className,
  nameClassName,
  codeClassName,
  children,
}: Props) {
  const panel = useStockPanelOptional();
  const fromCtx = useStockResolve({ code, name });
  const hasScope = !!useStockResolveOptional();
  const resolved = resolvedProp ?? fromCtx;
  const matched = isStockMatched(resolved);
  const stock = matched ? resolved!.stock! : null;
  const displayCode = stock?.code || (code || "").trim();
  const displayName = stock?.name || (name || "").trim();
  const canOpen = !!panel && !!displayCode;

  const [menu, setMenu] = useState<MenuState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const canDebate = /^\d{6}$/.test(displayCode);

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

  const body = children ?? (
    variant === "codeOnly" ? (
      <span className={cn("font-mono text-xs text-muted-foreground", codeClassName)}>{displayCode}</span>
    ) : variant === "nameOnly" ? (
      <span className={cn("font-medium", nameClassName)}>{displayName || "—"}</span>
    ) : (
      <>
        <span className={cn("font-medium", nameClassName)}>{displayName || "—"}</span>{" "}
        <span className={cn("text-xs text-muted-foreground/50", codeClassName)}>{displayCode}</span>
      </>
    )
  );

  const title = canOpen
    ? matched
      ? `已映射 A 股 ${displayCode} · 右键查看详情`
      : "右键：个股数据 / 多空辩论"
    : hasScope && resolved?.status === "unmatched"
      ? "未映射到 A 股列表"
      : undefined;

  return (
    <>
      <span
        onContextMenu={onContextMenu}
        data-stock-code={matched ? displayCode : undefined}
        className={cn(
          canOpen && "cursor-context-menu",
          matched && stockMatchedClass(true),
          className,
        )}
        title={title}
      >
        {body}
      </span>
      {menu && panel && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[80] min-w-[10.5rem] overflow-hidden rounded-lg border border-border bg-card py-1 text-sm text-foreground shadow-lg"
          style={{
            left: Math.min(menu.x, window.innerWidth - 180),
            top: Math.min(menu.y, window.innerHeight - 100),
          }}
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/60"
            onClick={() => { panel.openData(displayCode, displayName || undefined); setMenu(null); }}
          >
            <Database className="h-3.5 w-3.5 text-primary" /> 查看个股数据
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={!canDebate}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/60 disabled:opacity-40"
            onClick={() => { if (canDebate) { panel.openDebate(displayCode, displayName || undefined); setMenu(null); } }}
          >
            <Swords className="h-3.5 w-3.5 text-primary" /> 多空辩论
            {!canDebate && <span className="ml-auto text-[10px] text-muted-foreground">仅 A 股</span>}
          </button>
        </div>,
        document.body,
      )}
    </>
  );
}
