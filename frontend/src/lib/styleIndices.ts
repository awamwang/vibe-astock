import { request } from "./api";

export interface StyleIndexItem {
  key: string;
  name: string;
  group: string;
  code: string;
  change_pct: number | null;
  price: number | null;
  up: number | null;
  down: number | null;
  note: string | null;
  available: boolean;
  width_flag?: "价升面窄" | "价跌面宽" | null;
  change_pct_delta?: number | null;
  excess_rank_delta?: number | null;
  zscore?: number | null;
  cum_excess?: number | null;
  close_extreme?: "新高" | "新低" | "都不是" | "不足" | null;
}

export interface StyleIndexGroup {
  id: string;
  label: string;
  items: StyleIndexItem[];
}

export interface StyleIndexUnavailable {
  key: string;
  name: string;
  reason: string;
}

export type StylePreferenceStatus = "ok" | "partial" | "absent";
export type BoardGroupVs = "同向" | "反向" | "近平" | "不足";

export interface StylePreference {
  status: StylePreferenceStatus;
  hotspots: { key: string; excess: number }[];
  group_leads: { group: string; key: string }[];
  board_group: { n_valid: number; mean: number | null; vs: BoardGroupVs };
  size_spread: { value: number | null; status: "ok" | "不足" };
  size_spread_cnindex: { value: number | null };
}

export interface StyleIndicesSnapshot {
  available: boolean;
  reason?: string | null;
  date: string;
  is_live: boolean;
  updated?: string;
  hit: number;
  total: number;
  groups: StyleIndexGroup[];
  unavailable: StyleIndexUnavailable[];
  preference?: StylePreference;
  rotation?: StyleRotation;
}

export type StyleRotationStatus = "ok" | "partial" | "absent";

export interface StyleRotation {
  status: StyleRotationStatus;
  this: { date: string } | null;
  against: { date: string } | null;
  live_deferred: boolean;
  hotspot_enter: string[];
  hotspot_leave: string[];
  spearman: { value: number | null; n: number; status: "ok" | "不足" };
  z_n: number;
  close_n: number;
}

export function fetchStyleIndices() {
  return request<StyleIndicesSnapshot>("/market/style-indices");
}

export function formatStylePct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

export function formatStyleDelta(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "不足";
  return formatStylePct(v);
}

export function formatRankDelta(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "不足";
  return v > 0 ? `+${v}` : String(v);
}

export function formatZscore(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "不足";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}
