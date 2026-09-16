import { request } from "./api";
import { DOWN_TEXT, FLAT_TEXT, UP_TEXT } from "./colors";

export interface BoardEmotionLayer {
  key: string;
  label: string;
  unit: string;
  invert: boolean;
  value: number | null;
  window_dates: string[];
  window_values: Array<number | null>;
  missing_dates: string[];
  n: number;
  baseline_default: number | null;
  baseline: number | null;
  baseline_overridden: boolean;
  sigma: number;
  diff: number | null;
  coefficient: number | null;
  weight_default: number;
  weight: number;
  included: boolean;
  missing: boolean;
  missing_reasons: string[];
}

export interface BoardEmotionScore {
  trial: boolean;
  score: number | null;
  label: string;
  reason: string | null;
  active_layers: number;
  layers: BoardEmotionLayer[];
}

export interface BoardEmotionResonanceSnapshot {
  available: boolean;
  date: string;
  is_live: boolean;
  phase?: string | null;
  window_dates: string[];
  note: string;
  default: BoardEmotionScore;
  trial: BoardEmotionScore | null;
}

export function fetchBoardEmotionResonance(date?: string) {
  const q = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<BoardEmotionResonanceSnapshot>(`/market/board-emotion-resonance${q}`);
}

export function trialBoardEmotionResonance(body: {
  date?: string;
  baselines?: Record<string, number>;
  weights?: Record<string, number>;
}) {
  return request<BoardEmotionResonanceSnapshot>(
    "/market/board-emotion-resonance",
    "POST",
    body,
  );
}

export function formatResonanceScore(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "—";
  return score.toFixed(3);
}

export function resonanceLabelClass(label: string): string {
  if (label === "偏多") return UP_TEXT;
  if (label === "偏空") return DOWN_TEXT;
  if (label === "不足") return "text-warning";
  return FLAT_TEXT;
}

export function formatLayerValue(unit: string, v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (unit === "ratio") return `${(v * 100).toFixed(1)}%`;
  if (unit === "pct") {
    const sign = v > 0 ? "+" : "";
    return `${sign}${v.toFixed(digits)}%`;
  }
  if (unit === "板") {
    return `${Number.isInteger(v) ? String(v) : v.toFixed(1)} 板`;
  }
  return v.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}
