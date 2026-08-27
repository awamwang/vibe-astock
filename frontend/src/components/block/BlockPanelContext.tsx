import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { BlockDetailPanel } from "./BlockDetailPanel";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ThsBlockRef } from "@/lib/api";

export interface BlockPanelTarget {
  kind: string;
  id: string;
  name: string;
  kind_label?: string;
}

interface BlockPanelApi {
  open: (target: BlockPanelTarget) => void;
  openRef: (ref: ThsBlockRef) => void;
  close: () => void;
  target: BlockPanelTarget | null;
}

const Ctx = createContext<BlockPanelApi | null>(null);

export function useBlockPanel(): BlockPanelApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBlockPanel 必须在 BlockPanelProvider 内使用");
  return v;
}

export function useBlockPanelOptional(): BlockPanelApi | null {
  return useContext(Ctx);
}

export function BlockPanelProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<BlockPanelTarget | null>(null);

  const open = useCallback((t: BlockPanelTarget) => {
    const kind = (t.kind || "").trim();
    const id = (t.id || "").trim();
    if (!kind || !id) return;
    setTarget({
      kind,
      id,
      name: (t.name || id).trim(),
      kind_label: t.kind_label,
    });
  }, []);

  const openRef = useCallback((ref: ThsBlockRef) => {
    open({
      kind: ref.kind,
      id: ref.id,
      name: ref.name,
      kind_label: ref.kind_label,
    });
  }, [open]);

  const close = useCallback(() => setTarget(null), []);

  const api = useMemo(
    () => ({ open, openRef, close, target }),
    [open, openRef, close, target],
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

/** 右侧推拉面板：展示同花顺板块详情与成分股 */
export function BlockPanelHost() {
  const { target, close } = useBlockPanel();
  if (!target) return null;

  const title = target.name
    ? `${target.name}${target.kind_label ? ` · ${target.kind_label}` : ""}`
    : target.id;

  return (
    <aside
      className={cn(
        "glass relative m-2 ml-0 flex h-[calc(100%-1rem)] w-full max-w-6xl shrink-0 flex-col overflow-hidden rounded-2xl",
      )}
      aria-label="板块面板"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{title}</p>
          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{target.id}</p>
        </div>
        <button
          type="button"
          onClick={close}
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          title="关闭"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        <BlockDetailPanel kind={target.kind} blockId={target.id} name={target.name} />
      </div>
    </aside>
  );
}
