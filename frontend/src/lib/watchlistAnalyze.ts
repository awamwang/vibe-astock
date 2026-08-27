import type { Quote } from "@/lib/api";

const pct = (v: number | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v}%`);

/** 自选股行内 AI 分析共用的合规约束（须与 README 对外承诺一致） */
export const WATCHLIST_PROMPT_COMPLIANCE =
  "个股层面只陈述已经发生的客观数据与事实，方向与强弱判断做到题材板块层面为止：" +
  "不预测个股涨跌、不给个股参与倾向、不推荐任何标的、不构成投资建议。" +
  "输出用纯 Markdown（不要在表格或正文里使用 <br> 等 HTML 标签）。";

const quoteBlock = (code: string, q: Quote | undefined) =>
  `今天 A 股自选股「${q?.name || code}（${code}）」的客观数据：\n` +
  `现价 ${q?.price ?? "—"} 元，涨跌 ${q?.change_pct != null ? pct(q.change_pct) : "—"}，` +
  `PE(TTM) ${q?.pe_ttm ?? "—"}，PB ${q?.pb ?? "—"}，换手率 ${q?.turnover_pct ?? "—"}%，` +
  `流通市值 ${q?.mcap_yi != null ? `${q.mcap_yi} 亿` : "—"}。`;

/** 投研向深入分析 user prompt */
export function buildWatchlistDeepPrompt(code: string, q: Quote | undefined): string {
  return (
    `${quoteBlock(code, q)}\n\n` +
    "请深入分析这只股票：\n" +
    "1. 先调用工具查询这只股票的近期新闻、研报与估值数据，结合上面的行情数据，说清当前关注点的驱动因素（消息面 / 基本面 / 资金面）；\n" +
    "2. 就**这个题材板块整体**说清它的强度与所处阶段（情绪性炒作 / 有产业逻辑或业绩支撑），" +
    "并给出依据 —— 只讲题材板块层面，不要由此推断这只个股接下来会怎样；\n" +
    "3. 客观列出值得注意的点（估值水平、换手活跃度、近期催化与风险）。\n" +
    WATCHLIST_PROMPT_COMPLIANCE
  );
}

/** 短线向单票观察 user prompt */
export function buildWatchlistShortPrompt(code: string, q: Quote | undefined): string {
  return (
    `${quoteBlock(code, q)}\n\n` +
    "请按下面顺序做**单票短线观察**（只陈述已发生事实与相对位置，不给买卖结论）：\n\n" +
    "0. 先调用工具补全：query_kline（60 日）、query_fund_flow、query_concepts、" +
    "query_news、query_dragon_tiger（有则写，无则说明缺失）。\n\n" +
    "1. **价格与量能结构**（个股）：近 5/20 日涨跌、振幅、换手变化；是否放量/缩量；" +
    "K 线结构（趋势/箱体/突破/回调，基于工具返回，勿捏造）。\n\n" +
    "2. **技术位置**（个股，只解读不预测）：相对近期高低点的位置；工具若未提供 MACD/RSI 则说明「未覆盖」。\n\n" +
    "3. **资金与筹码**（个股）：近 5/20 日主力净流入方向与强度；龙虎榜/大宗：有则陈述，无则说明。\n\n" +
    "4. **题材内相对位置**（个股 vs 同题材，仍不推断个股走势）：所属概念/行业；" +
    "客观标注更像龙头/中军/跟风/独立逻辑（依据已发生事实）。\n\n" +
    "5. **驱动归因**（个股）：新闻/公告与题材逻辑是否一致。\n\n" +
    "6. **值得注意的点 vs 风险点**（个股事实）。\n\n" +
    "7. **就「这个题材板块整体」** 说清强度与阶段（情绪炒作 / 产业支撑 / 分歧期）" +
    " —— 只到板块层，不要由此推断这只个股接下来会怎样。\n\n" +
    "输出必须先三行固定摘要，再写正文：\n" +
    "【题材角色】xxx\n" +
    "【量能状态】xxx\n" +
    "【技术结构】xxx\n" +
    "题材角色必须从「龙头、中军、跟风、独立、不明」中**精确选一个并原样抄写**。" +
    "量能状态必须从「放量、缩量、平量、不明」中**精确选一个并原样抄写**。" +
    "技术结构必须从「上升、震荡、回调、不明」中**精确选一个并原样抄写**。\n\n" +
    WATCHLIST_PROMPT_COMPLIANCE
  );
}

export function watchlistDeepContext(code: string, q: Quote | undefined): string {
  return `自选股 ${q?.name || code}(${code}) 深入分析`;
}

export function watchlistShortContext(code: string, q: Quote | undefined): string {
  return `自选股 ${q?.name || code}(${code}) 短线观察`;
}
