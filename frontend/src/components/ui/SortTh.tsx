import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type SortOrder = "asc" | "desc";

/** 表头排序图标：未激活为双箭头，激活后替换为单方向箭头并用主题色高亮 */
export function SortIcon({
  active,
  order,
  className,
}: {
  active: boolean;
  order?: SortOrder;
  className?: string;
}) {
  const cls = cn("h-3 w-3 shrink-0", className);
  if (!active) {
    return <ArrowUpDown className={cn(cls, "opacity-50")} />;
  }
  const Icon = order === "desc" ? ArrowDown : ArrowUp;
  return <Icon className={cn(cls, "text-primary")} />;
}

export function SortTh<T extends string = string>({
  col,
  label,
  sortCol,
  order,
  onSort,
  sortable = true,
  hint,
  className,
  labelClassName,
}: {
  col: T;
  label: string;
  sortCol: T;
  order: SortOrder;
  onSort?: (col: T) => void;
  sortable?: boolean;
  hint?: string;
  className?: string;
  labelClassName?: string;
}) {
  const active = sortCol === col;

  if (!sortable || !onSort) {
    return (
      <th className={className} title={hint}>
        <span className={cn("text-muted-foreground", labelClassName)}>{label}</span>
      </th>
    );
  }

  return (
    <th className={className}>
      <button
        type="button"
        title={hint}
        className={cn(
          "inline-flex items-center gap-0.5 transition-colors",
          active ? "text-primary" : "text-muted-foreground hover:text-foreground",
          labelClassName,
        )}
        onClick={() => onSort(col)}
      >
        {label}
        <SortIcon active={active} order={order} />
      </button>
    </th>
  );
}
