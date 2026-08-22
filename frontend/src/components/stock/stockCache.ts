// 个股面板本地缓存：每个标的一份，允许重新拉取 / 重新分析。

import type { DebateStage } from "@/lib/agents";
import type {
  Announcement, Blocks, BlockTradeRow, DividendRow, DragonTiger, Financials,
  FundFlowRow, GlobalStock, HkCashflow, HotConcept, HolderRow, Lockup,
  MarginRow, NewsItem, QaRow, Report, Valuation, ValPercentile,
} from "@/lib/api";

const DATA_PREFIX = "va-stock-data:";
const DEBATE_PREFIX = "va-stock-debate:";

export interface StockDataCache {
  code: string;
  fetchedAt: number;
  val: Valuation | null;
  reports: Report[];
  news: NewsItem[];
  pctl: ValPercentile | null;
  fin: Financials | null;
  anns: Announcement[];
  depNote: string | null;
  margin: MarginRow[];
  blockT: BlockTradeRow[];
  holders: HolderRow[];
  dividend: DividendRow[];
  fundFlow: FundFlowRow[];
  dt: DragonTiger | null;
  lockup: Lockup | null;
  blocks: Blocks | null;
  hotCon: HotConcept[];
  qa: QaRow[];
  gstock: GlobalStock | null;
  cashflow: HkCashflow | null;
}

export interface DebateStageBox {
  stage: DebateStage;
  label: string;
  content: string;
  done: boolean;
}

export interface DebateCache {
  code: string;
  name?: string;
  rounds: number;
  status: string;
  progress: { title: string; ok: boolean }[];
  missing: string[];
  stages: DebateStageBox[];
  error: string;
  finishedAt: number | null;
}

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 隐私模式或配额满 */
  }
}

export function loadStockDataCache(code: string): StockDataCache | null {
  const c = (code || "").trim().toUpperCase();
  if (!c) return null;
  return read<StockDataCache>(DATA_PREFIX + c);
}

export function saveStockDataCache(data: StockDataCache) {
  const c = (data.code || "").trim().toUpperCase();
  if (!c) return;
  write(DATA_PREFIX + c, { ...data, code: c });
}

export function clearStockDataCache(code: string) {
  try {
    localStorage.removeItem(DATA_PREFIX + (code || "").trim().toUpperCase());
  } catch { /* ignore */ }
}

export function loadDebateCache(code: string): DebateCache | null {
  const c = (code || "").trim();
  if (!/^\d{6}$/.test(c)) return null;
  return read<DebateCache>(DEBATE_PREFIX + c);
}

export function saveDebateCache(data: DebateCache) {
  const c = (data.code || "").trim();
  if (!/^\d{6}$/.test(c)) return;
  write(DEBATE_PREFIX + c, { ...data, code: c });
}

export function clearDebateCache(code: string) {
  try {
    localStorage.removeItem(DEBATE_PREFIX + (code || "").trim());
  } catch { /* ignore */ }
}
