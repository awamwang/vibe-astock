// 直播盘面 view-model：打板情绪、环境条、连板股、场次分属不同概念（ADR-0001），仅共用场次。
// 类型与 typed fetch 收拢于此；HTTP 路径与 JSON 字段名不变。传输层见 api.request。

import { request } from "./api";

// ---------- 场次 ----------
/** 此刻的「实时行情」属于哪一场 —— 盘前行情返回的是上一场收盘，UI 要如实标注 */
export interface MarketSession {
  now: string;
  today: string;
  /** 实时行情代表的交易日；取不到时为 null */
  quotes_of: string | null;
  is_today: boolean;
  phase: string;
  /** 直接可展示的一句话，如「盘前 · 显示 2026-07-29 收盘」 */
  label: string;
}

// ---------- 打板情绪（live_emotion snapshot）----------
/** 今日实时打板情绪（盘面数据页）—— 与 ShortTermEmotion（已收盘那一场）分开 */
export interface LiveEmotionYesterday {
  zt_count?: number | null;
  dt_count?: number | null;
  zb_count?: number | null;
  max_boards?: number | null;
  lianban_count?: number | null;
  seal_rate?: number | null;
  break_rate?: number | null;
  promotion_rate?: number | null;
  promotion_base?: number | null;
}

export interface LiveEmotion {
  available: boolean;
  reason?: string;
  /** 左侧对照所属场次（周末/盘前为最近已收盘日，非日历今天） */
  date?: string;
  /** 快照时刻 HH:MM */
  as_of?: string;
  phase?: string;
  /** 日历今天是否就是这场（仅此时后端写归档） */
  is_live?: boolean;
  zt_count?: number;
  dt_count?: number | null;
  zb_count?: number | null;
  max_boards?: number;
  lianban_count?: number;
  seal_rate?: number | null;
  break_rate?: number | null;
  promotion_rate?: number | null;
  /** 晋级率的分母：上一场的涨停家数 */
  promotion_base?: number | null;
  /** 分母是哪一场。两张卡都叫「晋级率」，而各自的「昨」不是同一天，所以把日期给出来写死 */
  promotion_base_date?: string | null;
  /** 上一交易日（本地归档对照用） */
  prev_date?: string | null;
  /** 上一交易日收盘归档；无归档时为空对象，界面显示 /- */
  yesterday?: LiveEmotionYesterday;
}

// ---------- 环境条（short_board snapshot）----------
/** 短线盘面环境指标（今日 / 昨日对照，单位见各字段注释） */
export interface ShortBoardEnv {
  temperature?: number | null;  // 情绪温度 0-100（选股宝）
  n_up?: number | null;
  n_down?: number | null;
  n_sjzt?: number | null;       // 实际涨停
  n_sjdt?: number | null;       // 实际跌停
  v_sh?: number | null;         // 上证成交额，元
  v_ca?: number | null;         // A 股成交额，元
  m_net?: number | null;        // 主力净流入，元
  broken_r?: number | null;     // 炸板率，已 *100
  zt_avg_zr?: number | null;    // 涨停溢价，已 *100
  broken_c?: number | null;
  /** 趣财经情绪分 0–100（App「xx°」） */
  qcj_temp?: number | null;
  /** 趣财经阶段：冰点期 / 修复期 / 升温期 / 高潮期 / 降温期 / 退潮期 */
  qcj_level?: string | null;
  qcj_zt?: number | null;       // 趣财经涨停家数
  qcj_dt?: number | null;       // 趣财经跌停家数
  qcj_leader?: string | null;   // 龙头
  qcj_leader_top?: string | null; // 如「3天3板」
  qcj_themes?: string[] | null; // 主线题材
  qcj_date?: string | null;
}

export interface ShortBoardSnapshot {
  available: boolean;
  reason?: string | null;
  /** 左侧对照所属场次（周末为周五） */
  date?: string;
  /** 右侧对照场次（周末为周四） */
  prev_date?: string | null;
  /** 日历今天是否就是这场（仅此时后端写归档） */
  is_live?: boolean;
  today: ShortBoardEnv;
  yesterday: ShortBoardEnv;
  updated?: string;
  placeholders?: {
    volume_vs_yesterday?: boolean;
    volume_5d_ratio?: boolean;
  };
}

// ---------- 开盘啦板块人气（与环境条同页，非打板情绪）----------
/** 开盘啦板块人气一行（对齐 awam MoodBlockItem） */
export interface MoodBlockItem {
  code: string;
  name: string;
  power: number | null;   // 人气
  pct: number | null;     // 涨跌幅 %
  speed: number | null;   // 涨速 %
  m_net: number | null;   // 主力净额，元
  zt: number | null;      // 涨停家数
  sort: number;
}

export interface MoodBlocksSnapshot {
  available: boolean;
  reason?: string | null;
  date?: string;
  api_time?: number | null;
  blocks: MoodBlockItem[];
  updated?: string;
}

// ---------- 连板股（客观榜单；与打板情绪 / 环境条分属三处）----------
export interface EmotionTier { boards: number; count: number; plus: boolean }
export interface LianbanStock {
  code: string; name: string; boards: number;
  price: number; pct: number; amount: number | null; float_cap: number | null; industry: string;
  reason: string;  // 涨停原因题材串（同花顺涨停池主源；失败为空串）
}
/** 短线情绪：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数 + 连板股清单（客观公开榜单） */
export interface ShortTermEmotion {
  date: string;
  zt_count: number; dt_count: number; zb_count: number;
  max_boards: number; lianban_count: number;
  ladder: EmotionTier[];
  lianban_stocks: LianbanStock[];
  seal_rate: number | null; break_rate: number | null; promotion_rate: number | null;
  yzt_count: number;
}

// ---------- typed fetch（路径与字段名不变）----------
export const fetchMarketSession = () =>
  request<MarketSession>("/market/session");

export const fetchLiveEmotion = () =>
  request<LiveEmotion>("/market/live-emotion");

export const fetchShortBoard = () =>
  request<ShortBoardSnapshot>("/market/short-board");

export const fetchMoodBlocks = () =>
  request<MoodBlocksSnapshot>("/market/mood-blocks");

export const fetchLianbanEmotion = () =>
  request<ShortTermEmotion>("/market/emotion");
