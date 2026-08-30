# 消息优先级：纯 AI 判定方法

> 日期：2026-08-30。范围：单条 A 股资讯/电报的「该不该优先看」判定；对照本仓库消息分析已有 schema 与 AI 管线，不涉及买卖点或仓位建议。

## 结论摘要

- **不要让模型直接打一档 `impact_level`**：绝对档位易漂成「全是 medium」；应拆成可判定因子，再由服务端规则合成档位。
- **优先级 ≠ 客观重要**：至少拆成影响面、力度、时效、可交易性、可信度；「与我相关」用关注词/自选规则后处理，不要塞进同一 prompt。
- **推荐落地路径**：多维打标 → 固定权重合成 → 关注词 boost；辅以 few-shot 锚点与人工改档闭环校准。
- **现有管线可直接演进**：`vr/message/analyze.py` 已输出 `impact_level` / `freshness` / `effect_status` / `targets`；扩展 JSON 骨架为因子字段，合成函数落服务端即可。
- **不推荐**：无锚点的单字段五档直出；让 AI 同时承担「市场客观重要」与「对我重要」；无人工对照就调 prompt。

---

## 1. 本仓库现状

### 1.1 已有字段（与优先级相关）

| 字段 | 含义 | 来源 |
|------|------|------|
| `impact_level` | `critical` / `high` / `medium` / `low` / `noise` | 工作档：来源初值经关注升档、AI、人工 |
| `initial_impact_level` | 同上五档 | 进入系统时的初始档；仅人工改档时与工作档同步 |
| `impact_manual` | bool | 优先级是否被人工指定过；为真后 AI 不再覆写工作档 |
| `freshness` | `new` / `follow_up` / `duplicate` / `rumor` | AI |
| `effect_status` | 是否已炒作/兑现等 | AI（默认 `not_erupted`） |
| `targets` | market / sector / theme / stock / other | 解析 + AI 合并 |
| `followed` / 关注词 | 个人相关命中 | 规则（`vr/message/follow.py`） |

### 1.2 当前优先级形成链路

```text
来源先验（财联社 A/B/C、日历 importanceLevel）
  → 落库：initial_impact_level = 来源先验（冻结）
           impact_level = 来源先验经关注词升档（工作档）
           impact_manual = false
  → AI 结构化分析仅可覆写工作档 impact_level（analyze.py）；不动初始档
  → 若 impact_manual=true，AI 不再改工作档
  → 人工改档（analyzed_by=human）：同步 initial_impact_level 与 impact_level，并置 impact_manual=true
```

关键实现：

- AI 骨架与 system prompt：`vr/message/analyze.py`（`JSON_SKELETON` / `SYSTEM`）
- 档位枚举：`vr/message/schemas.py` → `ImpactLevel`
- 关注词升档：`vr/message/follow.py` → `boost_impact_level`
- 财联社初值：`vr/message/cls.py` → `level_to_impact`
- 日历初值：`vr/message/parser.py` → `importance_to_impact`

### 1.3 初始档与手动标记（已落地）

- 入库时写入 `initial_impact_level`（来源先验，**不含**关注升档）与工作档 `impact_level`（可含关注 +1）。
- AI 分析只动工作档；`impact_manual=true` 后 AI 不再改工作档。
- 人工改档（`analyzed_by=human`）时同步两档并置 `impact_manual=true`。

### 1.4 当前 AI 判定的局限

- 模型被要求**直接**选 `impact_level`，缺少可复核的中间因子。
- `freshness` 故意禁止引用库内其他消息，续报/重复只能弱判。
- 无 few-shot 锚点；无 AI vs 人工混淆矩阵闭环。
- 「客观影响」与「个人相关」：关注升档只影响工作档，初始档保持来源先验。

---

## 2. 「优先级」应拆成的维度

交易场景里，一条消息该不该先看，通常是多因子乘积，而非单一「重要」：

| 维度 | 问的是 | 建议由谁判 | 与现字段关系 |
|------|--------|------------|--------------|
| 影响面 scope | 全市场 / 板块 / 题材 / 个股 | AI | `targets.kind` |
| 力度 magnitude | 政策监管、业绩变脸 vs 软文 | AI | 合成进 `impact_level` |
| 时效 time_sensitivity | 盘中突发 vs 隔夜已知 | AI + 时钟 | 可与 `produced_at` 结合 |
| 可交易性 actionability | 能否落到可跟标的/题材 | AI | `targets` 质量 |
| 可信度 credibility | 官宣 / 主流 / 传闻 | AI | 对齐 `freshness=rumor` |
| 与我相关 | 持仓、自选、关注词 | **规则** | `followed` / boost |

合规边界（与仓库一致）：只做信息整理与客观标注；不推荐买卖、不预测涨跌、不给目标价。

---

## 3. 纯 AI 思路对比

### 3.1 多维打标 → 规则合成（推荐）

让模型输出因子，**服务端**映射到五档：

```text
模型输出示例：
  scope: market|sector|theme|stock|other
  magnitude: 1–5
  actionability: 1–5
  credibility: 1–5
  time_sensitivity: 1–5
  is_rumor: bool
  rationale: 一句理由（强制）

合成（示例，权重可调）：
  score = 0.30*magnitude
        + 0.25*actionability
        + 0.20*time_sensitivity
        + 0.15*credibility
        + 0.10*scope_weight

  is_rumor / freshness=rumor → 降一档
  duplicate → 封顶 medium
  关注词命中 → 个人化 +1（封顶 critical）
```

档位映射示意：`score` 分位或固定阈值 → `noise` … `critical`。

**优点**：可解释、可回测、可调权；比单字段直出稳定。  
**落地**：扩展 `JSON_SKELETON`；`impact_level` 改由合成函数写入，模型不再（或不单独）直接选档。

### 3.2 对比排序 / 成对比较（校准向）

- 同批消息两两比较「哪条更该先看」，再用 Bradley–Terry / Elo 得相对序；或
- prompt 内放入人工标好的锚点消息作 few-shot。

适合日终复盘、批量重排；不适合每条电报实时一条大模型。

### 3.3 小模型专做分类（成本向）

大模型标几千条 → 微调小分类器（或 embedding + 线性头）只输出档位。  
全量电报过筛用小模型；`high+` 再喂贵模型做摘要/标的。仍属「纯 AI」，但推理更稳、更便宜。

### 3.4 不推荐

| 做法 | 原因 |
|------|------|
| 无锚点直接五档直出 | 分布漂移，易全 medium |
| AI 同时判「客观 + 对我」 | 无法共用权重，难校准 |
| 仅靠「可能影响股价」抬档 | 几乎所有消息都会被抬高 |
| 无人工对照调 prompt | 无法知道漏报/误抬 |

---

## 4. Prompt 设计要点

### 4.1 锚点定义写死（比枚举名重要）

| 档位 | 定义（示例口径） |
|------|------------------|
| critical | 央行/证监会重大政策、系统性风险、指数级事件 |
| high | 核心板块监管、重大并购、龙头业绩变脸等 |
| medium | 一般公司公告、常规宏观数据 |
| low | 软性解读、行业动态 |
| noise | 广告、重复转发、无增量信息 |

### 4.2 其它硬规则

1. **Few-shot**：各档 1～2 条真实电报，含「吓人但其实 noise」负例。
2. **强制 `rationale` 一句**：先理由后档位/因子，降低随机漂移。
3. **禁止用「可能影响股价」抬档**：只按信息增量与影响面。
4. **上下文**：盘中/盘后；若允许查库，同主题 `follow_up` / `duplicate` 会准很多（与当前「禁止引用其他消息」策略需产品取舍）。

### 4.3 建议管线

```text
来源先验（弱）
  → AI 多维因子 + rationale
  → 服务端合成 impact_level
  → 关注词 / 自选 / 当前股 boost（个人化）
  → 人工改档回写（校准样本）
```

---

## 5. 校准与验收

最低成本闭环：

1. 人工改档时保留 `analyzed_by=human`（已有）。
2. 每周统计 AI（合成档）vs 人工的混淆矩阵。
3. 优先盯两类错误：
   - **漏报**：真实 critical/high 被标成 medium 以下；
   - **误抬**：noise/low 被抬到 high。

无标签前不调权重；有 50+ 条人工对照后再动合成公式。

---

## 6. 落地排序建议

| 优先级 | 动作 | 触及 |
|--------|------|------|
| P0 | 扩展 analyze JSON：因子 + rationale；服务端合成 `impact_level` | `vr/message/analyze.py`、测试 |
| P0 | System prompt 写入五档锚点定义 + 负例说明 | 同上 |
| P1 | 导入/分析后仍走关注词 boost；个人化与客观档分离文档化 | `follow.py` |
| P1 | 人工改档导出对照集；简单混淆矩阵脚本或手工表 | 运维/脚本 |
| P2 | 可选：同批相对排序或 few-shot 锚点库 | 批量分析路径 |
| P2 | 可选：小模型过筛 + 大模型精标 | 成本优化 |

---

## 7. 相关代码与文档

| 说明 | 路径 |
|------|------|
| AI 结构化分析 | `vr/message/analyze.py` |
| 消息 schema | `vr/message/schemas.py` |
| 关注词升档 | `vr/message/follow.py` |
| 财联社 level 映射 | `vr/message/cls.py` |
| 日历 importance 映射 | `vr/message/parser.py` |
| 消息存储 | `vr/message/store.py` |
| 消息来源说明 | `doc/消息来源.md` |
| 插件上报消息示例 | `doc/development/plugin-development.md`（`impact_level` 字段） |
