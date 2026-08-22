// 多 agent 前端客户端：多空辩论（NDJSON 流）。

import { ApiError } from "@/lib/api";
import { loadLlm } from "@/lib/llm";
import { streamNdjson, type NdjsonEvent } from "@/lib/ndjson";

export type DebateStage = "bull" | "bear" | "bull_rebut" | "bear_rebut" | "referee";

export interface DebateHandlers {
  onStatus?: (message: string) => void;
  onDossierProgress?: (title: string, ok: boolean, loaded: number, total: number) => void;
  onDossierReady?: (sections: { title: string; tool: string }[], missing: string[]) => void;
  onStageStart?: (stage: DebateStage, label: string) => void;
  onDelta?: (stage: DebateStage, text: string) => void;
  onStageDone?: (stage: DebateStage, label: string, content: string) => void;
  onError?: (message: string, stage?: DebateStage) => void;
}

function requireLlm() {
  const llm = loadLlm();
  if (!llm) throw new ApiError("尚未接入 AI，请先在「接入 AI」里配置", 400);
  return llm;
}

function dispatchDebate(ev: NdjsonEvent, h: DebateHandlers) {
  switch (ev.type) {
    case "status":
      h.onStatus?.(ev.message);
      break;
    case "dossier_progress":
      h.onDossierProgress?.(ev.title, ev.ok, ev.loaded, ev.total);
      break;
    case "dossier":
      h.onDossierReady?.(ev.sections || [], ev.missing || []);
      break;
    case "stage":
      h.onStageStart?.(ev.stage, ev.label);
      break;
    case "delta":
      h.onDelta?.(ev.stage, ev.text);
      break;
    case "stage_done":
      h.onStageDone?.(ev.stage, ev.label, ev.content);
      break;
    case "error":
      h.onError?.(ev.message, ev.stage);
      break;
  }
}

/** 跑一场多空辩论。rounds=2 时多空各多一轮交叉反驳。 */
export async function debateStream(
  code: string,
  rounds: number,
  handlers: DebateHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  const llm = requireLlm();
  await streamNdjson("/api/debate", { code, rounds, llm }, (ev) => dispatchDebate(ev, handlers), signal);
}
