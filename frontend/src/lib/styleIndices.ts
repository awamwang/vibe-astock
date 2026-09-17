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
}

export function fetchStyleIndices() {
  return request<StyleIndicesSnapshot>("/market/style-indices");
}

export function formatStylePct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
