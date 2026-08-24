# 打板情绪、环境条、连板股分属三处

架构扫描容易把 `live_emotion`、`short_board`、`vr` 情绪看成三份克隆。它们只共用场次，不是同一概念：打板情绪是当场次的封板/炸板/晋级比率（SoT 在 `duanxian.live_emotion`）；环境条是选股宝等拼出的温度与量能；连板股是客观榜单，必须留在可整树同步的 `vr/`。场次规则收进 `trade_calendar.resolve_as_of`；不把三者收成一个 snapshot。

**Considered Options**
- 一个 snapshot 信封同时返回环境条 + 打板情绪：interface 几乎和两套 implementation 一样宽。
- 连板股并进打板情绪：会把问财涨停原因拖进比率 module，且必须改 `vr/`。
- 派生情绪指标（赚钱效应 / 分档晋级）并进来：那是复盘口径，不是打板情绪。
