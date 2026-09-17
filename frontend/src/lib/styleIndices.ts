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
}

export function fetchStyleIndices() {
  return request<StyleIndicesSnapshot>("/market/style-indices");
}

export function formatStylePct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
