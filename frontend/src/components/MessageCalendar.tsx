import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AnalyzedMessage } from "@/lib/api";
import {
  IMPACT_EVENT_BG,
  IMPACT_LABEL,
  dateKeyFromEffective,
  effectiveAt,
  impactSortKey,
} from "@/lib/messages";

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];
const WEEKDAY_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
const MAX_VISIBLE = 4;
const POPOVER_WIDTH = 288;
const POPOVER_PAD = 8;
const POPOVER_GAP = 6;
const POPOVER_MAX_HEIGHT = 420;
const POPOVER_MIN_HEIGHT = 160;

export interface CalendarCell {
  date: Date;
  inMonth: boolean;
  isToday: boolean;
  key: string;
  items: AnalyzedMessage[];
}

function padDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
  );
}

function buildMonthGrid(year: number, month: number, items: AnalyzedMessage[]): CalendarCell[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const byDay = new Map<string, AnalyzedMessage[]>();
  for (const item of items) {
    const key = dateKeyFromEffective(item);
    const list = byDay.get(key);
    if (list) list.push(item);
    else byDay.set(key, [item]);
  }
  for (const list of byDay.values()) {
    list.sort((a, b) => {
      const ia = impactSortKey(a.impact_level);
      const ib = impactSortKey(b.impact_level);
      if (ia !== ib) return ia - ib;
      return effectiveAt(b).localeCompare(effectiveAt(a));
    });
  }

  const first = new Date(year, month, 1);
  const startOffset = first.getDay();
  const gridStart = new Date(year, month, 1 - startOffset);

  const cells: CalendarCell[] = [];
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + i);
    date.setHours(0, 0, 0, 0);
    const key = padDate(date);
    cells.push({
      date,
      inMonth: date.getMonth() === month,
      isToday: isSameDay(date, today),
      key,
      items: byDay.get(key) ?? [],
    });
  }
  return cells;
}

function EventChip({
  item,
  selected,
  onSelect,
  className,
}: {
  item: AnalyzedMessage;
  selected?: boolean;
  onSelect: (item: AnalyzedMessage) => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={`${IMPACT_LABEL[item.impact_level] || item.impact_level} · ${item.title || item.summary}`}
      className={cn(
        "w-full truncate rounded px-1.5 py-1 text-left text-[11px] font-medium leading-tight transition-opacity hover:opacity-90",
        IMPACT_EVENT_BG[item.impact_level] || IMPACT_EVENT_BG.medium,
        selected && "ring-2 ring-foreground/40 ring-offset-1",
        className,
      )}
      onClick={() => onSelect(item)}
    >
      {item.title || item.summary || "—"}
    </button>
  );
}

/** 按视口边缘碰撞调整位置（类似谷歌日历「更多」弹层：贴右向左、贴底向上） */
function clampPopoverPosition(
  anchor: DOMRect,
  width: number,
  measuredHeight: number,
): { top: number; left: number; maxHeight: number } {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = POPOVER_PAD;

  // 水平：优先左对齐锚点；右侧溢出则改为右对齐锚点，再钳到视口内
  let left = anchor.left;
  if (left + width > vw - pad) {
    left = anchor.right - width;
  }
  left = Math.max(pad, Math.min(left, vw - width - pad));

  const spaceBelow = Math.max(0, vh - anchor.bottom - pad - POPOVER_GAP);
  const spaceAbove = Math.max(0, anchor.top - pad - POPOVER_GAP);
  const openUp = spaceBelow < POPOVER_MIN_HEIGHT && spaceAbove > spaceBelow;
  const available = openUp ? spaceAbove : spaceBelow;

  let maxHeight = Math.min(POPOVER_MAX_HEIGHT, available);
  if (measuredHeight > 0) {
    maxHeight = Math.min(maxHeight, measuredHeight);
  }
  // 尽量不低于舒适高度，但绝不超出可用空间
  maxHeight = Math.max(maxHeight, Math.min(96, available));

  let top = openUp
    ? anchor.top - maxHeight - POPOVER_GAP
    : anchor.bottom + POPOVER_GAP;
  top = Math.max(pad, Math.min(top, vh - Math.max(maxHeight, 1) - pad));
  maxHeight = Math.max(0, Math.min(maxHeight, vh - top - pad));

  return { top, left, maxHeight };
}

function DayOverflowPopover({
  cell,
  selectedId,
  anchorRect,
  onClose,
  onSelect,
}: {
  cell: CalendarCell;
  selectedId?: string | null;
  anchorRect: DOMRect;
  onClose: () => void;
  onSelect: (item: AnalyzedMessage) => void;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const weekday = WEEKDAY_LABELS[cell.date.getDay()];
  const [pos, setPos] = useState(() =>
    clampPopoverPosition(anchorRect, POPOVER_WIDTH, 0),
  );

  useLayoutEffect(() => {
    const el = popoverRef.current;
    if (!el) return;
    const width = el.offsetWidth || POPOVER_WIDTH;
    // 先按视口可用空间设上限，再按实际渲染高度收紧（短列表 / 向上展开贴锚点）
    const capped = clampPopoverPosition(anchorRect, width, 0);
    el.style.maxHeight = `${capped.maxHeight}px`;
    const actual = el.offsetHeight;
    setPos(clampPopoverPosition(anchorRect, width, actual));
  }, [anchorRect, cell.key, cell.items.length]);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (popoverRef.current?.contains(e.target as Node)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    // 日历在可滚动容器内，滚动后锚点错位，直接关闭（与谷歌日历一致）
    const onScroll = (e: Event) => {
      const t = e.target;
      if (t instanceof Node && popoverRef.current?.contains(t)) return;
      onClose();
    };
    const onResize = () => onClose();
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={popoverRef}
      className="fixed z-[90] flex w-72 flex-col overflow-hidden rounded-xl border border-border bg-background shadow-xl"
      style={{ top: pos.top, left: pos.left, width: POPOVER_WIDTH, maxHeight: pos.maxHeight }}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-border/60 px-3 py-2">
        <div className="text-sm font-semibold text-foreground">
          <span className="text-muted-foreground">{weekday}</span>
          {" · "}
          {cell.date.getDate()} 日
          <span className="ml-1.5 text-xs font-normal text-muted-foreground">
            共 {cell.items.length} 项
          </span>
        </div>
        <button
          type="button"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          onClick={onClose}
          aria-label="关闭"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-auto p-2">
        {cell.items.map((item) => (
          <EventChip
            key={item.id}
            item={item}
            selected={selectedId === item.id}
            onSelect={(it) => {
              onSelect(it);
              onClose();
            }}
          />
        ))}
      </div>
    </div>,
    document.body,
  );
}

export function MessageCalendar({
  year,
  month,
  items,
  loading,
  selectedId,
  onMonthChange,
  onSelect,
}: {
  year: number;
  month: number;
  items: AnalyzedMessage[];
  loading?: boolean;
  selectedId?: string | null;
  onMonthChange: (year: number, month: number) => void;
  onSelect: (item: AnalyzedMessage) => void;
}) {
  const [expandedCell, setExpandedCell] = useState<CalendarCell | null>(null);
  const [popoverRect, setPopoverRect] = useState<DOMRect | null>(null);

  const cells = useMemo(
    () => buildMonthGrid(year, month, items),
    [year, month, items],
  );

  const closePopover = () => {
    setExpandedCell(null);
    setPopoverRect(null);
  };

  useEffect(() => {
    setExpandedCell(null);
    setPopoverRect(null);
  }, [year, month]);

  const monthLabel = `${year}年${month + 1}月`;

  const goToday = () => {
    const now = new Date();
    onMonthChange(now.getFullYear(), now.getMonth());
  };

  const goPrev = () => {
    if (month === 0) onMonthChange(year - 1, 11);
    else onMonthChange(year, month - 1);
  };

  const goNext = () => {
    if (month === 11) onMonthChange(year + 1, 0);
    else onMonthChange(year, month + 1);
  };

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={goToday}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-semibold text-foreground transition-opacity hover:bg-muted/50"
          >
            今天
          </button>
          <button
            type="button"
            onClick={goPrev}
            className="rounded-lg border border-border bg-background p-1.5 text-foreground transition-opacity hover:bg-muted/50"
            aria-label="上一月"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={goNext}
            className="rounded-lg border border-border bg-background p-1.5 text-foreground transition-opacity hover:bg-muted/50"
            aria-label="下一月"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <span className="ml-2 text-base font-bold tabular-nums text-foreground">{monthLabel}</span>
          {loading && <Loader2 className="ml-2 h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          {Object.entries(IMPACT_LABEL).map(([k, label]) => (
            <span key={k} className="inline-flex items-center gap-1">
              <span
                className={cn("inline-block h-2.5 w-2.5 rounded-sm", IMPACT_EVENT_BG[k]?.split(" ")[0])}
              />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-border/60">
        <div className="grid grid-cols-7 border-b border-border/60 bg-muted/40">
          {WEEKDAYS.map((w) => (
            <div
              key={w}
              className="border-r border-border/40 px-2 py-2 text-center text-xs font-semibold text-muted-foreground last:border-r-0"
            >
              {w}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((cell) => {
            const visible = cell.items.slice(0, MAX_VISIBLE);
            const overflow = cell.items.length - visible.length;
            return (
              <div
                key={cell.key}
                data-cal-cell
                className={cn(
                  "flex min-h-[108px] flex-col border-b border-r border-border/40 p-1 last:border-r-0",
                  !cell.inMonth && "bg-muted/15",
                  cell.isToday && "bg-primary/5",
                )}
              >
                <div className="mb-0.5 flex items-center justify-between px-0.5">
                  <span
                    className={cn(
                      "inline-flex h-6 min-w-[1.5rem] items-center justify-center rounded-full px-1 text-xs font-semibold tabular-nums",
                      cell.isToday && "bg-primary text-primary-foreground",
                      !cell.inMonth && !cell.isToday && "text-muted-foreground/60",
                      cell.inMonth && !cell.isToday && "text-foreground",
                    )}
                  >
                    {cell.date.getDate()}
                  </span>
                  {cell.items.length > 0 && (
                    <span className="text-[10px] tabular-nums text-muted-foreground">
                      {cell.items.length}
                    </span>
                  )}
                </div>
                <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-hidden">
                  {visible.map((item) => (
                    <EventChip
                      key={item.id}
                      item={item}
                      selected={selectedId === item.id}
                      onSelect={onSelect}
                    />
                  ))}
                  {overflow > 0 && (
                    <button
                      type="button"
                      className="px-1 text-left text-[10px] text-primary hover:underline"
                      onClick={(e) => {
                        // 以日期格为锚点（类似谷歌日历），贴右列时弹层可向左翻入视口
                        const cellEl = e.currentTarget.closest("[data-cal-cell]");
                        const rect = (cellEl ?? e.currentTarget).getBoundingClientRect();
                        setExpandedCell(cell);
                        setPopoverRect(rect);
                      }}
                    >
                      另外 {overflow} 项
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      {expandedCell && popoverRect && (
        <DayOverflowPopover
          cell={expandedCell}
          selectedId={selectedId}
          anchorRect={popoverRect}
          onClose={closePopover}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}
