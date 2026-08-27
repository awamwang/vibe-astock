# 短线情绪周期：AI 判定方法调研

> 日期：2026-08-25。范围：A 股题材/涨停短线情绪周期（退潮→冰点→修复→升温→高潮→过热→退潮）的判定方法，含规则/分位/HMM/分类/LLM 与可迁移学术方法；对照本仓库现有 S 算法与 Cap 定档，不涉及个股推荐或买卖点。

## 结论摘要

- **产品选型优先「结构化涨停生态 → 分位/规则 → 显式阶段」**：本仓库已具备 L0 `hard_rules` 与 L1 `percentile_qcj_em` / `qcj_degree`；下一步应做 L2「六档状态机 / 轻量 HMM」，而不是先上深度模型或宏观恐贪。
- **宏观恐贪（FusionIntel / 百分位网九分项系）不宜单独当短线 Cap 闸门**：官方口径均为指数级风险偏好，与连板高度、炸板率、1进2 晋级同频性弱；本仓库已接 `fusionintel` 作可选对照即可，不宜默认。
- **券商金工更接近「连续择时仓位」而非「六档 Cap」**：国泰海通（2025-05）用涨跌停占比、打板收益等合成择时信号，输出是仓位/择时组合，不是冰点/高潮分档；可借鉴特征，勿直接抄阈值。
- **HMM / 变点检测适合做「周期切换提示」**：Hamilton（1989）、Adams & MacKay（2007 BOCPD）、Killick et al.（2012 PELT）提供一手方法论；输入应是本仓库已有日频打板特征向量，输出为 regime 概率，再映射到现有六档，而不是替换 Cap 表。
- **有监督阶段分类可行但缺标签权威**：游资圈阶段定义为通识（阈值常与本系统接近），无单一白皮书；可用规则档作弱标签训练，必须样本外验证，否则易过拟合近期题材结构。
- **FinBERT / LLM 适合解释与另类特征，不适合单独执行闸**：FinBERT（Araci, 2019）、异构 LLM Agent FSA（Xing, 2024）、TwinMarket（Yang et al., 2025）等为一手证据；文本情绪滞后且噪声大，本仓库刻意隔离预算与 AI prompt 的边界应保持。
- **不推荐**：九分项宏观恐贪直接套短线档位；仅用 LLM 无结构化特征；未样本外验证的 LSTM/Transformer 黑盒当执行闸。
- **落地排序建议**：校准 L1 分位阈值 → L2 状态机（含修复确认硬字段）→ 可选 HMM 切换概率 → L3 弱监督分类实验 → L4 LLM 只写 `classify_reasons` 旁白。

---

## 1. 短线情绪周期在盘面/文献中的定义

### 1.1 盘面通识（游资/超短语境）

A 股短线「情绪周期」指的是**打板资金群体行为的阶段性反馈环**：赚钱效应扩张 → 连板高度抬升与题材扩散 → 过热/一致性 → 炸板与亏钱效应扩散 → 高度坍塌与冰点 → 再修复。这与宏观恐贪（波动、两融、宽度、RSI 等）不是同一对象。

公开可核验文字中，阶段划分多为 4–5 档，特征高度重合：

| 阶段（常见叫法） | 典型盘面特征（公开教程/财富号共识量级） | 与本仓库六档对应 |
|---|---|---|
| 冰点 / 低位震荡 | 涨停稀（常 <30）、高度压在 2–3 板、炸板偏高、主线沉寂 | 冰点观察 |
| 启动 / 试错 / 修复 | 亏钱效应减弱、出现反包/新题材首板、高度回升 | 修复确认（本仓库仅手拨） |
| 主升 / 升温 | 晋级顺畅、涨停扩散、高度 3–5 | 升温扩张 |
| 高潮 | 高度 ≥5、跟风密、赚钱效应强 | 高潮拥挤 |
| 分歧 / 过热 | 炸板抬升、高位一致性、跟风失败增多 | 过热防守 |
| 退潮 | 高度压降 + 亏钱扩散、跌停增多、核按钮批量 | 退潮杀伤 |

可引用的公开表述示例（非学术权威，但是一手产品/栏目文字）：

- 趣财经产品页明确面向「超短情绪周期」「冰点/高潮」「连板晋级」：[qucj.com](https://qucj.com/)（秒级情绪值、连板天梯）。
- 九方智投公开课讲义对启动/高潮/退潮/冰点的盘面描述：[情绪周期 5 大阶段](https://wap.9fzt.com/article/e4348b0acba658928af2721d8522cb73-9fztgw_1_top.html)。
- 东财财富号实操版用涨停家数、连板高度、炸板率、跌停、赚钱效应判定四阶段：[A股情绪周期判断体系](https://caifuhao.eastmoney.com/news/20260314093054692373420)。

**重要边界**：本仓库 `doc/仓位预算-定档规则.md` 已写明——六档框架是游资圈通识，**没有单一论文可追到「发明人」**；源文档判定列标了「（示例）」。阈值（涨停 <30、炸板 ≥40%、高度 ≥5 等）属于工程约定，不是交易所标准。

### 1.2 券商金工：涨停生态 → 择时，不是分档 Cap

**国泰海通证券**郑雅斌 / 余浩淼 / 曹君豪，《大类资产与中观配置研究（五）——从涨停板、“打板策略”到赚钱效应引发的情绪择时指标》，2025-05-14。

一手摘要来源（研报公众号转载，含分析师资格号）：[腾讯新闻转载国泰海通研究](https://news.qq.com/rain/a/20250515A09EJF00)。

核心 claim（可追溯到该文）：

- 输入：涨停占比、跌停占比、净涨停占比、打板策略收益、跌停次日收益等。
- 判定：多因子信号整合 + 可选趋势过滤 + 因子加权。
- 输出：**连续型择时/仓位组合收益**（文中给出年化、波动、回撤相对 Wind 全 A），**不是**冰点/高潮分档。
- 附带经验：打板策略长期平均收益偏负（本仓库定档文档亦引用开源复现仓库 [Sentiment-timing-report-reappear](https://github.com/therealXiaomanChu/Sentiment-timing-report-reappear)）。

**对产品含义**：特征可复用；输出形态应映射为「Cap 天花板」而非「进攻信号」。学术侧对「涨停后继续追」亦偏反转：[NBER w24014 *Daily Price Limits and Destructive Market Behavior*](https://doi.org/10.3386/w24014)。

### 1.3 本仓库内部定义（一手代码）

| 概念 | 定义位置 | 要点 |
|---|---|---|
| 打板情绪 | `CONTEXT.md` | 封板率、炸板率、晋级率、涨跌停家数、最高连板、连板家数；随盘/定稿同概念 |
| 派生情绪指标 | `CONTEXT.md` / `emotion_metrics.py` | 赚钱效应、分档晋级、梯队、**十日窗相对周期位置** |
| 六档 Cap | `trade_budget.py` / `doc/仓位预算-定档规则.md` | 冰点观察…退潮杀伤；情绪管总仓上限，不管买卖点 |
| `cycle_position` | `emotion_metrics.cycle_position` | 近 10 日涨停家数 / 最高连板 /（1−炸板率）minmax 合成，找谷底后计「第几天」——**相对窗内读数，无绝对阶段标签** |

---

## 2. 非 AI 基线：规则、分位、合成分

### 2.1 对比总表

| 方法 | 信号定义 | 输入特征 | 判定方式 | 可解释性 | 数据门槛 | 与本仓库 S/定档关系 |
|---|---|---|---|---|---|---|
| 游资规则树 | 六档名义阶段 | 高度、炸板、晋级、赚钱效应、跌停 | 阈值规则 / if-else | 极高 | 日频涨停池即可 | = `hard_rules`（默认） |
| 趣财经温度° | 0–100 + `sentimentLevel` 文案 | 涨停数、炸板、题材、资金等（产品称多维加权） | 厂商黑盒合成分 | 中（有阶段文案，无公开公式） | 调 `qiniugu.com` 序列 | = `qcj_degree`；归档含 `qcj_temp` / `qcj_level` |
| 历史分位合成 | 0–100 相对热度 | 涨停/跌停/高度/炸板/qcj/两融/量能 | 分位等权（可 invert） | 高（分量可审计） | ~220 日序列 + 东财补窗 | = `percentile_qcj_em` |
| 东财涨停/炸板池 | 原始盘面清单 | 连板数、炸板次数等 | 不直接给阶段 | 原始数据层 | AKShare/`stock_zt_pool_*_em` | 供分位与 `day_summary` |
| FusionIntel 宏观恐贪 | 0–100 恐贪 | 多市场宏观（厂商） | API 原样 | 低–中（区间说明公开，明细不透明） | API Key | = `fusionintel`（可选） |
| 国金「情绪脉冲」 | 实时情绪指数 | 大数据+AI（官方未披露特征清单） | 厂商指数；>75 / <25 解读 | 低 | MCP/`getSentiment` | **未接入**；宏观/日内脉冲，非连板周期 |
| 百分位网恐贪 | 0–100 六子指标 | 波动、换手、两融、宽度、RSI、涨跌停比 | 加权 + 历史分位 | 高（子项公开） | 站点公开读数 | **未接入**；含涨跌停比但仍偏宏观 |
| 开源九分项恐贪 | 0–100 | 波动/成交/新高新低/股债/宽度/涨跌停/赚钱效应等 | 分项 0–100 再合成 | 高（源码可读） | Tushare 积分等 | 对照实现：[Quantify-hp/Market-sentiment-index](https://github.com/Quantify-hp/Market-sentiment-index)；与短线档易拧巴 |
| 国泰海通情绪择时 | 多空/仓位信号 | 涨跌停占比、打板收益等 | 因子打分+趋势过滤 | 中–高 | 长历史涨跌停与收益序列 | 特征启发；非六档 |

### 2.2 一手产品/API 要点

**趣财经（本仓库已用）**

- 产品定位：[qucj.com](https://qucj.com/)——超短情绪冰点/高潮、连板晋级。
- 数据入口（本仓库源码）：`https://qiniugu.com/qng/api/v1/market` → `data.sentiment[]`，字段含 `temperatureDegree`、`sentimentLevel`、`limitUpCount`、`limitDownCount`、`leaderDayTop`（见 `short_board.py` / `sentiment_score.py`）。
- **无公开完整加权公式**；当作 L1 外部分数合理，当作唯一真理不合理。

**东财涨停生态（本仓库已用）**

- 行情中心涨停板页面为上游；开源封装见 [AKShare 文档](https://akshare.akfamily.xyz/tutorial.html)：`stock_zt_pool_em`、`stock_zt_pool_zbgc_em`、`stock_zt_pool_dtgc_em` 等。
- 本仓库用其补 `highest` / `broken_rate`（优先本机 AKTools）。

**FusionIntel（本仓库已用）**

- 官方页：[fusionintel.net](https://fusionintel.net/)——A 股宏观恐贪 0–100；REST 示例  
  `GET /v1/feargreed/a_stock_macro/shi_feargreedindex?period=30d`，Header `X-API-Key`。
- 响应列为 `date, price, feargreed_index`。代码常量：`duanxian/sentiment_score.py` 中 `_FUSION_URL`。
- 官方说明是「市场贪婪与恐惧」，**不是**连板情绪周期阶段机。

**国金证券 A 股情绪脉冲**

- 腾讯云开发 MCP 产品页（国金署名）：[mcp-gjzq-sentiment](https://tcb.cloud.tencent.com/mcp-server/mcp-gjzq-sentiment)。
- 宣称：每 5 分钟更新；`>75` 亢奋回调风险、`<25` 低迷反弹需求；工具 `getSentiment`。
- **特征清单与训练细节未公开**；定位偏实时市场情绪脉冲，与题材连板周期只能弱对齐。

**百分位网**

- [baifenwei.com/indicator/fear-greed](https://baifenwei.com/indicator/fear-greed/)：六子指标（波动率、相对换手、两融、宽度、RSI、涨跌停比）加权 0–100；分档 极度恐慌/恐慌/中性/贪婪/极度贪婪。
- 透明、可解释，但仍是**指数级综合情绪**，涨跌停比只是一项。

### 2.3 本仓库 S → Cap 映射（已实现）

有可用 S 且非 `hard_rules` 时（`sentiment_score.classify_with_s`）：

1. **退潮/过热硬叠加仍优先**（高度压降∧转差；近窗高位∧炸板≥40%）。
2. 否则：`S<20` 冰点 → `20–55` 升温 → `55–80` 高潮 → `>80` 过热。
3. **「修复确认」永不自动产出**。

无 S 时升温扩张是兜底 `else`——文档已记为已知问题：兜底=最激进档。

---

## 3. AI/ML 判定方法清单（按族）

### 3.1 隐马尔可夫 / 状态空间 / 切换回归

| 项 | 内容 |
|---|---|
| **思路** | 观测序列（收益、波动、或打板特征向量）由不可见离散 regime 生成；估计转移矩阵与发射分布，解码当前状态概率。 |
| **一手来源** | Hamilton, J. D. (1989). *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle*. Econometrica 57(2), 357–384. [JSTOR/IDEAS](https://ideas.repec.org/a/ecm/emetrp/v57y1989i2p357-84.html)。应用扩展：Adam et al. hierarchical HMM（金融牛熊）[DOI](https://doi.org/10.1177/1471082x211034048)；因子轮动 HMM：*Regime-Switching Factor Investing with Hidden Markov Models*, JRFM 2020 [MDPI](https://www.mdpi.com/1911-8074/13/12/311)。工程库：`hmmlearn` GaussianHMM。 |
| **输入** | 日频：涨停家数、炸板率、最高连板、1进2、赚钱效应中位、跌停家数（及可选指数收益/波动）。 |
| **输出** | K 个隐状态后验；需**人工对齐**到六档（或先聚成 3–4 个粗 regime 再映射）。 |
| **优点** | 显式「阶段记忆」与转移概率；适合回答「是否刚从高潮切到退潮」。 |
| **缺点** | 标签切换（label switching）；状态数难定；短样本不稳定；发射若用收益则偏宏观，须改用打板特征。 |

### 3.2 有监督分类（阶段分类）

| 项 | 内容 |
|---|---|
| **思路** | 将日频特征 → {冰点, 修复, 升温, 高潮, 过热, 退潮}；可用规则档作弱标签，或人工复盘标注。 |
| **一手来源** | 特征构造侧：国泰海通 2025-05 研报（涨跌停与打板收益因子）；分类器本身为标准 ML（无「A 股六档官方标签集」论文）。市场 regime 分类+新闻：*Cross-Sector Market Regime Forecasting with LLM-Augmented News Analysis*（FinBERT 集成 vs LSTM）[PDF](https://orbilu.uni.lu/bitstream/10993/63337/1/Cross_sectoral_market_regime_classification_using_LLM_Camera_Ready.pdf)。 |
| **输入** | 同上结构化特征 ± 昨日档位（马尔可夫特征）。 |
| **输出** | 类别或概率向量 → `caps_for(phase)`。 |
| **优点** | 直接对齐产品六档；可校准 precision/recall（尤其退潮漏检成本高）。 |
| **缺点** | 标签噪声；结构突变（注册制、T+0 预期等）导致漂移；修复档稀缺。 |

### 3.3 无监督：聚类与变点检测

| 项 | 内容 |
|---|---|
| **思路** | 不预设阶段名：聚类发现「盘面原型」；或检测序列分布突变点作为周期切换。 |
| **一手来源** | **BOCPD**：Adams, R. P., & MacKay, D. J. C. (2007). *Bayesian Online Changepoint Detection*. [arXiv:0710.3742](https://arxiv.org/abs/0710.3742)。**PELT**：Killick, R., Fearnhead, P., & Eckley, I. A. (2012). *Optimal Detection of Changepoints With a Linear Computational Cost*. JASA / [arXiv:1101.1438](https://arxiv.org/abs/1101.1438)。 |
| **输入** | 单变量（如合成分 S、炸板率）或多变量代价函数。 |
| **输出** | 变点日期 / run-length 后验；需二次规则命名阶段。 |
| **优点** | BOCPD 适合盘后在线；PELT 适合历史回放分段；少依赖主观标签。 |
| **缺点** | 「变了」≠「变成退潮」；多变量代价设计主观；短线噪声易假变点。 |

### 3.4 深度学习：LSTM / Transformer 序列

| 项 | 内容 |
|---|---|
| **思路** | 用深度序列模型预测下一 regime、收益方向或情绪分数。 |
| **一手来源** | FinBERT+LSTM 预测走势：[arXiv:2306.02136](https://arxiv.org/abs/2306.02136)；Transformer+FinBERT 趋势：[arXiv:2305.14368](https://arxiv.org/pdf/2305.14368)；LSTM+Transformer 情绪混合价预测（Journal of Economic Analysis, 2025）等。 |
| **输入** | 价格/波动序列 ± 新闻嵌入；迁移到本项目时应换为打板特征窗。 |
| **输出** | 多为涨跌方向或价格，**很少直接输出 A 股六档情绪周期**。 |
| **优点** | 可拟合非线性与长依赖。 |
| **缺点** | 样本外脆弱；可解释性差；作 **Cap 执行闸** 风险高于规则/分位；算力与标注成本高。 |

### 3.5 LLM / Agent（文本 + 结构化）

| 项 | 内容 |
|---|---|
| **思路** | 用新闻、股吧、龙虎榜叙述 + 盘面表，生成阶段判断或解释。 |
| **一手来源** | Xing (2024). *Designing Heterogeneous LLM Agents for Financial Sentiment Analysis*. [arXiv:2401.05799](https://arxiv.org/abs/2401.05799)；Yang et al. *TwinMarket*（股吧/雪球信号进 LLM agent 仿真）[arXiv HTML](https://arxiv.org/html/2502.01506v5)；综述 *LLM Agent in Financial Trading* [arXiv:2408.06361](https://arxiv.org/html/2408.06361v2)；产品向：TradingAgents-CN 类开源用东财股吧作 Sentiment Agent（工程示例，非论文）。 |
| **输入** | 文本流 + 当日 readings JSON。 |
| **输出** | 自然语言阶段标签 / 辩论结论；概率需自校准。 |
| **优点** | 适合写 `classify_reasons`、异常叙事、题材脉络。 |
| **缺点** | 幻觉、不稳定、难回测；**本仓库明确：仓位预算不进 AI prompt**（`doc/todo/仓位风控-v1延期.md`）。 |

### 3.6 另类数据情绪指数 → 映射短线周期

| 项 | 内容 |
|---|---|
| **思路** | 文本情绪指数作辅助分量，映射到 0–100 或阶段。 |
| **一手来源** | FinBERT：Araci, D. (2019). [arXiv:1908.10063](https://arxiv.org/abs/1908.10063)。中文可用领域模型/雪球股吧语料微调（实现层）；SnowNLP 等为通用中文情感库，**非金融一手论文**。 |
| **输入** | 标题/帖子日聚合分数。 |
| **输出** | 连续情绪分；与炸板/高度共振时才有短线价值。 |
| **优点** | 捕捉舆情拐头。 |
| **缺点** | 与打板生态不同步；操纵帖/营销噪声；单独映射六档证据弱。 |

---

## 4. 与本仓库现状对照

### 4.1 已实现能力地图

| 层级 | 仓库现状 | 代码/文档 |
|---|---|---|
| L0 规则树 | ✅ 默认 `hard_rules`；四道闸 + 宽度背离降档 | `trade_budget.classify_rule_phase` |
| L1 分位/外部分 | ✅ `qcj_degree` / `percentile_qcj_em` / `fusionintel` | `sentiment_score.py`；设置页切换 |
| 相对周期位置 | ✅ 十日窗谷底「第几天」 | `emotion_metrics.cycle_position`（**非六档状态机**） |
| 修复确认 | ⚠️ 仅代理提示 + 手拨；缺「核心人气股地天/强反包」硬字段 | `repair_proxy_met`；延期项 |
| L2 HMM/状态机 | ❌ | — |
| L3 监督分类 | ❌ | — |
| L4 LLM 闸门 | ❌ 刻意隔离；分析师 prompt 可读周期文案但不驱动 Cap | `analysts.py` / 延期项 |

### 4.2 现有 S 算法对照研究维度

| 算法 | 信号定义 | 输入 | 判定 | 可解释性 | 数据门槛 | 短线周期贴合度 |
|---|---|---|---|---|---|---|
| `hard_rules` | 六档规则 | 涨停生态读数 | 规则树 | 最高 | 当日+近 5 场高度 | 高（专为短线） |
| `qcj_degree` | 厂商温度° | 趣财经 | 原样当 S | 中 | API 序列 ~220 日 | 高（厂商定位超短） |
| `percentile_qcj_em` | 历史分位热度 | 趣财经+东财+两融+量能 | 等权分位 | 高 | 长窗+补全 | 高（涨停生态为主） |
| `fusionintel` | 宏观恐贪 | FusionIntel API | 原样当 S | 中低 | API Key | **低–中**（宏观） |

### 4.3 已知结构性缺口（与 AI 选型相关）

来自 `doc/仓位预算-定档规则.md` / `doc/todo/仓位风控-v1延期.md`：

1. 无 S 时升温=兜底最激进 → L1 校准或正向条件可缓解。  
2. 高度成单点否决 → L2 状态机应用「非高度通道」降档。  
3. 修复确认不自动、手拨不传次日 → 状态机转移表可建模。  
4. 分位阈值样本外校准仍延期 → 上 L3 前应先完成。  
5. 预算结果不进 AI prompt → L4 只做解释层符合现产品边界。

---

## 5. 推荐落地路径（排序 + 理由）

### L0 规则树（已有）——保持为安全底座

| 维度 | 说明 |
|---|---|
| 数据 | 现有 `gather_readings` |
| 输出 | `rule_phase` → `Cap_*` |
| 与 Cap | 直接 `caps_for` |
| 风险/误判 | 高度卡中间时无法降档；无 S 时升温兜底过激 |

**行动**：修「升温需正向条件」或强制默认走 L1，不必等 AI。

### L1 分位合成 S（已有）——优先完成阈值回测

| 维度 | 说明 |
|---|---|
| 数据 | `series.db` 情趣财经+东财+margin+amount |
| 输出 | `S∈[0,100]` + 分量明细 |
| 与 Cap | `classify_with_s`：退潮/过热叠加优先，再按 20/55/80 |
| 风险/误判 | 东财窗外 broken_rate 缺失；宏观分量（两融）稀释短线信号；阈值未校准 |

**行动**：按延期项做样本外定档一致性与回撤对照；可对涨停生态分量升权、宏观分量降权。

### L2 显式周期阶段状态机 / 轻量 HMM（推荐下一阶段主路径）

| 维度 | 说明 |
|---|---|
| 数据 | 日频 readings + 昨日 `phase`（应用生效档而非仅 `rule_phase`） |
| 输出 | 离散六档 + 可选转移概率；修复确认可用转移条件触发（配合地天硬字段） |
| 与 Cap | 输出直接替换/约束 `classify_rule_phase` |
| 风险/误判 | 转移表过拟合；HMM 状态与六档名不对齐 |

**理由**：产品要的是**有记忆的阶段**，不是无记忆的当日截面；Hamilton/BOCPD 提供方法论，但工程上先做**可审计状态机**，HMM 作旁路概率条。

建议最小状态机：

```
退潮 → 冰点 →（修复条件）→ 修复 → 升温 → 高潮 → 过热 → 退潮
         ↑__________________________________________|
```

硬叠加（炸板+高度压降）可强制切退潮，防止「升温粘滞」。

### L3 监督学习阶段分类（实验层）

| 维度 | 说明 |
|---|---|
| 数据 | ≥2–3 年日频特征；弱标签=当日规则档或人工复盘 |
| 输出 | 六类概率；可与 L2 投票 |
| 与 Cap | 仅当概率边际显著且通过防守校验时覆盖 |
| 风险/误判 | 标签噪声；制度变迁；退潮漏检代价高 |

**行动**：先离线 notebook 评估，**不**默认接线到 `build_budget`。

### L4 LLM 辅助解释（不建议单独当闸门）

| 维度 | 说明 |
|---|---|
| 数据 | readings JSON + 可选新闻/股吧摘要 |
| 输出 | 中文理由、风险提示；禁止单独改 `phase` |
| 与 Cap | 零耦合或只写展示层 |
| 风险/误判 | 幻觉把退潮说成升温；不可回测 |

符合现有合规边界：预算纯硬规则，不进 AI prompt。

### 明确不推荐 / 易拧巴

1. **宏观九分项恐贪直接套短线档位**（百分位网/开源九分项/FusionIntel 默认）：时间尺度与特征集合错位；本仓库文档已警告。  
2. **仅用 LLM、无结构化打板特征**：一手论文亦强调文本需与时序结合；单独闸门不可审计。  
3. **未样本外验证的深度模型当执行闸**：Cap 错误直接变成仓位错误，非预测游戏分数。  
4. **把国泰海通择时收益信号当成「应加仓」**：与本产品「情绪=天花板」原则相反；NBER 涨停行为研究亦提示反转风险。

### 落地优先级（产品）

1. L0 兜底逻辑修补 + L1 阈值校准（低成本、立刻改善已知问题）  
2. L2 状态机（含修复硬字段、昨日生效档传递）  
3. L2 旁路 BOCPD/HMM 切换概率条（提示用）  
4. L3 离线实验  
5. L4 解释层（可选）

---

## 6. 引用与来源

### 本仓库

- `CONTEXT.md`
- `doc/仓位预算-定档规则.md`
- `doc/todo/仓位风控-v1延期.md`
- `duanxian/sentiment_score.py`、`risk_stance.py`、`short_board.py`、`trade_budget.py`、`emotion_metrics.py`

### 产品 / 数据厂商（一手页或源码调用）

- 趣财经产品：[https://qucj.com/](https://qucj.com/)；API 使用见本仓库 `qiniugu.com/qng/api/v1/market`
- FusionIntel：[https://fusionintel.net/](https://fusionintel.net/)
- 国金情绪脉冲 MCP：[https://tcb.cloud.tencent.com/mcp-server/mcp-gjzq-sentiment](https://tcb.cloud.tencent.com/mcp-server/mcp-gjzq-sentiment)
- 百分位网恐贪：[https://baifenwei.com/indicator/fear-greed/](https://baifenwei.com/indicator/fear-greed/)
- AKShare 涨停池文档：[https://akshare.akfamily.xyz/tutorial.html](https://akshare.akfamily.xyz/tutorial.html)
- 开源九分项：[https://github.com/Quantify-hp/Market-sentiment-index](https://github.com/Quantify-hp/Market-sentiment-index)

### 券商 / 盘面公开文字

- 国泰海通（2025-05-14）情绪择时要点转载：[https://news.qq.com/rain/a/20250515A09EJF00](https://news.qq.com/rain/a/20250515A09EJF00)（作者资格号见文内）
- 九方智投情绪周期阶段：[https://wap.9fzt.com/article/e4348b0acba658928af2721d8522cb73-9fztgw_1_top.html](https://wap.9fzt.com/article/e4348b0acba658928af2721d8522cb73-9fztgw_1_top.html)
- 东财财富号实操体系：[https://caifuhao.eastmoney.com/news/20260314093054692373420](https://caifuhao.eastmoney.com/news/20260314093054692373420)

### 学术 / 预印本

- Hamilton (1989) Markov switching：Econometrica 57(2). [IDEAS](https://ideas.repec.org/a/ecm/emetrp/v57y1989i2p357-84.html)
- Adams & MacKay (2007) BOCPD：[arXiv:0710.3742](https://arxiv.org/abs/0710.3742)
- Killick et al. (2012) PELT：[arXiv:1101.1438](https://arxiv.org/abs/1101.1438)
- Araci (2019) FinBERT：[arXiv:1908.10063](https://arxiv.org/abs/1908.10063)
- Xing (2024) Heterogeneous LLM Agents for FSA：[arXiv:2401.05799](https://arxiv.org/abs/2401.05799)
- Yang et al. TwinMarket：[https://arxiv.org/html/2502.01506v5](https://arxiv.org/html/2502.01506v5)
- LLM trading agent survey：[https://arxiv.org/html/2408.06361v2](https://arxiv.org/html/2408.06361v2)
- FinBERT+LSTM：[arXiv:2306.02136](https://arxiv.org/abs/2306.02136)
- Transformer+sentiment：[arXiv:2305.14368](https://arxiv.org/pdf/2305.14368)
- LLM-augmented regime classification：[orbilu PDF](https://orbilu.uni.lu/bitstream/10993/63337/1/Cross_sectoral_market_regime_classification_using_LLM_Camera_Ready.pdf)
- NBER w24014 涨停与破坏性行为：[https://doi.org/10.3386/w24014](https://doi.org/10.3386/w24014)
- Hierarchical HMM 牛熊检测：[https://doi.org/10.1177/1471082x211034048](https://doi.org/10.1177/1471082x211034048)
- HMM factor regime：[https://www.mdpi.com/1911-8074/13/12/311](https://www.mdpi.com/1911-8074/13/12/311)

### 证据强度说明（撰稿自检）

| Claim | 强度 |
|---|---|
| 本仓库四档 S 算法行为与 Cap 映射 | 强（源码） |
| FusionIntel / 百分位网 / 国金脉冲的官方区间解读 | 强（产品页） |
| 国泰海通五因子与回测数字 | 中–强（官方公众号转载要点；全文 PDF 常加密） |
| 游资六档阈值「通识」 | 中（多源公开教程一致，无单一权威标准） |
| 趣财经温度°内部加权细节 | 弱（产品宣称多维，公式未公开） |
| 国金脉冲具体特征与「AI」训练方式 | 弱（仅营销级描述） |
| 「HMM/BOCPD 直接提升短线 Cap 夏普」 | 弱（方法论可迁移，A 股连板场景缺专项一手实证） |

---

*本文仅作方法调研，不构成投资建议；仓位规则以仓库现行代码与定档文档为准。*
