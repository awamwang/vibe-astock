# Vibe-Astock 基础架构

> 词汇与产品边界以根目录 [CONTEXT.md](../../CONTEXT.md) 为准；系统级架构决策见 [docs/adr/](../../docs/adr/)。  
> 插件开发见 [plugin-development.md](./plugin-development.md)，钩子生命周期见 [hook-lifecycle.md](./hook-lifecycle.md)。

---

## 1. 总览

Vibe-Astock 是 **单进程、本机自托管** 的 A 股短线复盘看板：FastAPI 后端合并静态前端，对外一个端口（默认 `8910`）。核心职责是把公开盘面数据整理为 **派生情绪指标** 与 **客观事实**，再经多 Agent 编排产出可读研判；不推荐个股、不预测涨跌。

```
┌─────────────────────────────────────────────────────────────────┐
│  frontend/dist（React SPA）                                      │
│  pages · liveBoard / agent view-model · api 传输层               │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / SSE
┌────────────────────────────▼────────────────────────────────────┐
│  server.py（宿主 FastAPI）                                       │
│  复盘任务 · 写闸 · 静态资源 · duanxian 路由薄适配                  │
└─────┬───────────────────────────────┬───────────────────────────┘
      │                               │
      │ import                        │ vr_host.install()
      ▼                               ▼
┌─────────────────┐           ┌─────────────────┐
│  duanxian/      │           │  vr/            │
│  场次·打板情绪   │           │  个股·持仓·消息  │
│  定稿档案·复盘图 │           │  同花顺板块·自选 │
│  预算·钩子      │           │  （可整树拷贝）  │
└────────┬────────┘           └────────┬────────┘
         │                             │
         └──────────┬──────────────────┘
                    ▼
         外部数据源（东财 / akshare / 问财 / AKTools …）
                    ▼
         ~/.duanxian-agents/  ~/.vibe-research/  ~/.vibe-astock/
```

**独立入口**：`main.py` 可在命令行直接跑单日复盘（不经 `server.py`），与 Web 共用 `duanxian` 领域逻辑。

---

## 2. 代码分区

| 分区 | 路径 | 职责 |
|------|------|------|
| **宿主** | `server.py` | 进程生命周期、复盘/周报 HTTP、Origin 写闸、合并 VR 路由、服务 `frontend/dist` |
| **短线引擎** | `duanxian/` | 场次（`trade_calendar`）、打板情绪（`live_emotion`）、环境条（`short_board`）、定稿日档案（`settled_archive`）、派生指标（`emotion_metrics` / `market_facts`）、复盘图（`review_graph`）、仓位预算（`risk_stance` / `trade_budget`）、插件钩子（`hooks`） |
| **VR 数据层** | `vr/` | 个股行情（`astock`）、持仓/自选、消息分析、同花顺板块、股票列表、辩论/聊天等 `/api/*` 端点；**保持可整树拷贝同步**（见 ADR-0001） |
| **VR 宿主策略** | `duanxian/vr_host.py` | 路由合并、定稿涨停池钉住、CLI 白名单、用户数据防护、`vr_guard_error` |
| **前端** | `frontend/src/` | React 19 + Vite；`lib/liveBoard.ts`（随盘）、`lib/agent.ts`（定稿档案）、`lib/api.ts`（传输） |
| **插件** | `plugins/` + `~/.vibe-astock/plugins.json` | 导出 `HookPack`；经 `duanxian.hooks` 加载 |
| **测试** | `tests/` | 按 deep module 拆分（`test_settled_archive`、`test_risk_stance`、`test_vr_host` 等） |

### 2.1 产品概念与模块映射（ADR-0001）

以下概念 **刻意分模块**，不要合并成单一 snapshot：

| 概念（CONTEXT） | 主要模块 | 说明 |
|-----------------|----------|------|
| 场次 | `trade_calendar` | `resolve_as_of` / `latest_session` / `is_settled` |
| 打板情绪 | `live_emotion` | 封板率、炸板率、晋级率、连板家数等 |
| 环境条 | `short_board` | 选股宝、开盘啦等拼出的盘面温度 |
| 连板股 | `vr` 侧榜单 | 客观公开名单，不进打板情绪比率 |
| 派生情绪指标 | `emotion_metrics` + `settled_archive` | 复盘用赚钱效应、分档晋级、情绪周期等 |
| 当日风险姿态 | `risk_stance` | 档位、上限、guard、读数组装 |

### 2.2 复盘数据流

```
validate_trade_date + is_settled
        ↓
review_graph（五分析师 + 裁判，LangGraph）
        ↓
review_store 落盘 ~/.duanxian-agents/reviews/
        ↓
trade_store.refresh（仓位预算，不进 review JSON）
        ↓
hooks.RUNNER.emit_after_review（插件推送）
```

派生情绪指标与客观事实在进 AI 之前已由 `settled_archive` / 相关 module **纯计算**完成；AI 只做叙事收敛。

### 2.3 启动与后台任务

`server.py` 的 `lifespan` 会：

1. `stock_universe.startup_load()` — 股票列表只读本地缓存  
2. `ths_block.processor.schedule_ensure_kinds_cached()` — 同花顺板块懒加载  
3. `market_series.ensure_fresh_background()` — 两融/指数等序列后台刷新  
4. `aktools_service` — 可选托管 AKTools 子进程（`8988`）

`vr/app.py` 独立启动时另有：`portfolio` 定时刷新、`message.poller` 启动钩子。

---

## 3. 数据落盘

| 目录 | 内容 |
|------|------|
| `~/.duanxian-agents/reviews/` | 日复盘 JSON |
| `~/.duanxian-agents/weekly/` | 近 N 日热度缓存 |
| `~/.duanxian-agents/cache/` | 市场序列 SQLite、广度、短板等 |
| `~/.duanxian-agents/messages/` | 消息分析 SQLite（`messages.db`） |
| `~/.vibe-research/` | 持仓、自选、部分 VR 缓存（`VR_DATA_DIR` 可覆盖） |
| `~/.vibe-astock/` | 插件注册表、`prompts_local.py` |

写盘惯例：**临时文件 + `os.replace` 原子替换**（如 `server._atomic_write`、持仓迁移），读方不会看到半截 JSON。

---

## 4. HTTP 与安全闸

| 闸 | 位置 | 作用 |
|----|------|------|
| Origin 写闸 | `server._origin_ok` | 昂贵 POST（复盘、评估等）仅允许本机 Host |
| VR API Key | `vr/app.py` | 设 `VR_API_KEY` 后 `/api/*` 需 Bearer |
| VR 用户数据闸 | `vr_host.vr_guard_error` | 合并进来的 VR 写路径额外判定 |
| CLI 白名单 | `vr_host` + `server` | 非 `claude` CLI 需 `VIBE_ALLOW_UNSAFE_CLI` |

---

## 5. 插件与扩展点

- **Prompt 包**：`VIBE_ASTOCK_PROMPTS` → `duanxian.prompts.PACK`  
- **钩子**：`duanxian.hooks` — 引擎 push（复盘/预算快照）与插件 pull（`HookRegistry.import_*`）  
- **指标验证**：`MetricProvider` 注册自定义可验证指标  

详见 [plugin-development.md](./plugin-development.md)、[hook-lifecycle.md](./hook-lifecycle.md)。

---

## 6. 并发与加锁

本项目在 **单进程、多线程** 模型下运行（FastAPI 同步路由 + 后台 `threading.Thread`）。没有分布式锁；所有锁均为 **进程内 `threading.Lock` / `RLock`**，用于保护内存状态或串行化「读-改-写」。

设计原则：

1. **锁粒度尽量 module 内私有**，不导出全局锁对象。  
2. **短临界区**：锁内不做网络 I/O（缓存类 module 在锁外抓取、锁内仅更新 dict）。  
3. **单飞 / 防丢更新**：长时间刷新用 `acquire(blocking=False)` 或独立 `_BG_LOCK` 避免并发覆盖。  
4. **SQLite**：`message/store` 使用 WAL + `timeout=30`，应用层再用 `RLock` 串行化复合操作。  
5. **持锁重入与 IO 线程**：非可重入 `Lock` 禁止在 `with lock:` 内再调同模块带锁函数；WebSocket 读线程只入队。详见 [lock-safety.md](./lock-safety.md)。

### 6.1 锁一览

| 模块 | 锁 | 类型 | 保护对象 | 典型场景 |
|------|-----|------|----------|----------|
| `server.py` | `_lock` | `Lock` | `_job` 复盘任务状态 | 启动/结束复盘、查询 `/api/review/status`；原子 check-then-act 防双开 |
| `server.py` | `_wk_lock` | `Lock` | 周报计算 | `build_weekly` 非阻塞 `acquire`；计算中返回 `busy` 或旧缓存 |
| `duanxian/trade_calendar.py` | `_quote_day_lock` | `Lock` | `_quote_day_cache` | 腾讯行情推断交易日；双检锁防开盘前后慢请求覆盖 |
| `duanxian/live_emotion.py` | `_lock` | `Lock` | 内存 TTL 缓存 | 打板情绪按 key 缓存 |
| `duanxian/short_board.py` | `_lock` | `Lock` | 内存 TTL 缓存 | 环境条按 key 缓存 |
| `duanxian/mood_block.py` | `_lock` | `Lock` | 板块人气缓存 | 开盘啦 list 合并结果 |
| `duanxian/market_series.py` | `_LOCK` | `Lock` | 序列读缓存 / 迁移 | 两融、上证、成交额等 |
| `duanxian/market_series.py` | `_BG_LOCK` | `Lock` | `_BG_RUNNING` | 后台 `ensure_fresh_background` 单飞 |
| `duanxian/series_store.py` | `_LOCK` | `Lock` | SQLite 连接与写入 | 市场日序列落盘 |
| `duanxian/aktools_service.py` | `_LOCK` | `Lock` | `_PROC` 子进程 | 启动/停止 AKTools；防重复拉起 |
| `duanxian/trade_store.py` | `_LOCK` | `Lock` | 交易读数 JSON | 预算读数组装与刷新 |
| `duanxian/trade_threshold_config.py` | `_LOCK` | `Lock` | 阈值配置 | 读-改-写本地配置 |
| `duanxian/trade_phase_config.py` | `_LOCK` | `Lock` | 阶段配置 | 同上 |
| `duanxian/zt_keywords.py` | `_LOCK` | `Lock` | 涨停原因词表 | 用户编辑与持久化 |
| `duanxian/theme_normalize.py` | `_LOCK` | `Lock` | 题材别名表 | 别名映射缓存 |
| `duanxian/message_follow_keywords.py` | `_LOCK` | `Lock` | 消息关注词 | 关键词配置 |
| `duanxian/experience.py` | `_LOCK` | `Lock` | 经验库索引 | 笔记 CRUD |
| `duanxian/articles.py` | `_LOCK` | `Lock` | 研报文章索引 | 文章落盘与 index 刷新 |
| `duanxian/sentiment_score.py` | `_LOCK` | `Lock` | 情绪分缓存 | 计算结果 memo |
| `duanxian/current_stock.py` | `_lock` | `Lock` | `_current`、SSE 监听列表 | 当前看盘标的切换与推送 |
| `vr/message/store.py` | `_LOCK` | `RLock` | SQLite + 复合事务 | 消息入库、分析结果、列表查询 |
| `vr/message/archive.py` | （复用 store） | — | 与 store 同锁 | 归档批量操作 |
| `vr/message/poller.py` | `_LOCK` | `Lock` | `_STARTED` | 轮询钩子仅启动一次 |
| `vr/portfolio.py` | `_LOCK` | `Lock` | `portfolio.json` | 持仓读-改-写、定时刷新 |
| `vr/watchlist.py` | `_LOCK` | `Lock` | 自选 JSON | 自选同步 |
| `vr/myreports.py` | `_LOCK` | `Lock` | 报告索引 | 上传/删除防互相覆盖 |
| `vr/stock_universe.py` | `_REFRESH_LOCK` | `Lock` | 刷新状态 | 股票列表网络刷新单飞 |
| `vr/signals.py` | `_FETCH_LOCK` | `Lock` | GPU 租约缓存 | 整段刷新串行化，防慢请求覆盖新结果 |
| `vr/watchtower.py` | `_lock` | `Lock` | `_extra_watch` | 额外监控列表 |
| `vr/ths_block/cache.py` | `_LOCK` | `Lock` | 全局板块快照 | 内存快照 get/set |
| `vr/ths_block/processor.py` | `_LOCK` | `Lock` | 待匹配队列、名称索引 | 板块字符串匹配状态 |
| `vr/ths_block/processor.py` | `_ENSURE_LOCK` | `Lock` | `_ENSURE_*` 标志 | 懒加载 ensure 与异步调度 |
| `vr/ths_block/service.py` | `_REFRESH_LOCK` | `Lock` | 刷新状态 | 同花顺目录刷新单飞 |
| `plugins/vibe-ths-linker/plugin.py` | `_send_lock` | `Lock` | WebSocket 发送 | 多线程发帧互斥 |
| `plugins/vibe-ths-linker/plugin.py` | `_response_lock` | `Lock` | 响应队列 | 请求-响应配对 |

### 6.2 典型模式

**复盘任务（`server._lock`）**

```text
POST /api/review/run
  → with _lock: 若已有 running 且未超时 → 直接返回 busy
  → 否则写入 job_id / started
  → 后台线程 _run_review
  → finally: with _lock: 仅当 job_id 匹配才清 running
```

**缓存双检（`live_emotion` / `short_board` / `trade_calendar`）**

```text
with lock: 命中 TTL → 返回
（锁外）计算或请求网络
with lock: 写入缓存
```

**消息库（`RLock`）**

复合操作（插入 + 关联分析 + 列表过滤）在 store 层整体持锁，避免 WAL 下多语句交错；单连接 `timeout=30` 减轻 SQLITE_BUSY。

**未使用锁的写路径**

单次 `json.dump` 到独立路径后 `os.replace` 的路径（复盘落盘、周报 `latest.json`）依赖 **原子替换** 而非互斥锁；并发写同一文件仍可能丢更新，故周报额外用 `_wk_lock` 串行化计算。

---

## 7. 相关文档

完整索引见 [doc/README.md](../README.md)。

| 文档 | 说明 |
|------|------|
| [plugin-development.md](./plugin-development.md) | 插件 API |
| [lock-safety.md](./lock-safety.md) | 锁安全、死锁回归测试、静态扫描 |
| [hook-lifecycle.md](./hook-lifecycle.md) | 钩子加载与派发顺序 |
| [todo/架构加深-后续.md](./todo/架构加深-后续.md) | 架构演进 backlog |
| [research/](./research/) | AI / 情绪判定等调研 |
| [../仓位预算-定档规则.md](../仓位预算-定档规则.md) | 业务定档规则 |
| [../消息来源.md](../消息来源.md) | 消息数据源说明 |

---

## 8. 后续演进

当前已知架构债与计划项见 [todo/架构加深-后续.md](./todo/架构加深-后续.md)（定稿日档案、风险姿态收拢、VR host、前端 view-model、钩子 emit 半边等）。
