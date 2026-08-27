<p align="center"><b>简体中文</b> | <a href="README_en.md">English</a></p>

<h1 align="center">Vibe-Astock</h1>

<p align="center">
  <b>A 股短线复盘看板 —— 打开就看清今天的短线情绪</b><br>
  派生情绪指标 · 全本地运行 · 可用本机 CLI 订阅免 key
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.12-3776AB.svg?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/react-19-61DAFB.svg?logo=react&logoColor=white" alt="React">
  <img src="https://img.shields.io/badge/tests-341%20passing-brightgreen.svg" alt="Tests">
  <img src="https://img.shields.io/badge/version-v0.1.1-orange.svg" alt="Version">
</p>

<p align="center">
  <a href="#这是什么">这是什么</a> ·
  <a href="#界面">界面</a> ·
  <a href="#当前版本包含">当前版本</a> ·
  <a href="#核心派生情绪指标">派生情绪指标</a> ·
  <a href="#架构">架构</a> ·
  <a href="#自定义分析口径prompt-包">自定义口径</a> ·
  <a href="#钩子插件">钩子插件</a> ·
  <a href="#快速开始">快速开始</a> ·
</p>

<p align="center">
  <b>⚠️ 本项目只做公开盘面数据的整理、统计与市场层面研判，不推荐个股、不预测涨跌、不给买卖时机。<br>
  不构成任何投资建议，也不提供任何投资服务。</b>
</p>

---

## 这是什么

**帮你把今天的复盘做完。**

短线复盘每天要翻涨停池、连板梯队、龙虎榜、板块资金、题材归因，再算一遍昨日涨停股今天赚不赚钱。
这套东西每天重复一小时。Vibe-Astock 把它自动化：拉数据 → 五个分析师各读一面 →
收敛成一份能读的盘面研判。

复盘本身是**事实工作**（把今天发生的事整理清楚），本来就不需要推荐。
所以屏幕上九成是**硬指标层**——赚钱效应 / 晋级率 / 梯队结构 / 情绪周期 / 亏钱效应 /
封板质量 / 题材事件树 / 历史统计位置——**全部纯计算、数据源直出，不经过 AI，打开就有**。
AI 的角色是把七八个数据源串成一个能读的故事，不是选股。

**它不做什么**：不推荐个股、不给参与倾向、不给买卖点位。个股一律只作客观陈述
（属于哪个题材、几板、龙虎榜谁在买、技术位置如何）。方向与情绪判断做到板块层面为止。

---


## 界面

**复盘看板** —— 打开就有的硬指标层。全市场宽度当分母，昨日强势股今天落到哪一档，赚钱效应与亏钱效应对着看。

<img src="assets/screenshots/01-review-metrics.png" alt="复盘看板：全市场宽度 / 昨日强势股反馈 / 赚钱效应 / 亏钱效应">

**明日验证条件** —— 把今晚的判断变成明天能对账的东西：每条都带今日基准值和"变动超过多少才算数"的阈值。

<img src="assets/screenshots/02-verification.png" alt="明日验证条件：每条带今日基准值与阈值">

**盘面数据** —— 指数、隔夜外围（含美股七姐妹）、板块资金、成交额榜、今日实时打板情绪，可开自动刷新。

<img src="assets/screenshots/03-market-data.png" alt="盘面数据：大盘指数与隔夜外围">

**近5天热度 + 龙头谱系** —— 五个交易日的情绪走向，以及前几天的龙头现在跌到哪了。

<img src="assets/screenshots/04-heat.png" alt="近5天情绪热度与龙头谱系">

---

## 当前版本包含

**v0.1.1** —— 侧栏五个入口：

| 入口 | 是什么 |
|---|---|
| **复盘看板** | 主体，默认落地页。AI 叙述在页顶，硬指标在下方 |
| 盘面数据 | 指数 / 板块资金 / 资金轮动 / 热点个股 |
| 首板分析 | 当日首板池与封板结构 |
| 近5天热度 | 近 5 个交易日的题材热度变化 |
| 接入 AI | 配 API key 或本机 CLI（见下） |

## 核心：派生情绪指标

涨停家数只是原料。真正决定盘面状态的是这几个**派生**读数：

| 指标 | 说明 | 为什么重要 |
|---|---|---|
| **赚钱效应** | 昨日涨停股今天的均值 / **中位数** / 翻红率 / 再涨停率 | 涨停 40 家但昨日涨停股今天中位 -1.8%，那是退潮；涨停 25 家但中位 +4%，那是健康 |
| **晋级率** | 昨日各档连板今天仍涨停的比例（1进2 / 2进3 / 3板以上） | **1进2 最敏感**：明显走低=退潮，回升=修复 |
| **连板溢价** | 昨日 2 板以上个股今天的表现 | 高标承接度 |
| **梯队结构** | 各档连板家数 + 断层检测 | 有 5 板和 2 板却缺 3-4 板 = 最高标悬空，断板后无下一梯队承接 |
| **情绪周期** | 近 10 个交易日情绪分曲线，定位本轮起点与"第几天" | 知道现在处在周期什么位置 |

> ⚠️ **均值与中位数经常背离**——少数大涨会把均值拉起来。看"多数人的体感"以中位数为准。

---

## 架构

```
涨停池 / 龙虎榜 / 板块资金 / 题材归因 / 腾讯行情
        ↓
派生情绪指标 + 客观事实表（纯计算，不经过 AI —— 屏幕上的九成）
        ↓
五个短线分析师（情绪面 · 资金面 · 题材热点 · 龙虎榜游资 · 龙头跟踪）
        ↓
复盘裁判 → 结构化盘面研判
        （情绪档位 / 活跃方向 + 依据 + 风险证伪条件 / 风险提示）
```


---

## 自定义分析口径（Prompt 包）

引擎（数据管线 / 多 agent 编排 / 反思闭环）是通用的；**说什么、说到什么程度**由 prompt 包决定。
每个人的短线体系不一样——有人看情绪周期，有人只做首板，有人只跟资金——所以这一层做成可替换的。

本仓库自带 `RESEARCH_PACK`（市场与板块层面的观察与研判）。想换一套口径：

最省事的写法 —— 只换措辞，结论 schema 沿用自带的（这段可以直接照抄跑）：

```python
# ~/.vibe-astock/prompts_local.py
from duanxian.prompts import PromptPack, RESEARCH_PACK

PACK = PromptPack(
    name="my-style",
    analyst_style="只讲情绪周期位置和晋级率，别的少说。",   # 五个分析师的语气与尺度
    analyst_len="控制在 250 字内。",
    judge_requirements="""1. 判断当前市场情绪档位（冰点/修复/发酵/亢奋/退潮）。
2. 说清这个档位的依据是哪几个读数。
3. 列出需警惕的风险信号。""",                              # 裁判的产出要求
    # 下面三个是一组，要么全用自带的，要么自己写一整套
    focus_model=RESEARCH_PACK.focus_model,      # = schemas.TomorrowFocus
    focus_skeleton=RESEARCH_PACK.focus_skeleton,
    render_focus=RESEARCH_PACK.render_focus,
)
```

想连结论结构一起换，就自己定义 `focus_model`（pydantic 模型）、
`focus_skeleton`（给 JSON 模式的英文键骨架）和 `render_focus`（模型 → markdown），
三个必须配套。完整字段见 `duanxian/prompts.py` 的 `PromptPack`，
可照 `duanxian/schemas.py` 里 `TomorrowFocus` 的写法改。

引擎会自动发现该文件（也可用环境变量 `VIBE_ASTOCK_PROMPTS` 指向任意路径），加载失败会打印原因并回退默认包。
该文件在本仓库之外、不随代码分发；写什么、怎么用、由此产生的责任由使用者自负，
并请自行确认所在司法辖区对相关活动的资质要求。

---

## 钩子插件

引擎在复盘落盘、仓位预算刷新、验证条件保存等节点，可向已注册插件 **推送结构化快照**（情绪指标、预算档位、验证条件等）；插件也可通过 `HookRegistry` **回写** 持仓、账户与预算覆盖档。

与 Prompt 包正交：Prompt 管「怎么说」，插件管「数据进出引擎」。

| 文档 | 内容 |
|---|---|
| [doc/README.md](doc/README.md) | **文档索引**（领域规则、开发文档、待办） |
| [doc/development/architecture.md](doc/development/architecture.md) | 代码分区、数据流、并发加锁 |
| [doc/development/hook-lifecycle.md](doc/development/hook-lifecycle.md) | 进程加载、事件触发顺序、`emit_after_review` 链路 |
| [doc/development/plugin-development.md](doc/development/plugin-development.md) | `HookPack` 写法、`HookRegistry` API、自定义验证指标、CLI |

最简注册：

```bash
python -m duanxian.plugin_cli register ~/.vibe-astock/plugins/my_bridge.py
# 修改注册表或插件文件后需重启 server
```

注册表：`~/.vibe-astock/plugins.json`。

---

## 快速开始

```bash
# Python >= 3.10（akshare 新版要求）
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

前端要先构建（构建产物不进 git，由后端直接服务）：

```bash
cd frontend && npm install && npm run build
```

配置 LLM —— **两条后端，有哪个用哪个**：

**① 有 OpenAI 兼容的 API key**（默认，示例是 MiMo）：

```bash
# ~/.config/mimo/mimo.env
MIMO_API_KEY=...
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5-pro
```

**② 只有 Claude / Codex 订阅、没有 API key**：走本机已登录的 CLI，免 key。

```bash
VIBE_LLM_CLI=claude .venv/bin/python server.py
```

> ⚠️ 在 server 上跑 **claude 以外**的 CLI，还要显式加 `VIBE_ALLOW_UNSAFE_CLI=<同一个>`。
> 不自动放开是有意的：那会连「网页里问 AI」一起放开，而那条路会把抓来的外部新闻原文
> 塞进 prompt，注入面比复盘大得多。`claude` 分支带 `--disallowedTools`，做一次性问答够用。
> 用 `python main.py` 独立跑复盘则不需要第二个开关。

<details>
<summary><b>Windows 用户看这里（上面的命令是 macOS / Linux 写法）</b></summary>

Windows 上有两处不一样：解释器路径是 `.venv\Scripts\python`（不是 `.venv/bin/python`），
环境变量不能写在命令前面，要先单独设。

**PowerShell**（推荐）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 前端必须先构建，否则打开页面是 503（frontend/dist 不进 git）
cd frontend; npm install; npm run build; cd ..

# ① 用 API key：照上面写 mimo.env，路径是 $env:USERPROFILE\.config\mimo\mimo.env
# ② 用本机 CLI 订阅：
$env:VIBE_LLM_CLI = "claude"
.venv\Scripts\python server.py
```

**CMD**：

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

rem 前端必须先构建，否则打开页面是 503
cd frontend && npm install && npm run build && cd ..

set VIBE_LLM_CLI=claude
.venv\Scripts\python server.py
```

要跑 `claude` 以外的 CLI，同样要加第二个开关（PowerShell：
`$env:VIBE_ALLOW_UNSAFE_CLI = "codex"`；CMD：`set VIBE_ALLOW_UNSAFE_CLI=codex`）。

前提是那个 CLI **已经装好并登录过**，在同一个终端里直接敲 `claude` 能进得去——
后端只是去 PATH 里找它、复用它的登录态，不会替你登录。
如果 `claude` 单独能跑、经 server 却报「未检测到」或起不来，
请把完整报错贴到 [issue](https://github.com/simonlin1212/vibe-astock/issues) 里，
注明 Windows 版本和 CLI 的安装方式（npm / 安装包），我们跟进。

</details>

跑起来：

```bash
.venv/bin/python server.py          # 一个进程一个端口 :8910，五个入口全在
```
```bash
.venv/bin/python main.py            # 或者 CLI 直接跑今天的复盘
```

⚠️ **复盘的对象只能是已经收盘的那一场。** 不带日期时自动取最近已收盘交易日；
指定一个还没收盘的日子会被拒绝并指回那一场（涨停池 / 龙虎榜盘中都还没定稿，
喂进去只会让 AI 硬凑）。那一场已经跑过就直接看，不重跑；要重跑加 `?force=1`。

**历史场次随时能看**：赚钱效应 / 亏钱效应 / 连板溢价 / 昨日强势股反馈都优先走
**定稿记录**（已收盘的日子落盘缓存，否则走东财昨日涨停池），不依赖实时行情 ——
所以盘中也能翻上周三那份复盘。

数据落在 `~/.duanxian-agents/`（复盘 / 热度 / 缓存），盘面数据那几个分栏落 `~/.vibe-research/`。

### 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `VIBE_PORT` | `8910` | 后端端口 |
| `VIBE_LLM_CLI` | 未设 | 用本机 CLI 当 LLM（`claude` / `codex` …），设了就不需要 API key |
| `VIBE_ALLOW_UNSAFE_CLI` | 未设 | 放开 `claude` 以外的 CLI，逗号分隔（见上面那条提醒） |
| `VIBE_ASTOCK_PROMPTS` | `~/.vibe-astock/prompts_local.py` | 换一套分析口径（见「自定义分析口径」） |
| `VIBE_ALLOW_HOSTS` | 未设 | 挂到域名下访问时把域名加进来，否则写操作 403 |
| `VIBE_MARKET_PROXY` | 未设 | 东财在你这儿**只能经代理**才连得上时设 `1`。等同于 `VR_DATA_PROXY=1`，设哪个都行 |
| `VIBE_MARKET_DIRECT` | 未设 | 相反方向：代理把东财挂掉、连取涨停池都失败时设 `1` 强行直连。⚠️ 它是**进程级**的，会一并关掉东财请求的代理回退 |
| `VR_API_KEY` | 未设 | 给盘面数据那几个分栏的接口加一层 key 校验 |

---

## 数据源

| 来源 | 提供 | 要 key 吗 |
|---|---|---|
| akshare（东财涨停池 / 龙虎榜） | 涨停 · 炸板 · 跌停 · 连板梯队 · 龙虎榜席位 | 不要 |
| 东财 `push2delay` clist | 板块 / 个股资金流、成交额榜 | 不要 |
| akshare 昨日涨停池 | **定稿记录**：昨日涨停股在目标日的表现（赚钱效应 / 亏钱效应 / 连板溢价 / 反馈矩阵的主来源）| 不要 |
| 腾讯财经 `qt.gtimg.cn` | 实时行情批量（自选股、今日实时打板情绪；也作上面那几项的兜底）| 不要 |
| 腾讯 hist `stock_zh_a_hist_tx` | K 线与交易日历（部分网络下东财 push2his 被封，故走腾讯） | 不要 |
| 同花顺涨停池 `data.10jqka.com.cn` | 涨停原因题材串（→ 题材事件树；与 [zvt LimitUpInfo](https://github.com/zvtvz/zvt) 同源） | 不要 |
| [pywencai](https://github.com/zsrl/pywencai)（备用） | 同上，主源失败时回退 | cookie |
| 同花顺问财 openapi（再备用） | 同上 | `IWENCAI_API_KEY` |

题材串**默认免费**走同花顺涨停池；失败再试 pywencai（需 `IWENCAI_COOKIE` +
Node.js 16+），再失败可走 `IWENCAI_API_KEY`。全失败时「题材事件树」如实标成不可用
（复盘其余部分不受影响）。备用配法写在仓库根 `.env`：

```
IWENCAI_COOKIE=从问财网页请求头复制的Cookie
# 或
IWENCAI_API_KEY=你的key
```

历史交易日的涨停池摘要会落盘缓存（`~/.duanxian-agents/cache/`）——它们是不会再变的事实，
第二次起几乎零成本。

---

## 测试

```bash
.venv/bin/python -m pytest -q
```

341 个用例，覆盖指标计算、口径边界与降级路径 —— 重点在那些**错了也看不出来**的地方：
界面照常渲染、数字看着合理，但结论是错的。

---


## 免责声明

> - 本系统产出的所有内容均由 AI 自动生成，可能存在错误或偏差
> - 本项目不构成任何投资建议；投资决策请咨询持有相应资质的专业机构
> - 作者不对使用本工具产生的任何损失承担责任
> - 股市有风险，投资需谨慎

## 赞赏

觉得有用的话，可以请我喝杯咖啡 ☕

<p align="center">
  <a href="https://buymeacoffee.com/simonlin1212"><img src="./assets/bmc-qr.png" width="180" alt="Buy Me a Coffee"></a>
</p>

## License

Apache-2.0，详见 [LICENSE](LICENSE)。

**作者：** Simon 林 · X [@linsizhen](https://x.com/linsizhen) · 邮箱：[simonlin0423@gmail.com](mailto:simonlin0423@gmail.com)
