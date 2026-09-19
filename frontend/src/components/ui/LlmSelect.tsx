import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  LLM_CHANGE_EVENT, defaultLlmId, resolveLlm, resolveLlmId, savedLlmLabel,
  setLlmOverride, usableSavedLlms, type LlmConfig, type SavedLlmEntry,
} from "@/lib/llm";

export interface LlmPick {
  id: string;
  setId: (id: string) => void;
  llm: LlmConfig | null;
  options: SavedLlmEntry[];
  defaultId: string | null;
  configured: boolean;
}

/** 读全局默认 + 本次会话临时选择；下拉变更不改默认，只影响本会话的问 AI。 */
export function useLlmPick(): LlmPick {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const sync = () => setTick((n) => n + 1);
    window.addEventListener(LLM_CHANGE_EVENT, sync);
    return () => window.removeEventListener(LLM_CHANGE_EVENT, sync);
  }, []);
  void tick;
  const options = usableSavedLlms();
  const defaultId = defaultLlmId();
  const id = resolveLlmId() || "";
  const llm = resolveLlm(id);
  return {
    id,
    setId: (next) => setLlmOverride(next || null),
    llm,
    options,
    defaultId,
    configured: llm !== null,
  };
}

interface Props {
  compact?: boolean;
  disabled?: boolean;
  className?: string;
  /** 未接入时：隐藏，或显示去配置链接 */
  empty?: "none" | "link";
}

/** 已配置模型下拉。选中项用于本次问 AI；带「（默认）」的是接入 AI 页指定的全局默认。 */
export function LlmSelect({ compact, disabled, className, empty = "none" }: Props) {
  const { id, setId, options, defaultId, configured } = useLlmPick();
  if (!configured || options.length === 0) {
    if (empty === "link") {
      return (
        <Link to="/settings" className="text-xs text-primary hover:underline">
          尚未接入 AI
        </Link>
      );
    }
    return null;
  }
  return (
    <select
      aria-label="选择模型"
      title="本次提问使用的模型。默认模型在「接入 AI」里设置，此处改选只影响本会话。"
      value={id}
      disabled={disabled}
      onChange={(e) => setId(e.target.value)}
      className={cn(
        "max-w-[16rem] truncate rounded-lg border border-border bg-black/20 text-foreground outline-none focus:border-primary/50 disabled:opacity-40",
        compact ? "px-2 py-1 text-xs" : "px-2.5 py-1.5 text-sm",
        className,
      )}
    >
      {options.map((e) => (
        <option key={e.id} value={e.id}>
          {savedLlmLabel(e)}{e.id === defaultId ? "（默认）" : ""}
        </option>
      ))}
    </select>
  );
}
