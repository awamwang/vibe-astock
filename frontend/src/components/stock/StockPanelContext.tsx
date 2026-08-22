import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { StockDataPanel } from "./StockDataPanel";
import { DebatePanel } from "./DebatePanel";
import { X, Database, Swords } from "lucide-react";
import { cn } from "@/lib/utils";

export type StockPanelMode = "data" | "debate";

export interface StockPanelTarget {
  code: string;
  name?: string;
  mode: StockPanelMode;
}

interface StockPanelApi {
  open: (target: StockPanelTarget) => void;
  openData: (code: string, name?: string) => void;
  openDebate: (code: string, name?: string) => void;
  close: () => void;
  target: StockPanelTarget | null;
}

const Ctx = createContext<StockPanelApi | null>(null);

export function useStockPanel(): StockPanelApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStockPanel 必须在 StockPanelProvider 内使用");
  return v;
}

/** 可选：在无 Provider 时返回 null（例如单元测试） */
export function useStockPanelOptional(): StockPanelApi | null {
  return useContext(Ctx);
}

export function StockPanelProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<StockPanelTarget | null>(null);

  const open = useCallback((t: StockPanelTarget) => {
    const code = (t.code || "").trim();
    if (!code) return;
    setTarget({ ...t, code });
  }, []);

  const openData = useCallback((code: string, name?: string) => {
    open({ code, name, mode: "data" });
  }, [open]);

  const openDebate = useCallback((code: string, name?: string) => {
    const c = code.trim();
    if (!/^\d{6}$/.test(c)) return; // 辩论仅支持 A 股 6 位
    open({ code: c, name, mode: "debate" });
  }, [open]);

  const close = useCallback(() => setTarget(null), []);

  const api = useMemo(
    () => ({ open, openData, openDebate, close, target }),
    [open, openData, openDebate, close, target],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
    </Ctx.Provider>
  );
}

/** 右侧推拉面板：宽度与主内容区 max-w-6xl 对齐，向左挤压原页面 */
export function StockPanelHost() {
  const { target, close, openData, openDebate } = useStockPanel();
  if (!target) return null;

  const title = target.name
    ? `${target.name}（${target.code}）`
    : target.code;

  return (
    <aside
      className={cn(
        "glass relative m-2 ml-0 flex h-[calc(100%-1rem)] w-full max-w-6xl shrink-0 flex-col overflow-hidden rounded-2xl",
      )}
      aria-label="个股面板"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-border/60 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{title}</p>
          <div className="mt-1.5 flex gap-1">
            <button
              type="button"
              onClick={() => openData(target.code, target.name)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px]",
                target.mode === "data"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <Database className="h-3 w-3" /> 个股数据
            </button>
            <button
              type="button"
              onClick={() => openDebate(target.code, target.name)}
              disabled={!/^\d{6}$/.test(target.code)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] disabled:opacity-40",
                target.mode === "debate"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <Swords className="h-3 w-3" /> 多空辩论
            </button>
          </div>
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
        {target.mode === "data" ? (
          <StockDataPanel code={target.code} name={target.name} />
        ) : (
          <DebatePanel code={target.code} name={target.name} />
        )}
      </div>
    </aside>
  );
}
