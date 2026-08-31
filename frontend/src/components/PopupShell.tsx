import { useEffect, type ReactNode } from "react";
import { attachPopupGeometryPersistence } from "@/lib/sectionPopup";
import { cn } from "@/lib/utils";
import { useDarkMode } from "@/hooks/useDarkMode";

/** 独立弹窗页外壳：主题同步、文档标题、记住窗口大小（无应用内标题栏） */
export function PopupShell({
  title,
  children,
  className,
  bodyClassName,
}: {
  title: string;
  /** 保留调用方兼容；不再渲染应用内标题栏 */
  subtitle?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  useDarkMode();

  useEffect(() => {
    document.title = title;
  }, [title]);

  useEffect(() => attachPopupGeometryPersistence(), []);

  return (
    <div className={cn("flex h-screen flex-col bg-background text-foreground", className)}>
      <div className={cn("min-h-0 flex-1 overflow-auto p-3", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
