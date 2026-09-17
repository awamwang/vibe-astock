---
name: experience-memory-batch
description: >-
  把交易日记/复盘表（TSV、表格、逐行笔记）按经验记忆格式逐行整理成主题 Markdown，
  由 Agent 抽取标题、分类、摘要、个股与板块后直接调用 duanxian.experience.commit_files 落盘。
  在用户要批量导入经验、把交易记录整理进经验记忆库、或提到经验记忆批量处理时使用。
---

# 经验记忆批量整理

把日记表整理成可检索的主题记忆，**每行一条**，Agent 当场整理后直接落盘，不走前端「预览确认」。

落盘目录：`~/.duanxian-agents/experience/`（经 `commit_files` 写主题 Markdown 并刷新 `index.md`）。

## 何时用

- 用户贴出带日期/标的/买卖条件/备注的交易日记表
- 要求「按经验记忆整理」「批量写入经验库」
- 提到经验记忆批量处理、逐行落盘

## 何时不用

- 只记一条随手心得、要先预览再写入 → 走前端「经验记忆」页的 AI 整理
- 改 `duanxian/experience.py` 的存储格式（除非任务明确要求改系统侧）

## 流程

1. **拆行**：跳过表头；空行忽略。一格多行仍算一行。
2. **读已有库**：`python -c "from duanxian import experience as exp; import json; print(json.dumps(exp.get_meta(), ensure_ascii=False, indent=2))"`
3. **逐行整理**：按 [schema.md](schema.md) 写成 `files[]` 项。日记默认**每行一条新主题**，不要因为教训相似就合并。
4. **去重**：仅当库中已有**同一天 + 同一标的 + 同一事件**的主题时，跳过或并入该 `filename`。
5. **落盘**：把 `{"files":[...]}` 交给脚本，一次提交（超过 50 条则每批 ≤20）。

```bash
python skills/experience-memory-batch/scripts/commit.py path/to/files.json
```

也可 stdin：`python skills/experience-memory-batch/scripts/commit.py -`

6. **核对**：看脚本打印的 `written` 条数与 `index.md`；向用户列出标题、分类、日期。不要把整篇正文贴回聊天。

## 整理规则（对齐前端 `buildOrganizePrompt`）

1. 主题名用简洁中文概括**这条经验的核心**，禁止口号；标题不要手写日期（`commit_files` 会加 `-YYYY-MM-DD`）。
2. `date` 用该行日期，规范为 `YYYY-MM-DD`（`2026/01/19` → `2026-01-19`）。
3. `filename` 可省略，系统按「标题-日期.md」生成；合并已有主题时必须沿用其 `filename`。
4. `category` 只能是：`踩坑` / `操作指引` / `方法论` / `盘感复盘` / `仓位纪律`。判定见 [schema.md](schema.md)。
5. `summary` 一句话，≤40 字。
6. `stocks` / `sectors` 只写文中出现的；代码未知则 `code` 省略，写入时会再扫描正文补全。
7. `content` 只写正文 Markdown，**不要**再写标题、日期、分类、个股、板块元数据行。
8. 保留用户原话里的交易黑话（如「不买人」「零轴」「买人」），可加半句解释，不要改写成空话。
9. 备注为空时不要编造反思；写明「日记未记录具体动作」，要点只从计划字段提炼。
10. `❌` / `❌️` 不是标题，只作分类线索；`✅` 仍可能是踩坑（计划对、执行错）。

## 列映射

| 日记列 | 写入 |
|--------|------|
| 日期 | `date` |
| 类别（个股/大盘） | 正文情景，不是 `category` |
| 标的 | 个股名或主题名；个股进 `stocks` |
| 描述 / 买入条件 / 卖出条件 | 「标的与计划」 |
| 操作 / 操作结果 | 「实际操作」 |
| 仓位 | 正文里的仓位；数字在卖出条件里则当止盈/止损 |
| 优先级 | 有则写入计划，无则省略 |
| 备注 | 「认知反思」+「复用要点」的主要来源 |

## 正文骨架

个股/计划行用：

```markdown
## 标的与计划
## 实际操作
## 认知反思
## 复用要点
```

大盘/环境行把第一节改成 `## 盘面情景`。

## 完成检查

- [ ] 表头未当成经验
- [ ] 每行对应 `files` 一项（去重跳过的要在结果里说明）
- [ ] 分类落在五个枚举内
- [ ] 已 `commit.py` 落盘，不是手写 `experience/` 文件
- [ ] 向用户汇报写入条数、跳过条数、库路径
