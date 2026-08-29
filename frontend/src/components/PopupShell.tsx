import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";

/** 独立弹窗页外壳：主题同步、标题栏、可关闭 */
export function PopupShell({
  title,
  subtitle,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  useDarkMode();

  useEffect(() => {
    document.title = title;
  }, [title]);

  return (
    <div className={cn("flex h-screen flex-col bg-background text-foreground", className)}>
      <header className="flex shrink-0 items-center gap-2 border-b border-border/60 px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-foreground">{title}</p>
          {subtitle && (
            <div className="truncate text-[11px] text-muted-foreground">{subtitle}</div>
          )}
        </div>
        <button
          type="button"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted/50 hover:text-foreground"
          title="关闭"
          onClick={() => {
            try {
              window.close();
            } catch {
              /* 非脚本打开的窗口可能关不掉 */
            }
          }}
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className={cn("min-h-0 flex-1 overflow-auto p-3", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
