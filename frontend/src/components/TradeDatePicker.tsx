import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

/** YYYY-MM-DD 是否为周末（非交易日廉价判据，与后端 is_weekend 同口径） */
export function isWeekendDate(iso: string): boolean {
  if (!iso || iso.length < 10) return false;
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return false;
  const w = d.getDay();
  return w === 0 || w === 6;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function toIso(y: number, m: number, day: number): string {
  return `${y}-${pad(m + 1)}-${pad(day)}`;
}

function parseIso(iso: string): { y: number; m: number; d: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]) - 1, d: Number(m[3]) };
}

interface Cell {
  iso: string;
  day: number;
  inMonth: boolean;
  weekend: boolean;
  future: boolean;
  selectable: boolean;
}

function buildGrid(year: number, month: number, maxIso: string): Cell[] {
  const first = new Date(year, month, 1);
  // 周一为一周起点：周日 getDay=0 → 偏移 6
  const mondayOffset = (first.getDay() + 6) % 7;
  const gridStart = new Date(year, month, 1 - mondayOffset);
  const cells: Cell[] = [];
  for (let i = 0; i < 42; i += 1) {
    const dt = new Date(gridStart);
    dt.setDate(gridStart.getDate() + i);
    const y = dt.getFullYear();
    const m = dt.getMonth();
    const day = dt.getDate();
    const iso = toIso(y, m, day);
    const weekend = dt.getDay() === 0 || dt.getDay() === 6;
    const future = iso > maxIso;
    cells.push({
      iso,
      day,
      inMonth: m === month,
      weekend,
      future,
      selectable: !weekend && !future,
    });
  }
  return cells;
}

export interface TradeDatePickerProps {
  value: string;
  onChange: (iso: string) => void;
  /** 日历可选上限（通常为今天）；缺省不限制未来以外的工作日 */
  maxDate?: string;
  className?: string;
}

/** 复盘用交易日选择器：周末置灰不可选，不提供非交易日入口 */
export function TradeDatePicker({ value, onChange, maxDate, className }: TradeDatePickerProps) {
  const parsed = parseIso(value) || parseIso(maxDate || "") || {
    y: new Date().getFullYear(),
    m: new Date().getMonth(),
    d: new Date().getDate(),
  };
  const [open, setOpen] = useState(false);
  const [viewY, setViewY] = useState(parsed.y);
  const [viewM, setViewM] = useState(parsed.m);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const p = parseIso(value);
    if (p) {
      setViewY(p.y);
      setViewM(p.m);
    }
  }, [open, value]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const maxIso = maxDate || "9999-12-31";
  const cells = useMemo(() => buildGrid(viewY, viewM, maxIso), [viewY, viewM, maxIso]);

  function shiftMonth(delta: number) {
    const d = new Date(viewY, viewM + delta, 1);
    setViewY(d.getFullYear());
    setViewM(d.getMonth());
  }

  function pick(iso: string, selectable: boolean) {
    if (!selectable) return;
    onChange(iso);
    setOpen(false);
  }

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm hover:border-primary/40"
      >
        <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
        {value || "选择交易日"}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-[260px] rounded-xl border border-border bg-card p-2.5 shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              onClick={() => shiftMonth(-1)}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="上一月"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-medium tabular-nums">
              {viewY}年{viewM + 1}月
            </span>
            <button
              type="button"
              onClick={() => shiftMonth(1)}
              className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="下一月"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="mb-1 grid grid-cols-7 gap-0.5 text-center text-[10px] text-muted-foreground">
            {WEEKDAYS.map((w) => (
              <div key={w} className={cn(w === "六" || w === "日" ? "text-muted-foreground/40" : "")}>
                {w}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-0.5">
            {cells.map((c) => {
              const selected = c.iso === value;
              return (
                <button
                  key={c.iso}
                  type="button"
                  disabled={!c.selectable}
                  onClick={() => pick(c.iso, c.selectable)}
                  title={c.weekend ? "非交易日" : c.future ? "未来日期" : c.iso}
                  className={cn(
                    "h-8 rounded text-[12px] tabular-nums transition-colors",
                    !c.inMonth && "opacity-35",
                    c.weekend || c.future
                      ? "cursor-not-allowed text-muted-foreground/35"
                      : "hover:bg-primary/15 hover:text-primary",
                    selected && c.selectable && "bg-primary/20 font-semibold text-primary",
                  )}
                >
                  {c.day}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-[10px] text-muted-foreground/70">周末置灰不可选</p>
        </div>
      )}
    </div>
  );
}
