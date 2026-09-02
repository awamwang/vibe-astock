# 文档索引（本机）

> **不入库**：本文件与 `doc/inner/` 已在 `.gitignore` 中排除，仅本机维护。仓库入口见根目录 [README.md](../README.md) 的文档表。

本目录存放 **领域规则**、**数据源说明** 与 **开发文档**。产品词汇以根目录 [CONTEXT.md](../CONTEXT.md) 为准；系统级架构决策见 [docs/adr/](../docs/adr/)。

---

## 内部稿（不入库）

| 文档 | 说明 |
|------|------|
| [inner/教学大纲-新手介绍与使用.md](./inner/教学大纲-新手介绍与使用.md) | 面向新手的介绍与使用大纲（仅本机） |

---

## 领域与业务

| 文档 | 说明 |
|------|------|
| [仓位预算-定档规则.md](./仓位预算-定档规则.md) | 情绪档位、Cap 上限、定档流程与 guard 规则 |
| [消息来源.md](./消息来源.md) | 选股宝、财联社等快讯来源与接入方式 |

---

## 开发

入口：[development/](./development/)

| 文档 | 说明 |
|------|------|
| [architecture.md](./development/architecture.md) | 代码分区、数据流、数据落盘、**并发加锁** |
| [lock-safety.md](./development/lock-safety.md) | **锁安全**：持锁重入、IO 线程、回归测试与静态扫描 |
| [plugin-development.md](./development/plugin-development.md) | 插件 `HookPack` 写法与 `HookRegistry` API |
| [hook-lifecycle.md](./development/hook-lifecycle.md) | 钩子加载顺序与事件派发链路 |

### 调研

| 文档 | 说明 |
|------|------|
| [短线情绪周期-AI判定方法.md](./development/research/短线情绪周期-AI判定方法.md) | 情绪周期 AI 判定思路调研 |
| [自选股深入分析-AI提示词调研.md](./development/research/自选股深入分析-AI提示词调研.md) | 自选股深入分析提示词调研 |
| [消息优先级-AI判定方法.md](./development/research/消息优先级-AI判定方法.md) | 单条消息优先级（影响档）AI 判定调研 |
| [消息新旧程度-AI判定方法.md](./development/research/消息新旧程度-AI判定方法.md) | 消息新旧 / 是否炒过：主张指纹 + 召回差分；第三方仅记组合建议 |
| [龙虎榜营业部标记与Tushare游资名录.md](./inner/research/龙虎榜营业部标记与Tushare游资名录.md) | 席位标签/风格/体量来源；Tushare `hm_list` 请求与本机权限实测 |

---

## 待办与演进

| 文档 | 说明 |
|------|------|
| [架构加深-后续.md](./development/todo/架构加深-后续.md) | 架构演进 backlog（定稿档案、风险姿态、VR host 等） |
| [仓位风控-v1延期.md](./todo/仓位风控-v1延期.md) | v1 已确认延期项，后续阶段再开 |

---

## 仓库其他文档

| 位置 | 说明 |
|------|------|
| [CONTEXT.md](../CONTEXT.md) | 产品词汇表（场次、打板情绪、定稿等） |
| [docs/adr/](../docs/adr/) | 架构决策记录（ADR） |
| [docs/agents/](../docs/agents/) | Agent / 工程技能如何消费本仓库文档 |
| [README.md](../README.md) | 项目介绍、快速开始、环境变量 |
