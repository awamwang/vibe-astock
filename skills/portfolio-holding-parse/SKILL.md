---
name: portfolio-holding-parse
description: >-
  从券商/交易软件持仓截图（或可见持仓文本）解析为 vibe-astock「持仓与预算」可导入的 JSON。
  有总权益/账户名/可用/可取等账户汇总时输出 ScreenshotDraft；仅有持仓表时输出 holdings 列表。
  在用户要解析持仓截图、导出持仓 JSON、导入本地持仓，或提到 ScreenshotDraft / ScreenshotHoldingRow 时使用。
---

# 持仓解析（导入 vibe-astock）

把券商持仓截图或可见持仓信息，整理成可在本项目 **持仓与预算 → 导入 JSON** 粘贴/上传的结构。不要编造看不见的数字。

## 何时用

- 用户提供持仓截图、持仓页粘贴内容，要求解析/导入
- 需要生成 `ScreenshotDraft` 或持仓行列表，供本仓库写入本地持仓

## 决策：整体 vs 仅持仓

先扫一遍输入里是否出现**账户汇总**信号（任一即可算「有账户信息」）：

| 信号 | 常见文案 |
|------|----------|
| 总权益 | 总资产、总权益、净资产 |
| 账户名 | 账户名、客户名、右下角账户标识 |
| 资金类 | 资金余额、可用、可取、冻结 |
| 盈亏汇总 | 股票市值、持仓盈亏、当日盈亏、当日盈亏比 |

- **有账户汇总** → 输出 **整体** `ScreenshotDraft`（含 `holdings`）
- **只有持仓表**（代码/名称/股数/成本等）→ 输出 **仅持仓**：`{ "holdings": [ ... ] }`  
  （仍带 `holdings` 键，便于「导入 JSON」按整体草稿识别；不要输出裸数组）
- **仅一行持仓且无账户汇总** → 也可输出单条 `ScreenshotHoldingRow`（按 `code` 增/改）

## 输出格式

### A. 整体 `ScreenshotDraft`

键名固定；看不清填 `null`。百分比写成 `-3.34`（不要 `0.0334`）。代码为 6 位数字字符串。

```json
{
  "broker": "券商或软件名，未知则 null",
  "account_name": "账户名或 null",
  "account_display": "右下角账户标识或 null",
  "equity": 0,
  "cash_balance": 0,
  "available": 0,
  "withdrawable": 0,
  "frozen": 0,
  "stock_market_value": 0,
  "position_pnl": 0,
  "daily_pnl": 0,
  "daily_pnl_pct": 0,
  "note": null,
  "holdings": [
    {
      "code": "600000",
      "name": "名称或 null",
      "shares": 1000,
      "available_shares": null,
      "cost": 10.5,
      "price": null,
      "pnl": null,
      "market_value": null
    }
  ]
}
```

### B. 仅持仓列表

```json
{
  "holdings": [
    {
      "code": "600000",
      "name": "浦发银行",
      "shares": 1000,
      "available_shares": null,
      "cost": 10.5,
      "price": null,
      "pnl": null,
      "market_value": null
    }
  ]
}
```

### C. 单条持仓（可选）

```json
{
  "code": "600000",
  "name": "浦发银行",
  "shares": 1000,
  "cost": 10.5
}
```

写入规则：`code` 已存在则覆盖股数/成本，否则新增。

## 解析规则

1. 只根据可见内容填写；缺失/看不清 → `null`，禁止猜测补全。
2. 股票代码统一 6 位；含前缀时取末 6 位数字。
3. 金额/股数去掉千分位逗号；去掉「元」「%」后再转数字。
4. `equity` 优先「总资产」；否则用能代表总权益的字段。
5. `cash_balance` 与 `withdrawable` 图中常相同；只见到一个时可互填。
6. 持仓表尽量扫全行（含股数为 0 的历史行）；导入时股数与成本均须 `> 0` 才会写入。
7. 只输出 JSON（可包在 markdown 代码块里），不要长篇解释；需要时可在 JSON 后用一两句说明选了整体还是仅持仓。

## 截图识图提示词（代理读图时沿用）

系统：只根据图片可见内容填 JSON，不编造；看不清填 null；只输出 JSON。

用户侧要求与上文「输出格式 A」一致；若图中**完全没有**账户汇总字段，则改为输出格式 B（仅 `holdings`）。

## 导入到本项目

1. 打开前端 **持仓与预算**（路由 `/trade`）
2. 点 **导入 JSON**，粘贴本技能产出的 JSON（或存成 `.json` 上传）
3. 整体草稿：核对账户栏与持仓勾选后确认写入（默认可整表覆盖）
4. 单条：按 `code` 确认新增或更新

后端对应（参考，一般走 UI 即可）：

- 整体：`POST /api/trade/screenshot/apply`
- 单条覆盖写入：`POST /api/portfolio/holding`，body 含 `upsert: true`

## 字段速查

完整字段与示例见 [schemas.md](schemas.md)。
