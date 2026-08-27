import { apiUrl } from "./base";
import type { WatchItem } from "./watchlist";
import type {
  LiveEmotion,
  MarketSession,
  MoodBlocksSnapshot,
  ShortBoardSnapshot,
  ShortTermEmotion,
} from "./liveBoard";
// 后端 API 客户端（HTTP 传输层）。/api → vite 代理到本仓库的 FastAPI（server.py，默认 8910）。
// 领域类型见 liveBoard（直播盘面）/ agent（复盘档案）/ watchlist（自选）；本文件只做 auth、ApiError、request。
// 后端未启动或数据源异常时抛 ApiError，页面据此优雅降级。

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

// 后端访问密钥（对应后端部署时的 VR_API_KEY，公网部署防蹭用）。只存本地浏览器。
const ACCESS_KEY = "vr-access-key";

export function loadAccessKey(): string {
  try {
    return localStorage.getItem(ACCESS_KEY) || "";
  } catch {
    return "";
  }
}

export function saveAccessKey(key: string) {
  try {
    if (key) localStorage.setItem(ACCESS_KEY, key);
    else localStorage.removeItem(ACCESS_KEY);
  } catch {
    /* 隐私模式等场景 localStorage 不可用 */
  }
}

export function authHeaders(): Record<string, string> {
  const k = loadAccessKey();
  return k ? { Authorization: `Bearer ${k}` } : {};
}

export interface MyReport {
  id: string; name: string; industry: string; size: number; ext: string; ts: number;
}

// 下载/预览研报：带鉴权头 fetch → blob → 触发浏览器下载（<a download> 无法带 Authorization，故走 blob）。
export async function downloadReport(id: string, name: string): Promise<void> {
  const resp = await fetch(apiUrl(`/api/myreports/file/${id}`), { headers: authHeaders() });
  if (!resp.ok) throw new ApiError(`下载失败 HTTP ${resp.status}`, resp.status);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function request<T>(path: string, method: "GET" | "POST" | "DELETE" | "PUT" | "PATCH" = "GET", body?: unknown): Promise<T> {
  let resp: Response;
  const headers: Record<string, string> = { ...authHeaders() };
  const opts: RequestInit = { method };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (Object.keys(headers).length > 0) opts.headers = headers;
  try {
    resp = await fetch(apiUrl(`/api${path}`), opts);
  } catch {
    throw new ApiError("连接不到后端，请先在项目根目录启动：.venv/bin/python server.py（默认 8910）", 0);
  }
  let payload: any = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    if (resp.status === 401) {
      throw new ApiError("后端开启了访问鉴权（VR_API_KEY）：请在「接入 AI」页底部填写后端访问密钥", 401);
    }
    throw new ApiError(payload?.detail || payload?.error || `HTTP ${resp.status}`, resp.status);
  }
  return (payload?.data ?? payload) as T;
}

const get = <T>(path: string) => request<T>(path, "GET");

export interface Quote {
  name: string; price: number; last_close: number; change_pct: number;
  pe_ttm: number; pb: number; mcap_yi: number; turnover_pct: number;
  limit_up: number; limit_down: number;
}

export interface Valuation {
  name: string; code: string; price: number; mcap_yi: number;
  pe_ttm: number; pb: number;
  eps_26e: number | null; eps_27e: number | null; pe_26e: number | null;
  cagr_pct: number | null; peg: number | null; digest_years: number | null;
  analyst_count: number; forecast_note?: string;
}

export interface Report {
  title: string; publishDate: string; orgSName: string;
  emRatingName?: string; indvInduName?: string; pdfUrl?: string | null;
}

export interface ValMetric {
  current: number; percentile: number; min: number; max: number;
  p20: number; p50: number; p80: number; n: number;
}
export interface ValPercentile {
  period: string; metrics: { pe_ttm?: ValMetric; pb?: ValMetric };
}

export interface Announcement {
  date: string; title: string; type: string; url: string;
}

export interface Financials {
  period: string | null;
  revenue: string | null; revenue_yoy: string | null;
  net_profit: string | null; net_profit_yoy: string | null;
  eps: string | null; bvps: string | null; roe: string | null;
  gross_margin: string | null; net_margin: string | null; op_cf_ps: string | null;
}

export interface NewsItem {
  新闻标题?: string; 发布时间?: string; 文章来源?: string; 新闻链接?: string;
}

export interface IndexQuote {
  name: string; price: number; change_pct: number; change_amt: number;
}

export interface MarketSentimentYesterday {
  breadth?: string;
  speculation?: string;
  up?: number;
  down?: number;
  flat?: number;
  active?: string;
}

export interface MarketSentiment {
  up: number; down: number; flat: number; zt: number; zt_real: number; dt: number; dt_real: number;
  active: string; breadth: string; speculation: string; date: string;
  prev_date?: string | null;
  is_live?: boolean;
  yesterday?: MarketSentimentYesterday;
}
export interface SectorFlow {
  name: string; pct: number; net: number; inflow: number; outflow: number; firms: number;
}
export interface MarketOverview {
  sentiment: MarketSentiment; sectors: SectorFlow[]; updated: string;
}

// 每日盯盘：3 秒实时快照（持仓/自选/500亿大票/三板+/昨日成交前十 + 异动流）
export interface WatchRow {
  code: string; name: string;
  price: number | null; pct: number | null; amount: number | null;
  cost?: number; shares?: number; pnl_pct?: number;   // 持仓行
  boards?: number; is_limit?: boolean;                 // 三板+行
}
export interface MonitorAlert {
  ts: string; code: string; name: string; kind: string; msg: string; sources: string[];
}
export interface MonitorSnapshot {
  ts: string; phase: "open" | "break" | "closed"; poll_seconds: number;
  holdings: WatchRow[]; watchlist: WatchRow[];
  bigcap: { total: number; top: WatchRow[] };
  lianban3: WatchRow[];
  turnover: { label: string; stocks: WatchRow[] };
  alerts: MonitorAlert[];
}

// 涨停分析：当日全部涨停股 + 涨停原因题材串（客观公开榜单）
export interface FirstBoardStock {
  code: string; name: string; boards: number;
  price: number; pct: number; amount: number | null; float_cap: number | null;
  industry: string; seal_time: string; break_count: number; reason: string;
  themes: string[];
}
export interface ThemeOption { tag: string; count: number }
export interface FirstBoardData {
  date: string; total_zt: number; first_count: number; lianban_count: number;
  reason_note: string | null;
  theme_options: ThemeOption[];
  stocks: FirstBoardStock[];
}

export interface ZtReasonPreviewRow {
  code: string; name: string; reason: string;
}
export interface ZtReasonPreview {
  ok: boolean; date: string; count: number; skipped: number;
  rows: ZtReasonPreviewRow[];
}

// 全市场成交额榜（客观公开榜单）
export interface TurnoverStock {
  code: string; name: string;
  price: number | null; pct: number | null;
  amount: number | null; mcap: number | null; float_cap: number | null; industry: string;
}
export interface TurnoverTop { stocks: TurnoverStock[]; updated: string }

export interface RadarItem {
  title: string; url: string; time: string; source: string; summary?: string; zh?: string;
}
export interface Industry {
  key: string; name: string; accent: string; total: number; items: RadarItem[];
}
export interface RadarData {
  generated_at: string | null; recent_days: number; industries: Industry[];
  stats: { industries: number; total_sources: number; failed_sources?: number };
}

export type ImpactLevel = "critical" | "high" | "medium" | "low" | "noise";
export type Freshness = "new" | "follow_up" | "duplicate" | "rumor";
export type EffectStatus =
  | "not_erupted" | "pending_verify" | "ongoing_hype" | "already_hyped" | "invalid";
export type TargetKind = "market" | "sector" | "theme" | "stock" | "other";

export interface ImpactTarget {
  kind: TargetKind;
  code?: string | null;
  name: string;
}

export interface MessageSourceInfo {
  id: string;
  label: string;
  adapter_type: "manual" | "poll";
  enabled: boolean;
  poll_interval_s?: number | null;
  last_poll_at?: string | null;
  last_error?: string | null;
}

export interface RawMessageDraft {
  draft_key: string;
  source_id: string;
  source_label: string;
  content: string;
  title: string;
  keywords: string[];
  url: string;
  marks: string[];
  external_ref?: string | null;
  produced_at?: string | null;
  effective_mode?: "immediate" | "scheduled";
  effective_at?: string | null;
  targets: ImpactTarget[];
  meta?: Record<string, unknown>;
}

export interface RawMessage {
  id: string;
  source_id: string;
  source_label: string;
  content: string;
  title: string;
  keywords: string[];
  url: string;
  marks: string[];
  content_hash: string;
  batch_id?: string | null;
  external_ref?: string | null;
  produced_at: string;
  ingested_at: string;
  meta?: Record<string, unknown>;
}

export interface AnalyzedMessage {
  id: string;
  raw_ids: string[];
  source_id: string;
  source_label: string;
  title: string;
  keywords: string[];
  url: string;
  marks: string[];
  summary: string;
  detail: string;
  effective_mode: "immediate" | "scheduled";
  effective_at?: string | null;
  end_at?: string | null;
  produced_at: string;
  targets: ImpactTarget[];
  impact_level: ImpactLevel;
  freshness: Freshness;
  effect_status: EffectStatus;
  analyzed_at?: string | null;
  analyzed_by?: string | null;
  version: number;
  status: "draft" | "confirmed" | "archived";
  favorited?: boolean;
  followed?: boolean;
  matched_follow_keywords?: string[];
}

export interface AnalyzedMessageDetail extends AnalyzedMessage {
  raw_messages: RawMessage[];
}

export interface MessageListResult {
  items: AnalyzedMessage[];
  total: number;
}

export interface XgbPollResult {
  fetched: number;
  inserted: number;
  withdrawn: number;
  head_mark?: string;
  tail_mark?: string;
}

export interface ClsPollResult {
  fetched: number;
  pages_used?: number;
  pages_backfill?: number;
  new_candidates: number;
  inserted: number;
  updated?: number;
  synced: number;
  tail_mark?: string;
  last_id?: number;
  backfill_today?: boolean;
}

export interface Holding {
  code: string; name: string; price: number; shares: number; cost: number;
  market_value: number; pnl: number; pnl_pct: number;
}
export interface ClosedPosition {
  code: string; name: string; date: string; price: number; shares: number; cost: number;
  pnl: number; pnl_pct: number;
}
export interface PortfolioData {
  holdings: Holding[];
  totals: { market_value: number; cost: number; pnl: number; pnl_pct: number };
  closed: ClosedPosition[];
  realized_pnl: number;
  updated: string; last_refresh: string | null;
}

/** 券商持仓截图 AI 解析草稿（对照确认后再写入） */
export interface ScreenshotHoldingRow {
  code: string;
  name?: string | null;
  shares: number;
  available_shares?: number | null;
  cost?: number | null;
  price?: number | null;
  pnl?: number | null;
  market_value?: number | null;
  include?: boolean;
}
export interface ScreenshotDraft {
  broker?: string | null;
  account_name?: string | null;
  account_display?: string | null;
  equity?: number | null;
  cash_balance?: number | null;
  available?: number | null;
  withdrawable?: number | null;
  frozen?: number | null;
  stock_market_value?: number | null;
  position_pnl?: number | null;
  daily_pnl?: number | null;
  daily_pnl_pct?: number | null;
  note?: string | null;
  holdings: ScreenshotHoldingRow[];
}

export interface TradeAccountFields {
  account_name?: string;
  cash_balance?: number;
  account_display?: string;
  broker?: string;
  available?: number;
  withdrawable?: number;
  frozen?: number;
  stock_market_value?: number;
  position_pnl?: number;
  daily_pnl?: number;
  daily_pnl_pct?: number;
}

export interface TradeDaySnapshot extends TradeAccountFields {
  equity: number;
  market_value: number;
  asof: string;
  summary?: string;
}

/** 仓位预算六档（硬规则，与 AI 五档分开） */
export interface TradePhaseRow {
  phase: string; cap_total: number; cap_single: number;
  prompt?: string;
  allow: string[]; forbid: string[];
}
export interface TradeRepairProxy {
  met: boolean;
  checks: { key: string; ok: boolean; detail: string }[];
}
export interface TradeBudget {
  schema?: number;
  date: string;
  available: boolean;
  reason?: string | null;
  rule_phase?: string | null;
  override_phase?: string | null;
  override_reason?: string | null;
  phase?: string | null;
  cap_total?: number | null;
  cap_single?: number | null;
  prompt?: string | null;
  allow?: string[];
  forbid?: string[];
  expansion_allowed?: boolean;
  demoted?: boolean;
  classify_reasons?: string[];
  repair_proxy?: TradeRepairProxy;
  prev_rule_phase?: string | null;
  block_new_long_reasons?: string[];
  width_divergence?: { hit?: boolean; skipped?: boolean; reason?: string } | null;
  generated_at?: string;
  readings?: {
    s?: number | null;
    s_ok?: boolean;
    s_method?: string | null;
    [key: string]: unknown;
  };
}
export interface TradeConstants {
  risk_per_trade: number;
  daily_loss_limit: number;
  max_dd_soft: number;
  max_dd_hard: number;
}
export interface TradeAccount {
  schema: number;
  equity: number | null;
  equity_note: string;
  account_fields?: TradeAccountFields;
  updated_at: string | null;
  snapshots: Record<string, TradeDaySnapshot>;
  constants: TradeConstants;
}
export interface TradeGuard {
  date: string;
  budget: TradeBudget;
  equity: number | null;
  constants: TradeConstants;
  position: {
    market_value: number;
    total_pct: number | null;
    over_total: boolean;
    remain_total: number;
    per_name: { code: string; name: string; market_value: number; pct_of_equity: number | null; over_single: boolean }[];
    breaches: string[];
  } | null;
  reduce_order: {
    code: string; name: string; market_value: number; pnl: number; pnl_pct?: number;
    action: string; suggest_cut?: number;
  }[];
  daily_loss: {
    prev_date: string; prev_equity: number; equity: number;
    pnl_pct: number; limit: number; hit: boolean;
  } | null;
  block_new_long_reasons: string[];
}
export interface TradeSizeResult {
  ok: boolean; reason?: string; amount: number;
  date?: string; phase?: string;
  cap_total?: number; cap_single?: number; used?: number;
  components?: Record<string, number>;
}

// 资金面 / 筹码 / 信号（v3.3 并入，均为「用户查的那只股」的公开数据）
export interface MarginRow { date: string; rzye: number; rzmre: number; rzche: number; rqye: number; rqmcl: number; rzrqye: number }
export interface BlockTradeRow { date: string; price: number; close: number; premium_pct: number; vol: number; amount: number; buyer: string; seller: string }
export interface HolderRow { date: string; holder_num: number; change_ratio: number; avg_shares: number }
export interface DividendRow { date: string; bonus_rmb: number; transfer_ratio: number; bonus_ratio: number | null; plan: string }
export interface FundFlowRow { date: string; main_net: number; small_net: number; mid_net: number; large_net: number; super_net: number }
export interface DtSeat { name: string; buy_amt: number; sell_amt: number; net: number }
export interface DragonTiger {
  records: { date: string; reason: string; net_buy: number; turnover: number }[];
  seats: { buy: DtSeat[]; sell: DtSeat[] };
  institution: { buy_amt: number; sell_amt: number; net_amt: number };
}
export interface LockupRow { date: string; type: string; shares: number; able_shares: number; ratio: number }
export interface Lockup { history: LockupRow[]; upcoming: LockupRow[] }
export interface Board { name: string; code: string; change_pct: number | string; lead_stock: string }
export interface Blocks { total: number; boards: Board[]; concept_tags: string[] }
export interface HotConcept { concept: string; bk: string; hit: number }
export interface QaRow { company: string; question: string; answer: string | null; answerer: string; ask_time: string }
export interface IndustryRow { rank: number; name: string; change_pct: number; code: string; up_count: number; down_count: number }
export interface IndustryData { top: IndustryRow[]; bottom: IndustryRow[]; total: number }

// 全球市场（美股 / 港股，移植自 global-stock-data · 东财域内源）
export interface GlobalIndex {
  key: string; name: string; region: string;
  price: number | null; change_pct: number | null;
}
export interface GlobalQuote {
  code: string; name: string;
  price: number | null; open: number | null; high: number | null; low: number | null;
  prev_close: number | null; amount: number | null; mcap: number | null; change_pct: number | null;
}
export interface GlobalMetrics {
  report_date: string;
  revenue: number | null; revenue_yoy: number | null; net_profit: number | null;
  eps: number | null; roe: number | null; gross_margin: number | null;
  net_margin: number | null; debt_ratio: number | null;
}
export interface GlobalStock {
  code: string; name: string; market: string;
  quote: GlobalQuote; metrics: GlobalMetrics | null;
}

export interface HkCashflowItem { amount: number | null; yoy: number | null }
export interface HkCashflowPeriod {
  report_date: string;
  items: Record<string, HkCashflowItem>;
}
export interface HkCashflow {
  currency: string | null; item_order: string[]; periods: HkCashflowPeriod[];
}

/** 隔夜外围快照：指数 + 美股七姐妹，各自带「属于哪一场」 */
export interface OverseasRow {
  name: string;
  price: number;
  change_pct: number;
  /** 该行行情所属交易日；取不到为 null（**不拿今天顶替**） */
  session: string | null;
  region?: string;
  ticker?: string;
}
export interface OverseasSnapshot {
  available: boolean;
  reason?: string;
  indices?: OverseasRow[];
  mag7?: OverseasRow[];
  us_session?: string | null;
  hk_session?: string | null;
  /** 可直接展示的一句话，如「美股 2026-07-29 收盘」「港股 2026-07-30 盘前」。
   *  别用 us_session 自己拼「XX 收盘」—— 港股在北京白天可能正在交易。 */
  us_label?: string | null;
  hk_label?: string | null;
}

/** 自选同步 HTTP 形状；条目与 watchlist.WatchItem 同一知识镜像 */
export interface WatchlistData {
  schema?: number;
  codes: string[];
  items?: WatchItem[];
  updated_at: string | null;
}

export const api = {
  health: () => get<{ ok: boolean }>("/health"),
  indices: () => get<IndexQuote[]>("/indices"),
  marketSession: () => get<MarketSession>("/market/session"),
  overseas: () => get<OverseasSnapshot>("/market/overseas"),
  liveEmotion: () => get<LiveEmotion>("/market/live-emotion"),
  shortBoard: () => get<ShortBoardSnapshot>("/market/short-board"),
  moodBlocks: () => get<MoodBlocksSnapshot>("/market/mood-blocks"),
  marketOverview: () => get<MarketOverview>("/market/overview"),
  emotion: () => get<ShortTermEmotion>("/market/emotion"),
  monitorSnapshot: (watch: string) => get<MonitorSnapshot>(`/monitor/snapshot?watch=${encodeURIComponent(watch)}`),
  watchlist: () => get<WatchlistData>("/watchlist"),
  saveWatchlist: (codes: string[]) => request<WatchlistData>("/watchlist", "PUT", { codes }),
  firstBoard: () => get<FirstBoardData>("/market/first-board"),
  parseZtReasons: (text: string) =>
    request<ZtReasonPreview>("/market/first-board/parse-reasons", "POST", { text }),
  importZtReasons: (text: string) =>
    request<{ ok: boolean; date: string; count: number; imported: number; skipped: number }>(
      "/market/first-board/import-reasons", "POST", { text }),
  turnoverTop: () => get<TurnoverTop>("/market/turnover-top"),
  globalIndices: () => get<GlobalIndex[]>("/global/indices"),
  globalStock: (symbol: string) => get<GlobalStock>(`/global/stock?symbol=${encodeURIComponent(symbol)}`),
  hkCashflow: (symbol: string) => get<HkCashflow>(`/global/hk/cashflow?symbol=${encodeURIComponent(symbol)}`),
  radar: () => get<RadarData>("/radar"),
  radarRefresh: () => request<RadarData>("/radar/refresh", "POST"),
  portfolio: () => get<PortfolioData>("/portfolio"),
  addHolding: (code: string, shares: number, cost: number) => request<PortfolioData>("/portfolio/holding", "POST", { code, shares, cost }),
  /** 按代码覆盖写入持仓（已存在则改，否则增） */
  setHolding: (code: string, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/holding", "POST", { code, shares, cost, upsert: true }),
  removeHolding: (code: string) => request<PortfolioData>(`/portfolio/holding?code=${code}`, "DELETE"),
  refreshPortfolio: () => request<PortfolioData>("/portfolio/refresh", "POST"),
  closePosition: (code: string, date: string, price: number, shares: number, cost: number) =>
    request<PortfolioData>("/portfolio/close", "POST", { code, date, price, shares, cost }),
  removeClosed: (index: number) => request<PortfolioData>(`/portfolio/close?index=${index}`, "DELETE"),
  tradePhases: () => get<{ phases: TradePhaseRow[] }>("/trade/phases"),
  tradeBudget: (date?: string, refresh = false) =>
    get<TradeBudget>(`/trade/budget?${date ? `date=${date}&` : ""}refresh=${refresh ? 1 : 0}`),
  tradeBudgetRefresh: (date?: string) =>
    request<TradeBudget>(`/trade/budget/refresh${date ? `?date=${date}` : ""}`, "POST"),
  tradeOverride: (date: string, phase: string | null, reason = "") =>
    request<TradeBudget>(`/trade/budget/override?date=${date}`, "POST", { phase, reason }),
  tradeAccount: () => get<TradeAccount>("/trade/account"),
  setTradeEquity: (equity: number, note = "") =>
    request<TradeAccount>("/trade/account/equity", "POST", { equity, note }),
  setTradeConstants: (c: Partial<TradeConstants>) =>
    request<TradeAccount>("/trade/account/constants", "POST", c),
  tradeSnapshot: (date: string, market_value: number, extra?: {
    account_fields?: TradeAccountFields;
    note?: string;
  }) =>
    request<TradeAccount>(`/trade/account/snapshot?date=${date}`, "POST", {
      market_value,
      ...(extra || {}),
    }),
  tradeGuard: (date?: string) =>
    get<TradeGuard>(`/trade/guard${date ? `?date=${date}` : ""}`),
  tradeSize: (body: { date?: string; stop_pct: number; boards?: number | null }) =>
    request<TradeSizeResult>("/trade/size", "POST", body),
  parseTradeScreenshot: (image_b64: string, llm: { provider: string; baseURL: string; apiKey: string; model: string }) =>
    request<{ ok: boolean; draft: ScreenshotDraft }>("/trade/screenshot/parse", "POST", { image_b64, llm }),
  applyTradeScreenshot: (body: {
    equity?: number | null;
    note?: string;
    account_fields?: TradeAccountFields;
    holdings: { code: string; shares: number; cost: number; include?: boolean }[];
    replace?: boolean;
  }) => request<{
    ok: boolean;
    account: TradeAccount;
    portfolio: PortfolioData;
    written_holdings: number;
    replace: boolean;
    snapshot_date?: string | null;
  }>("/trade/screenshot/apply", "POST", body),
  valuation: (code: string) => get<Valuation>(`/valuation?code=${code}`),
  percentile: (code: string) => get<ValPercentile>(`/valuation/percentile?code=${code}`),
  financials: (code: string) => get<Financials>(`/financials?code=${code}`),
  announcements: (code: string) => get<Announcement[]>(`/announcements?code=${code}`),
  quote: (codes: string) => get<Record<string, Quote>>(`/quote?codes=${codes}`),
  reports: (code: string) => get<Report[]>(`/reports?code=${code}`),
  news: (code: string) => get<NewsItem[]>(`/news?code=${code}`),
  margin: (code: string) => get<MarginRow[]>(`/margin?code=${code}`),
  blockTrade: (code: string) => get<BlockTradeRow[]>(`/block-trade?code=${code}`),
  holders: (code: string) => get<HolderRow[]>(`/holders?code=${code}`),
  dividend: (code: string) => get<DividendRow[]>(`/dividend?code=${code}`),
  fundFlow: (code: string) => get<FundFlowRow[]>(`/fund-flow?code=${code}`),
  dragonTiger: (code: string) => get<DragonTiger>(`/dragon-tiger?code=${code}`),
  lockup: (code: string) => get<Lockup>(`/lockup?code=${code}`),
  blocks: (code: string) => get<Blocks>(`/blocks?code=${code}`),
  hotConcepts: (code: string) => get<HotConcept[]>(`/hot-concepts?code=${code}`),
  investorQa: (code: string) => get<QaRow[]>(`/investor-qa?code=${code}`),
  industry: (top = 20) => get<IndustryData>(`/industry?top=${top}`),
  myReports: () => get<MyReport[]>("/myreports"),
  uploadReport: (name: string, contentB64: string) =>
    request<MyReport>("/myreports", "POST", { name, content_b64: contentB64 }),
  deleteReport: (id: string) => request<{ ok: boolean }>(`/myreports/${id}`, "DELETE"),
  backupStatus: () => get<BackupStatus>("/backup/status"),
  backupOpen: (kind: "root" | "cache" | "series") =>
    request<{ ok: boolean; path: string; kind: string }>("/backup/open", "POST", { kind }),
  backupExport: (destDir: string) =>
    request<BackupExportResult>("/backup/export", "POST", { dest_dir: destDir }),
  backupExportSeries: (destDir: string) =>
    request<SeriesExportResult>("/backup/export-series", "POST", { dest_dir: destDir }),
  backupImportPath: (path: string) =>
    request<BackupImportResult>("/backup/import", "POST", { path }),
  backupImportZip: (contentB64: string) =>
    request<BackupImportResult>("/backup/import", "POST", { content_b64: contentB64 }),
  stockUniverseStatus: () => get<StockUniverseStatus>("/config/stock-universe"),
  refreshStockUniverse: () =>
    request<StockUniverseStatus>("/config/stock-universe/refresh", "POST"),
  themeAliases: () => get<ThemeAliasConfig>("/config/theme-aliases"),
  saveThemeAliases: (entries: ThemeAliasEntry[]) =>
    request<ThemeAliasSaveResult>("/config/theme-aliases", "POST", { entries }),
  resetThemeAliases: () =>
    request<ThemeAliasSaveResult>("/config/theme-aliases/reset", "POST", {}),
  blockPending: () => get<BlockPendingConfig>("/config/block-pending"),
  saveBlockPendingAlias: (alias: string, canonical: string) =>
    request<ThemeAliasSaveResult>(
      "/config/block-pending/save-alias",
      "POST",
      { alias, canonical },
    ),
  ztKeywords: () => get<ZtKeywordConfig>("/config/zt-keywords"),
  saveZtKeywords: (keywords: string[]) =>
    request<{ keywords: string[]; count: number }>("/config/zt-keywords", "POST", { keywords }),
  resetZtKeywords: () =>
    request<{ keywords: string[]; count: number }>("/config/zt-keywords/reset", "POST", {}),
  messageFollowKeywords: () => get<MessageFollowKeywordConfig>("/config/message-follow-keywords"),
  saveMessageFollowKeywords: (keywords: string[]) =>
    request<{ keywords: string[]; count: number }>("/config/message-follow-keywords", "POST", { keywords }),
  resetMessageFollowKeywords: () =>
    request<{ keywords: string[]; count: number }>("/config/message-follow-keywords/reset", "POST", {}),
  tradePhaseConfig: () => get<TradePhaseConfig>("/config/trade-phases"),
  saveTradePhaseConfig: (phases: TradePhaseConfigRow[]) =>
    request<{ phases: TradePhaseConfigRow[]; count: number }>("/config/trade-phases", "POST", { phases }),
  resetTradePhaseConfig: () =>
    request<{ phases: TradePhaseConfigRow[]; count: number }>("/config/trade-phases/reset", "POST", {}),
  tradeThresholdConfig: () => get<TradeThresholdConfig>("/config/trade-thresholds"),
  saveTradeThresholdConfig: (thresholds: Record<string, number>) =>
    request<TradeThresholdConfig>("/config/trade-thresholds", "POST", { thresholds }),
  resetTradeThresholdConfig: () =>
    request<TradeThresholdConfig>("/config/trade-thresholds/reset", "POST", {}),
  sentimentSConfig: () => get<SentimentSConfig>("/config/sentiment-s"),
  saveSentimentSConfig: (method: string, opts?: { fusionintelApiKey?: string }) => {
    const body: Record<string, string> = { method };
    if (opts && "fusionintelApiKey" in opts) {
      body.fusionintel_api_key = opts.fusionintelApiKey ?? "";
    }
    return request<SentimentSConfig>("/config/sentiment-s", "POST", body);
  },
  refreshSentimentSSeries: (enrichLimit?: number | null) =>
    request<SentimentSRefreshResult>("/config/sentiment-s/refresh", "POST", {
      enrich_limit: enrichLimit === undefined ? 30 : enrichLimit,
    }),
  experienceMeta: () => get<ExperienceMeta>("/experience/meta"),
  experienceTopic: (name: string) =>
    get<ExperienceTopic>(`/experience/topic?name=${encodeURIComponent(name)}`),
  experienceRetrieve: (query: string, k = 3) =>
    request<ExperienceRetrieveResult>("/experience/retrieve", "POST", { query, k }),
  experienceCommit: (files: ExperienceDraftFile[]) =>
    request<ExperienceCommitResult>("/experience/commit", "POST", { files }),
  pluginsList: () => get<PluginsListResult>("/plugins"),
  pluginsPick: (initialDir?: string) =>
    request<PluginPickResult>("/plugins/pick", "POST", { initial_dir: initialDir || "" }),
  pluginsRegister: (path: string) =>
    request<PluginRecord>("/plugins/register", "POST", { path }),
  pluginsEnable: (plugin: string) =>
    request<PluginRecord>("/plugins/enable", "POST", { plugin }),
  pluginsDisable: (plugin: string) =>
    request<PluginRecord>("/plugins/disable", "POST", { plugin }),
  pluginsUninstall: (plugin: string) =>
    request<PluginRecord>("/plugins/uninstall", "POST", { plugin }),
  pluginsOpenDir: (plugin: string) =>
    request<{ ok: boolean; path: string }>("/plugins/open-dir", "POST", { plugin }),
  messageSources: () => get<MessageSourceInfo[]>("/messages/sources"),
  messageIngestPreview: (body: {
    format?: string;
    source_id?: string;
    text?: string;
    items?: Record<string, unknown>[];
    options?: Record<string, unknown>;
  }) => request<RawMessageDraft[]>("/messages/ingest/preview", "POST", body),
  messageIngestCommit: (drafts: RawMessageDraft[]) =>
    request<{ inserted: unknown[]; analyzed: AnalyzedMessage[] }>("/messages/ingest/commit", "POST", { drafts }),
  messageAnalyzedList: (params: {
    source?: string | string[];
    q?: string;
    from_dt?: string;
    to_dt?: string;
    impact_level?: string | string[];
    effect_status?: string | string[];
    status?: string | string[];
    favorited?: string | string[];
    followed?: string | string[];
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v === undefined || v === "") return;
      if (Array.isArray(v)) {
        const joined = v.filter(Boolean).join(",");
        if (joined) qs.set(k, joined);
        return;
      }
      qs.set(k, String(v));
    });
    const q = qs.toString();
    return get<MessageListResult>(`/messages/analyzed${q ? `?${q}` : ""}`);
  },
  messageAnalyzedDetail: (id: string) => get<AnalyzedMessageDetail>(`/messages/analyzed/${id}`),
  messageAnalyzedPatch: (id: string, patch: Partial<AnalyzedMessage>) =>
    request<AnalyzedMessage>(`/messages/analyzed/${id}`, "PATCH", patch),
  messageAnalyzedFavorite: (ids: string[], favorited = true) =>
    request<{ updated: number; favorited: boolean }>("/messages/analyzed/favorite", "POST", {
      ids,
      favorited,
    }),
  messageAnalyzedDelete: (ids: string[]) =>
    request<{ deleted: number }>("/messages/analyzed/delete", "POST", { ids }),
  messageAnalyzeQueue: (rawIds: string[], analyzedIds: string[] = []) =>
    request<{ job_ids: string[]; queued: number }>("/messages/analyze", "POST", {
      raw_ids: rawIds,
      analyzed_ids: analyzedIds,
    }),
  messageAnalyzeQueueStatus: () =>
    get<{ counts: Record<string, number>; pending: unknown[] }>("/messages/analyze/queue"),
  messagePollCls: (opts?: { backfill?: boolean }) =>
    request<ClsPollResult>(`/messages/poll/cls${opts?.backfill ? "?backfill=true" : ""}`, "POST"),
  messagePollXgb: () => request<XgbPollResult>("/messages/poll/xgb", "POST"),
  messageXgbResyncTargets: () => request<{ synced: number }>("/messages/xgb/resync-targets", "POST"),
  thsBlocksSnapshot: () => get<ThsBlocksSnapshot>("/ths-blocks"),
  thsBlocksRefresh: (ths_dir = "") =>
    request<ThsBlocksSnapshot>("/ths-blocks/refresh", "POST", ths_dir ? { ths_dir } : {}),
  thsBlocksRefreshKind: (kind: string, ths_dir = "") =>
    request<ThsBlocksSnapshot>(`/ths-blocks/refresh/${encodeURIComponent(kind)}`, "POST", ths_dir ? { ths_dir } : {}),
  thsBlockStocks: (kind: string, blockId: string) =>
    get<ThsBlockStocksDetail>(`/ths-blocks/stocks?kind=${encodeURIComponent(kind)}&block_id=${encodeURIComponent(blockId)}`),
  thsBlocksResolve: (names: string[]) =>
    request<BlockResolveResult>("/ths-blocks/resolve", "POST", { names }),
  thsBlocksIndexInfo: () => get<BlockIndexInfo>("/ths-blocks/index-info"),
  stocksResolve: (queries: StockResolveQuery[]) =>
    request<StockResolveResult>("/stocks/resolve", "POST", { queries }),
  stocksIndexInfo: () => get<StockIndexInfo>("/stocks/index-info"),
};

export interface PluginPickResult {
  cancelled: boolean;
  path?: string;
}

export interface PluginRuntimeStatus {
  level: "ok" | "info" | "warn" | "error" | "off";
  message: string;
  detail?: string;
  updated_at: string;
}

export interface PluginRecord {
  id: string;
  path: string;
  name: string;
  version: string;
  enabled: boolean;
  registered_at: string;
  file_exists: boolean;
  runtime_status: PluginRuntimeStatus;
}
export interface PluginsListResult {
  plugins: PluginRecord[];
  registry_file: string;
}

export interface ExperienceTopicMeta {
  filename: string;
  title: string;
  summary: string;
}
export interface ZtKeywordConfig {
  schema: number;
  keywords: string[];
  locked: string[];
  path: string;
  defaults: string[];
}
export interface MessageFollowKeywordConfig {
  schema: number;
  keywords: string[];
  path: string;
}

export interface ThsBlockRow {
  kind: string;
  kind_label: string;
  id: string;
  name: string;
  node_type: "branch" | "leaf" | "flat";
  tree_path: string;
  depth?: number;
  parent_id?: string | null;
  tree_order?: number;
  custom_type?: "static" | "dynamic";
  dynamic_kind?: "broker" | "concept" | "rule";
  query_key?: string;
  hex_id?: string;
  stock_count?: number;
}

export interface ThsTreeNode {
  id: string;
  name: string;
  node_type: "branch" | "leaf";
  children?: ThsTreeNode[];
}

export interface ThsBlockKindSnapshot {
  kind: string;
  kind_label: string;
  count: number;
  blocks: Record<string, string>;
  blocks_meta?: Record<string, Record<string, unknown>>;
  root_id?: string;
  root_name?: string;
  branch_count?: number;
  leaf_count?: number;
  tree_mode?: "tree" | "flat_fallback";
  tree?: Record<string, unknown>;
  rows: ThsBlockRow[];
}

export interface ThsBlocksSnapshot {
  updated_at: string | null;
  ths_dir: string | null;
  kinds: Record<string, ThsBlockKindSnapshot>;
  errors?: string[];
  empty?: boolean;
  linker_unavailable?: boolean;
  linker_message?: string;
}

export interface ThsBlockStockItem {
  code: string;
  market: string;
}

export interface ThsBlockRef {
  kind: string;
  kind_label: string;
  id: string;
  name: string;
}

export interface BlockResolveItem {
  raw: string;
  mapped: string;
  status: "empty" | "matched" | "partial" | "unmatched";
  block: ThsBlockRef | null;
  candidates: ThsBlockRef[];
}

export interface BlockIndexInfo {
  ready: boolean;
  complete?: boolean;
  ensuring?: boolean;
  refreshing?: boolean;
  linker_unavailable?: boolean;
  linker_message?: string;
  name_count: number;
  ref_count: number;
  updated_at?: string | null;
  ths_dir?: string | null;
}

export interface BlockResolveResult {
  items: BlockResolveItem[];
  by_raw: Record<string, BlockResolveItem>;
  index: BlockIndexInfo;
}

export interface StockRef {
  code: string;
  name: string;
  market: string;
  types: string[];
}

export interface StockResolveQuery {
  code?: string | null;
  name?: string | null;
}

export interface StockResolveItem {
  key: string;
  code?: string | null;
  name?: string | null;
  status: "empty" | "matched" | "unmatched";
  stock: StockRef | null;
}

export interface StockIndexInfo {
  ready: boolean;
  refreshing?: boolean;
  count: number;
  updated_at?: string | null;
  source?: string | null;
  error?: string | null;
}

export interface StockResolveResult {
  items: StockResolveItem[];
  by_key: Record<string, StockResolveItem>;
  index: StockIndexInfo;
}

export interface ThsBlockStocksDetail {
  kind: string;
  kind_label: string;
  block_id: string;
  name: string;
  count: number;
  stocks: ThsBlockStockItem[];
}
export interface ThemeAliasEntry {
  alias: string;
  canonical: string;
  type: string;
}
export interface ThemeAliasConfig {
  schema: number;
  aliases: Record<string, string>;
  types?: Record<string, string>;
  entries: ThemeAliasEntry[];
  path: string;
  defaults: Record<string, string>;
}
export interface ThemeAliasSaveResult {
  aliases: Record<string, string>;
  types: Record<string, string>;
  entries: ThemeAliasEntry[];
  count: number;
}
export interface BlockPendingCandidate {
  kind: string;
  kind_label: string;
  id: string;
  name: string;
}
export interface BlockPendingItem {
  raw: string;
  mapped: string;
  status: "partial" | "unmatched";
  candidates: BlockPendingCandidate[];
  suggested_canonical?: string;
  sources: string[];
  source_labels: string[];
  sort_rank: number;
  hit_count: number;
  updated_at: string;
}
export interface BlockPendingConfig {
  count: number;
  items: BlockPendingItem[];
  source_labels: Record<string, string>;
  updated_at: string;
}
export interface TradePhaseConfigRow {
  phase: string;
  cap_total: number;
  cap_single: number;
  prompt: string;
}
export interface TradePhaseConfig {
  schema: number;
  path: string;
  phases: TradePhaseConfigRow[];
  defaults: TradePhaseConfigRow[];
}
export interface TradeThresholdField {
  key: string;
  label: string;
  desc: string;
  value_kind: "ratio" | "number" | "count" | "boards" | "score";
  ref_key: string;
  value: number;
  default: number;
  min: number;
  max: number;
}
export interface TradeThresholdGroup {
  id: string;
  label: string;
  desc: string;
  fields: TradeThresholdField[];
}
export interface TradeThresholdRefItem {
  key: string;
  label: string;
  value: number | string | null;
  formatted: string | null;
}
export interface TradeThresholdConfig {
  schema: number;
  path: string;
  groups: TradeThresholdGroup[];
  values: Record<string, number>;
  defaults: Record<string, number>;
  reference: {
    date: string | null;
    readings: Record<string, unknown>;
    display: TradeThresholdRefItem[];
    reason?: string | null;
  };
}
export interface SentimentSMethod {
  id: string;
  label: string;
  desc: string;
  needs_api_key?: boolean;
}
export interface SentimentSSeriesMeta {
  days: number;
  enriched_days: number;
  miss_days?: number;
  pending_days?: number;
  highest_days?: number;
  broken_rate_days?: number;
  first?: string | null;
  last?: string | null;
  updated_at?: string | null;
}
export interface MarketSeriesBrief {
  days: number;
  first?: string | null;
  last?: string | null;
  updated_at?: string | null;
}
export interface SentimentSConfig {
  schema: number;
  path: string;
  method: string;
  methods: SentimentSMethod[];
  series_path: string;
  series_meta: SentimentSSeriesMeta;
  market_series?: {
    margin: MarketSeriesBrief;
    index: MarketSeriesBrief;
    needs_refresh?: string | null;
  };
  has_fusionintel_api_key?: boolean;
  fusionintel_api_key_masked?: string;
}
export interface SentimentSRefreshResult {
  ok: boolean;
  enriched_this_run: number;
  missed_this_run?: number;
  tried_this_run?: number;
  qcj_highest_filled?: number;
  xgb_broken_filled?: number;
  meta: SentimentSSeriesMeta;
  updated_at?: string;
  margin_joined?: number;
  market_refresh?: {
    ok?: boolean;
    skipped?: boolean;
    reason?: string | null;
    margin?: { ok?: boolean; days?: number; last?: string };
    index?: { ok?: boolean; days?: number; last?: string };
  };
}
export interface ExperienceMeta {
  root: string;
  index_path: string;
  topics: ExperienceTopicMeta[];
}
export interface ExperienceTopic extends ExperienceTopicMeta {
  content: string;
  path: string;
}
export interface ExperienceHit extends ExperienceTopicMeta {
  content: string;
  score: number;
}
export interface ExperienceRetrieveResult {
  hits: ExperienceHit[];
  context: string;
  k: number;
}
export interface ExperienceDraftFile {
  filename?: string;
  title: string;
  summary: string;
  content: string;
}
export interface ExperienceCommitResult {
  ok: boolean;
  root: string;
  written: (ExperienceTopicMeta & { path: string })[];
  topics: ExperienceTopicMeta[];
}

export interface BackupFolder {
  name: string; files: number; bytes: number;
}
export interface SeriesOverviewItem {
  name: string;
  days: number;
  first?: string | null;
  last?: string | null;
  updated_at?: string | null;
  source?: string | null;
}
export interface SeriesOverview {
  db_path: string;
  byte_count: number;
  total_days: number;
  series: SeriesOverviewItem[];
}
export interface BackupStatus {
  root: string; cache_dir: string; exists: boolean;
  file_count: number; byte_count: number; skipped_logs: number;
  folders: BackupFolder[];
  series?: SeriesOverview;
}
export interface BackupExportResult {
  ok: boolean; path: string; filename: string;
  file_count: number; byte_count: number; skipped_logs: number;
  created_at?: string;
}
export interface SeriesExportResult {
  ok: boolean; path: string; file_count: number; row_count: number;
  files: string[]; db_path: string;
}
export interface BackupImportResult {
  ok: boolean; imported: number; byte_count: number;
  skipped_logs: number; root: string;
}

export interface StockUniverseSource {
  id: string;
  label: string;
}

export interface StockUniverseStatus {
  loaded: boolean;
  refreshing: boolean;
  count: number;
  source?: string | null;
  from_cache?: boolean;
  updated_at?: string | null;
  cache_path: string;
  cache_exists: boolean;
  read_order: StockUniverseSource[];
  network_sources: string[];
  error?: string | null;
  started?: boolean;
}

export async function downloadBackup(): Promise<string> {
  const resp = await fetch(apiUrl("/api/backup/download"), { headers: authHeaders() });
  if (!resp.ok) {
    let detail = `下载失败 HTTP ${resp.status}`;
    try {
      const payload = await resp.json();
      detail = payload?.detail || payload?.error || detail;
    } catch {
      /* 非 JSON */
    }
    throw new ApiError(detail, resp.status);
  }
  const blob = await resp.blob();
  const cd = resp.headers.get("content-disposition") || "";
  const matched = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(cd);
  const filename = matched ? decodeURIComponent(matched[1]) : "duanxian-agents-backup.zip";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return filename;
}
