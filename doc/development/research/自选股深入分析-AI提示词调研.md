# 自选股深入分析：AI 提示词调研

> 日期：2026-08-27。范围：面向**单只个股**的短线观察型 AI 提示词（非大盘情绪周期、非买卖决策）；对照本仓库自选股 / 首板 / 连板页的 `DeepDive` 实现、`vr/chat.py` 工具暴露与合规测试约束。不涉及个股推荐或买卖点。

## 结论摘要

- **自选股「深入分析」当前偏中线投研，不是短线口径**：user prompt 要求新闻/研报/估值 + 题材板块阶段；system 为 `vr/chat.py` 五维投研框架（估值/资金/财报/行业/事件）。与短线单票观察需求错位。
- **本仓库已有更好的单票短线 prompt 模板**：`FirstBoard.tsx`（首板）、`ShortBoard.tsx`（连板）已注入板位、封板时间、炸板次数、题材串等硬数据，并有结构化摘要行；`Watchlist.tsx` 仅有现价/PE/PB/换手/市值，最弱。
- **网上面向个股的短线 prompt 主流结构**：单票硬数据预填 + 价量/技术/资金/题材内角色/事件 五维观察 + 结构化摘要 + 证伪条件；指标由服务端预计算，LLM 只解读不推算。
- **不宜原样照搬的来源**：含 `action/BUY/SELL`、止损止盈、仓位、次日溢价/连板概率 的模板（如 DeepSeek 龙头战法 CSDN 文、limit-up-dao 的「次日展望」）——与 README 承诺及 `TestPerStockPromptsStayAtSectorLevel` 冲突。
- **工具链缺口**：`vr/tools.py` 已有 `query_kline`、`query_fund_flow`、`query_dragon_tiger`、`query_concepts` 等单票短线工具，但 `/api/chat`（`vr/chat.py`）仅暴露 `query_quote/valuation/reports/news/query_global_stock` 五个。
- **落地建议**：以首板 prompt 为母版改造自选股；扩展 chat 工具或预填 K 线/资金流摘要；可选增加 `【题材角色】【量能状态】【技术结构】` 三行摘要供 UI 解析。

---

## 1. 本仓库现状

### 1.1 调用链

| 环节 | 位置 | 说明 |
|------|------|------|
| 前端 prompt | `frontend/src/pages/Watchlist.tsx` `buildPrompt` | 注入当日行情，发起深入分析 |
| 页面 context | 同文件 `ctx()` | 如 `自选股 贵州茅台(600519) 深入分析` |
| 流式请求 | `frontend/src/lib/llm.ts` → `POST /api/chat` | NDJSON 流 |
| System prompt | `vr/chat.py` `SYSTEM_PROMPT` + `ANALYSIS_FRAMEWORK` | 五维投研 + 合规硬性规则 |
| 工具循环 | `vr/chat.py` `run_chat_stream` | API 接入最多 6 轮 function calling |
| 本地存档 | `frontend/src/components/ui/DeepDive.tsx` | localStorage，键 `${date}|watchlist|${code}`，保留 5 个交易日 |

### 1.2 自选股当前 user prompt（要点）

- **预填数据**：现价、涨跌、PE(TTM)、PB、换手、流通市值。
- **任务**：
  1. 调工具查新闻/研报/估值，说清驱动（消息/基本/资金）；
  2. 就**题材板块整体**说强度与阶段（情绪炒作 vs 产业/业绩支撑）；
  3. 客观列估值、换手、催化与风险。
- **合规**：个股只陈述事实；强弱判断到板块层；不预测涨跌、不给参与倾向。

### 1.3 首板 / 连板 prompt（单票短线，更完整）

**首板**（`FirstBoard.tsx`）额外包含：

- 板位、封板时间、炸板次数、成交额、流通市值、行业、题材标签、涨停原因串；
- 固定摘要三行：`【涨停关键字】【持续性】【题材新旧】`（关键字来自闭集 `ztKeywords`）；
- 正文要求：驱动归因、板块强度、题材是否被炒过、炸板/封板时间/连板高度等客观点。

**连板**（`ShortBoard.tsx`）额外包含：

- 连板天数、收盘/实时价、驱动是否随板位变化、成交额放大/缩量等。

### 1.4 合规测试约束

`tests/test_core_logic.py` → `TestPerStockPromptsStayAtSectorLevel` 对 `FirstBoard.tsx`、`ShortBoard.tsx`、`Watchlist.tsx` 强制：

- 含「这个题材板块整体」「不要由此推断这只个股接下来会怎样」；
- 含完整合规原文（不预测个股涨跌、不给个股参与倾向等）。

任何自选股 prompt 改版必须保留上述措辞，否则 CI 失败。

### 1.5 工具暴露对比

| 工具 | 单票短线价值 | `vr/tools.py` | `vr/chat.py` `/api/chat` |
|------|-------------|---------------|--------------------------|
| `query_quote` | 行情 | ✅ | ✅ |
| `query_valuation` | 估值/一致预期 | ✅ | ✅ |
| `query_reports` / `query_news` | 事件 | ✅ | ✅ |
| `query_kline` | 趋势/区间涨跌/振幅 | ✅ | ❌ |
| `query_fund_flow` | 主力净流入 | ✅ | ❌ |
| `query_dragon_tiger` | 龙虎榜 | ✅ | ❌ |
| `query_concepts` | 题材归属 | ✅ | ❌ |
| `query_margin` / `query_holders` | 杠杆/筹码 | ✅ | ❌ |
| `query_market(emotion)` | 大盘情绪 | ✅ | ❌ |

CLI 订阅接入无 function calling，完全依赖 prompt 内已有数据 + context。

---

## 2. 大盘向 vs 个股向 prompt（区分）

上一轮调研中偏**市场整体**的框架（仍有用，但不适用于单票深入分析主体）：

| 类型 | 典型内容 | 本仓库对应 |
|------|---------|-----------|
| 情绪周期 | 冰点/修复/发酵/亢奋/退潮、晋级率、炸板率 | `duanxian/analysts.py` 情绪面分析师、`doc/research/短线情绪周期-AI判定方法.md` |
| 固定决策顺序（大盘→板块） | TradeRank 式 cascade | 适合板块层，需下沉到「个股在题材内角色」 |
| PromptPack 裁判 | `duanxian/prompts.py` `judge_requirements` | 每日复盘，非自选股 DeepDive |

**个股向** prompt 应回答：这只票价量结构如何、资金谁在动、在题材里是龙头还是跟风、有什么事件催化——而不是先讲一遍全市场情绪档位。

---

## 3. 外部调研：面向个股的短线 prompt 模式

### 3.1 共性维度（2025–2026 社区 / 开源）

| 维度 | 典型输入 | 说明 |
|------|---------|------|
| 价格/量能 | 涨跌、换手、量比、成交额、振幅 | 放量/缩量、异常活跃 |
| 技术位置 | MA 排列、MACD/RSI/KDJ、支撑压力、ATR | **须预计算**，LLM 只解读 |
| 涨停/连板特有 | 板位、封板时间、炸板次数 | 封板质量 |
| 资金/筹码 | 主力净流入、龙虎榜、大宗、两融、股东户数 | 资金性质 |
| 题材内角色 | 同板块涨停数、启动早晚、高度是否最高 | 龙头/中军/跟风（相对同题材） |
| 消息/事件 | 新闻、公告、研报、涨停原因 | 驱动归因 |
| 证伪条件 | 「若出现 X 则当前观察框架失效」 | 可审计 |

### 3.2 代表性来源

| 来源 | 链接 | 单票程度 | 可采纳 | 不宜照搬 |
|------|------|---------|--------|---------|
| limit-up-dao 涨停归因 | [GitHub laozdao/limit-up-dao](https://github.com/laozdao/limit-up-dao) | ⭐⭐⭐⭐⭐ | 五维观察：消息/资金/封板质量/板块共振/连板位置 | 「次日溢价」「连板概率」 |
| DeepSeek 龙头战法模板 | [CSDN 2026-04](https://gitcode.csdn.net/69f073e00a2f6a37c5a692ed.html) | ⭐⭐⭐⭐ | 结构化单票输入字段（MA/MACD/量比/压力支撑） | 买卖/仓位/止损止盈 |
| 股票分析师智能体提示词 | [CSDN kingtok](https://blog.csdn.net/kingtok/article/details/158620317) | ⭐⭐⭐⭐ | 系统算指标 + prompt 写死解读规则 | 直接输出 BUY/SELL |
| SuperColony Agent GUIDE | [GitHub GUIDE.md](https://github.com/TheSuperColony/supercolony-agent-starter/blob/main/GUIDE.md) | ⭐⭐⭐ | Role + 结构化单资产数据 + what would change your mind | JSON signal 执行 |
| TradeRank 图表分析模板 | [traderank.ai](https://www.traderank.ai/blog/ai-trading-prompts-engineering) | ⭐⭐ | 固定 numbered 顺序、冲突则 no-trade | /crypto 周期表述需改 A 股 |
| DeepPulse | [GitHub wwyharry/DeepPulse](https://github.com/wwyharry/DeepPulse) | ⭐⭐⭐ | 单票+战法库匹配、技术指标预计算 | 完整产品架构，非 prompt 片段 |
| a-stock-pattern-review skill | [implexa.ai](https://implexa.ai/s/clawhub/a-stock-pattern-review) | ⭐⭐ | 身位高标/弹性核心/容量中军分类 | 含操作预案表述 |
| 用 GPT 辅助炒股（中文） | [jiaocaiw.com](https://www.jiaocaiw.com/chatgpt/3922.html) | ⭐⭐ | 多空双方逻辑、不给直接预测 | 通用原则 |

### 3.3 业界 prompt 工程原则（单票适用）

1. **预计算再喂模型**：RSI/MACD/晋级率等不要让 LLM 从原始 K 线推算（TradeRank、CSDN 技术智能体均强调）。
2. **固定 numbered 顺序**：避免 open-ended「帮我分析一下」导致跳步或 cherry-pick。
3. **结构化摘要行**：便于 UI 解析（本仓库首板已实践：`parseDiveMeta`）。
4. **证伪条件**：必须写出「什么客观事实出现则当前观察失效」。
5. **合规边界**：GPT 辅助炒股类教程共识——分析工具非决策者；vibe-astock 额外要求强弱判断止步板块层。

---

## 4. 推荐：自选股「单票短线观察」prompt 框架（合规版）

在保留 `TestPerStockPromptsStayAtSectorLevel` 必需原文前提下，融合 limit-up-dao 五维 + 首板摘要 + 技术智能体解读规则：

```text
今天 A 股自选股「{name}（{code}）」已知客观数据：
- 行情：现价 / 涨跌 / 换手 / 流通市值
- （若有）PE/PB

请按下面顺序做**单票短线观察**（只陈述已发生事实与相对位置，不给买卖结论）：

0. 先调用工具补全：query_kline(60日) / query_fund_flow / query_concepts /
   query_news / query_dragon_tiger（有则写，无则说明缺失）

1. **价格与量能结构**（个股）
   - 近 5/20 日涨跌、振幅、换手变化；是否放量/缩量
   - K 线结构：趋势/箱体/突破/回调（基于工具返回，勿捏造）

2. **技术位置**（个股，只解读不预测）
   - 相对 MA5/20/60 的位置；MACD/RSI/KDJ 若工具未提供则说明「未覆盖」
   - 近 20 日高/低点距离（支撑压力的事实描述）

3. **资金与筹码**（个股）
   - 近 5/20 日主力净流入方向与强度
   - 龙虎榜/大宗/股东户数：有则陈述，无则说明

4. **题材内相对位置**（个股 vs 同题材，仍不推断个股走势）
   - 所属概念/行业；与同题材相比：启动早晚、涨幅/换手是否领先
   - 客观标注：更像龙头/中军/跟风/独立逻辑（依据已发生事实）

5. **驱动归因**（个股）
   - 新闻/公告/研报：消息驱动权重
   - 与题材逻辑是否一致

6. **值得注意的点 vs 风险点**（个股事实）

7. **就「这个题材板块整体」** 说清强度与阶段（情绪炒作 / 产业支撑 / 分歧期）
   —— 只到板块层，不要由此推断这只个股接下来会怎样

固定摘要（输出开头三行，供 UI 解析）：
【题材角色】龙头 / 中军 / 跟风 / 独立 / 不明
【量能状态】放量 / 缩量 / 平量 / 不明
【技术结构】上升 / 震荡 / 回调 / 不明

个股层面只陈述已经发生的客观数据与事实，方向与强弱判断做到题材板块层面为止：
不预测个股涨跌、不给个股参与倾向、不推荐任何标的、不构成投资建议。
输出用纯 Markdown（不要在表格或正文里使用 <br> 等 HTML 标签）。
```

### 4.1 与首板 prompt 的差异

| 项 | 首板 | 建议自选股 |
|----|------|-----------|
| 预填 | 板位、封板时间、炸板 | 通用行情 + 可选 K 线/资金摘要 |
| 摘要行 | 涨停关键字/持续性/题材新旧 | 题材角色/量能状态/技术结构 |
| 工具 | news/reports | + kline/fund_flow/concepts/dragon_tiger |
| 板块层判断 | 要求 | 同样要求（合规） |

---

## 5. 落地路径建议

| 优先级 | 动作 | 文件/模块 |
|--------|------|-----------|
| P0 | 按 §4 改写 `buildPrompt` | `frontend/src/pages/Watchlist.tsx` |
| P0 | 合规原文保持不变 | 同上 + `tests/test_core_logic.py` |
| P1 | `/api/chat` 暴露单票短线工具 | `vr/chat.py` 从 `vr/tools.py` 增挂 |
| P1 | 或后端预填 K 线/资金流摘要进 user prompt | 新 API 或扩展 `useLiveQuotes` |
| P2 | 扩展 `parseDiveMeta` 解析新摘要行 | `DeepDive.tsx` |
| P2 | 区分「投研深析」与「短线观察」两套 PromptPack | `~/.vibe-astock/prompts_local.py` 或页面级 |

---

## 6. 相关文档与代码索引

| 资源 | 路径 |
|------|------|
| 大盘情绪周期调研（非本文主体） | `doc/research/短线情绪周期-AI判定方法.md` |
| 自选股 prompt | `frontend/src/pages/Watchlist.tsx` |
| 首板 prompt（单票短线参考母版） | `frontend/src/pages/FirstBoard.tsx` |
| 连板 prompt | `frontend/src/pages/ShortBoard.tsx` |
| DeepDive 组件 | `frontend/src/components/ui/DeepDive.tsx` |
| Chat system + 工具 | `vr/chat.py` |
| 完整工具定义 | `vr/tools.py` |
| 合规测试 | `tests/test_core_logic.py` → `TestPerStockPromptsStayAtSectorLevel` |
| 每日复盘短线分析师 | `duanxian/analysts.py` |
| Prompt 包机制 | `duanxian/prompts.py` |

---

## 7. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-08-27 | 初稿：自选股 DeepDive 现状、个股向外部调研、合规版推荐框架与落地建议 |
| 2026-08-27 | 已落地：自选股页「深度分析 / 短线分析」双按钮 + 标签页切换；`lib/watchlistAnalyze.ts`；`/api/chat` 增挂 K 线/资金流/概念/龙虎榜工具 |
