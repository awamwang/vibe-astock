import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button, Input, SearchField } from "react-aria-components";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";

function isImeKey(e: KeyboardEvent): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}

export interface SearchInputProps {
  value: string;
  /** 仅在输入法合成结束后提交，避免拼音阶段触发筛选/请求 */
  onChange: (value: string) => void;
  /** Enter（非合成态）确认；消息分析用来立刻搜或刷新 */
  onSubmit?: (value: string) => void;
  placeholder?: string;
  className?: string;
  inputClassName?: string;
  "aria-label"?: string;
  disabled?: boolean;
  autoFocus?: boolean;
}

/**
 * 全站统一搜索框：Adobe React Aria SearchField + 中文输入法合成拦截 + 清空按钮。
 * 合成期间只更新框内显示，不把拼音泄漏给筛选/防抖请求；Enter 确认字词也不会当搜索提交。
 */
export function SearchInput({
  value,
  onChange,
  onSubmit,
  placeholder,
  className,
  inputClassName,
  "aria-label": ariaLabel = "搜索",
  disabled,
  autoFocus,
}: SearchInputProps) {
  const [inner, setInner] = useState(value);
  const composingRef = useRef(false);
  /** 输入法确认键（含 keyCode 229）会穿透成 Enter，挡住同一次提交 */
  const imeKeyRef = useRef(false);

  useEffect(() => {
    // 外部清空（重置筛选）时即使仍在合成也要跟进，避免 compositionEnd 把拼音写回去
    if (composingRef.current && value !== "") return;
    composingRef.current = false;
    setInner(value);
  }, [value]);

  const commit = (next: string) => {
    composingRef.current = false;
    imeKeyRef.current = false;
    setInner(next);
    onChange(next);
  };

  return (
    <SearchField
      aria-label={ariaLabel}
      className={cn("relative w-full min-w-0", className)}
      value={inner}
      onChange={(next) => {
        setInner(next);
        if (!composingRef.current) onChange(next);
      }}
      onSubmit={(next) => {
        if (composingRef.current || imeKeyRef.current) {
          imeKeyRef.current = false;
          return;
        }
        onSubmit?.(next);
      }}
      onClear={() => commit("")}
      isDisabled={disabled}
      autoFocus={autoFocus}
    >
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        className={cn(
          "w-full rounded-lg border border-border bg-background py-2 pl-9 pr-8 text-sm text-foreground",
          "placeholder:text-muted-foreground outline-none focus:border-primary/50 disabled:opacity-50",
          "[&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden",
          inputClassName,
        )}
        onCompositionStart={() => {
          composingRef.current = true;
        }}
        onCompositionEnd={(e) => {
          composingRef.current = false;
          const next = e.currentTarget.value;
          setInner(next);
          onChange(next);
          window.setTimeout(() => {
            imeKeyRef.current = false;
          }, 0);
        }}
        onBlur={(e) => {
          if (!composingRef.current) return;
          composingRef.current = false;
          const next = e.currentTarget.value;
          setInner(next);
          onChange(next);
        }}
        onKeyDownCapture={(e) => {
          const enter = e.key === "Enter" || e.key === "Process" || e.keyCode === 13;
          if (enter && isImeKey(e)) imeKeyRef.current = true;
        }}
      />
      {inner ? (
        <Button
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-muted/60 hover:text-foreground"
          aria-label="清空搜索"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      ) : null}
    </SearchField>
  );
}
