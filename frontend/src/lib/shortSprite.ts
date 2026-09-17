import { request } from "./api";

export type SpriteUnit = "pct" | "count" | "temp" | "resonance";
export type SpriteEvent = "speed_up" | "speed_down" | "break_up" | "break_down";
export type SpriteEventLabel = "涨速" | "突破" | "跌破";

export interface SpriteHit {
  id: string;
  ts: string;
  epoch?: number;
  seq_id: string;
  name: string;
  event: SpriteEvent;
  event_label: SpriteEventLabel;
  direction: "up" | "down";
  reversed: boolean;
  value: number;
  unit: SpriteUnit | string;
  speech: string;
  voice: boolean;
}

export interface SpriteSequence {
  id: string;
  name: string;
  kind: "board" | "style";
  unit: SpriteUnit | string;
  reversed: boolean;
  monitored: boolean;
  voice: boolean;
  open: number | null;
  open_ts: string | null;
  current: number | null;
  vs_open: number | null;
  speed: number | null;
  speed_from: number | null;
  speed_from_ts: number | null;
  thresholds: {
    speed_up: number;
    speed_down: number;
    break_up: number;
    break_down: number;
    hysteresis: number;
  };
  outside: {
    speed_up: boolean;
    speed_down: boolean;
    break_up: boolean;
    break_down: boolean;
  };
  last_hit: SpriteHit | null;
  samples: { ts: number; value: number }[];
}

export interface ShortSpriteSnapshot {
  date: string | null;
  is_live: boolean;
  settled: boolean;
  enabled: boolean;
  can_detect: boolean;
  disclaimer: string;
  sequences: SpriteSequence[];
  hits: SpriteHit[];
  new_hits: SpriteHit[];
}

export interface ShortSpriteRule {
  key: string;
  label: string;
  unit: SpriteUnit | string;
  reversed: boolean;
  monitor: boolean;
  voice: boolean;
  speed_up: number;
  speed_down: number;
  break_up: number;
  break_down: number;
  hysteresis: number;
  defaults: {
    monitor: boolean;
    voice: boolean;
    speed_up: number;
    speed_down: number;
    break_up: number;
    break_down: number;
    hysteresis: number;
  };
}

export interface ShortSpriteConfig {
  schema: number;
  path: string;
  rules: ShortSpriteRule[];
  values: Record<string, ShortSpriteRule["defaults"]>;
  defaults: Record<string, ShortSpriteRule["defaults"]>;
}

export function fetchShortSprite(): Promise<ShortSpriteSnapshot> {
  return request<ShortSpriteSnapshot>("/market/short-sprite");
}

/** 盘面/风格随盘拍触发 tick；失败忽略，不挡主刷。 */
export function pingShortSprite(): Promise<void> {
  return fetchShortSprite().then(() => undefined).catch(() => undefined);
}

export function setShortSpriteEnabled(enabled: boolean): Promise<ShortSpriteSnapshot> {
  return request<ShortSpriteSnapshot>("/market/short-sprite/enabled", "POST", { enabled });
}

export function fetchShortSpriteConfig(): Promise<ShortSpriteConfig> {
  return request<ShortSpriteConfig>("/config/short-sprite");
}

export function saveShortSpriteConfig(
  rules: Record<string, Partial<ShortSpriteRule>>,
): Promise<ShortSpriteConfig> {
  return request<ShortSpriteConfig>("/config/short-sprite", "POST", { rules });
}

export function resetShortSpriteConfig(): Promise<ShortSpriteConfig> {
  return request<ShortSpriteConfig>("/config/short-sprite/reset", "POST", {});
}

export function fmtSpriteValue(v: number | null | undefined, unit: string): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (unit === "pct") return `${v.toFixed(2)}%`;
  if (unit === "count") return `${Math.round(v)} 家`;
  if (unit === "resonance") return v.toFixed(3);
  if (Math.abs(v - Math.round(v)) < 1e-6) return String(Math.round(v));
  return v.toFixed(1);
}

export function fmtSampleTs(epoch: number): string {
  const d = new Date(epoch * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
