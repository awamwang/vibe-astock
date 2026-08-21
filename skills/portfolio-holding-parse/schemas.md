# 持仓解析 Schema 与示例

与 vibe-astock 前端类型 `ScreenshotDraft` / `ScreenshotHoldingRow` 对齐（见 `frontend/src/lib/api.ts`）。

## ScreenshotHoldingRow

| 字段 | 类型 | 必填（写入） | 说明 |
|------|------|--------------|------|
| code | string | 是 | 6 位数字 |
| name | string \| null | 否 | 名称 |
| shares | number | 是且 > 0 | 持仓股数 |
| available_shares | number \| null | 否 | 可用股数 |
| cost | number \| null | 写入须 > 0 | 成本价 |
| price | number \| null | 否 | 现价 |
| pnl | number \| null | 否 | 盈亏 |
| market_value | number \| null | 否 | 市值 |
| include | boolean | 否 | UI 勾选；默认 shares>0 且 cost>0 为 true |

## ScreenshotDraft 账户字段

| 字段 | 说明 |
|------|------|
| broker | 券商/软件名 |
| account_name | 账户名 |
| account_display | 右下角账户标识 |
| equity | 总资产/总权益 |
| cash_balance | 资金余额 |
| available | 可用 |
| withdrawable | 可取 |
| frozen | 冻结 |
| stock_market_value | 股票市值 |
| position_pnl | 持仓盈亏 |
| daily_pnl | 当日盈亏 |
| daily_pnl_pct | 当日盈亏比（百分数，如 -3.34） |
| note | 备注 |
| holdings | 持仓行数组 |

## 导入识别（UI）

`PortfolioJsonImport` 规则：

- 对象含 `holdings` → 整体草稿预览
- 对象含 `code` 且无 `holdings` → 单条按 code 增/改
- 顶层数组 → 不支持（本技能勿输出裸数组）

## 示例：整体

```json
{
  "broker": "中金财富",
  "account_name": "中金财富-王*",
  "account_display": "中金财富6323",
  "equity": 125432.18,
  "cash_balance": 440.85,
  "available": 440.85,
  "withdrawable": 440.85,
  "frozen": 0,
  "stock_market_value": 124991.33,
  "position_pnl": -1203.5,
  "daily_pnl": -892.1,
  "daily_pnl_pct": -0.71,
  "note": null,
  "holdings": [
    {
      "code": "600000",
      "name": "浦发银行",
      "shares": 1000,
      "available_shares": 1000,
      "cost": 10.52,
      "price": 10.1,
      "pnl": -420,
      "market_value": 10100
    }
  ]
}
```

## 示例：仅持仓列表

```json
{
  "holdings": [
    { "code": "002463", "name": "沪电股份", "shares": 200, "cost": 38.2 },
    { "code": "300750", "name": "宁德时代", "shares": 100, "cost": 185.6 }
  ]
}
```

## 示例：单条

```json
{
  "code": "002463",
  "name": "沪电股份",
  "shares": 200,
  "cost": 38.2
}
```
