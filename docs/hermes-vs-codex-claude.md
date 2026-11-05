# Hermes、Codex、Claude Code：通用 Agent 与开发 Agent 的区别

先区分两层：

1. **模型层**：DeepSeek、GPT、Claude 等模型本身的能力；
2. **Harness 层**：模型外面的上下文、工具、循环、权限、状态和记忆系统。

本项目的三套 mini 都接同一个百炼 OpenAI 兼容模型，所以差异主要来自 Harness。

## 1. 一句话定位

| Harness | 定位 | 最核心的学习点 |
|---|---|---|
| Mini Codex | 开发场景 | `run_turn`、`AGENTS.md`、工具循环、事件流、验证 |
| Claude-style Harness | 开发场景 | `queryLoop`、`CLAUDE.md`、权限模式、hooks、Todo、压缩 |
| Hermes mini | 通用任务 | 长期记忆、技能学习、后台复盘、历史检索、toolset |

Hermes 不是“更强的 Codex”。它把“完成任务”扩展成了“完成任务并在以后做得更好”；
Codex/Claude Code 则把“在代码仓库里安全地改代码”做得更深入。

## 2. 控制流差异

### Mini Codex

```text
bootstrap → context → plan → agent(Python 循环)
  model → tool_calls → tools → model
  no tool_calls → verify → finalize
```

- 主循环是一个清楚的 Python `for`；
- `EventMsg` 风格事件写入 `events.jsonl`；
- 有 `AGENTS.md`、文件工具、命令白名单、计划、diff；
- 没有动态 `SKILL.md` 学习闭环。

### Claude-style

```text
prepare → plan → model
  tool_calls → tools → compact → model
  no tool_calls → finalize
```

- 用 LangGraph 显式节点和条件边；
- 先做 permission decision，再执行 hooks 和工具；
- `CLAUDE.md` 分层加载，session memory 跨 turn；
- 有 `microcompact` / `full_compact`；
- 当前只是 `InMemorySaver`，没有真正的中断恢复和 HITL UI。

### Hermes mini

```text
prepare → model → tools → model ... → finalize → background_review
```

- 通用 Agent 的工具循环；
- 每轮结束可以 fork 独立模型复盘；
- 复盘只写 memory/skills，不能改 workspace；
- 下次新会话自动注入记忆和技能索引；
- `session_search` 可以在历史对话中检索证据。

## 3. 上下文差异

| 维度 | Mini Codex | Claude-style | Hermes mini |
|---|---|---|---|
| 项目规范 | `AGENTS.md` | `CLAUDE.md` + rules + local | `SOUL.md` + 环境 |
| 长期用户偏好 | 无 | session memory 摘要 | `USER.md` |
| 环境长期事实 | 无 | 无独立存储 | `MEMORY.md` |
| 程序性记忆 | 无 | 无动态技能 | `skills/SKILL.md` |
| 历史检索 | 无 | session memory 摘要 | SQLite FTS5 `session_search` |
| 工具面 | 开发工具固定 | 开发工具 + 权限 + hooks | toolset 按场景裁剪 |

## 4. 安全与权限差异

- Mini Codex 用 **workspace 路径边界 + 命令黑名单/白名单**；
- Claude-style 用 **permission mode + pre/post hooks + 工具元数据**；
- Hermes mini 用 **toolset 裁剪 + 敏感文件过滤 + 后台 review 白名单**。

三者都不是 OS 级 sandbox。真实 Codex 还会使用 sandbox、approval policy 和
app-server 协议；真实 Claude Code 还有更完整的 permission rules 和 hooks；
真实 Hermes 有远程 terminal backend 和平台级工具权限。

## 5. “恢复”和“可视”不是同一件事

- `events.jsonl` / `timeline.md`：记录发生了什么，可回放，但不一定能恢复执行；
- LangGraph `InMemorySaver`：保存图状态，但进程退出后不保证持久恢复；
- Hermes 的 SessionDB / transcript / 文件 checkpoint：保存长期历史与文件状态；
- 真正的暂停/审批/恢复需要 durable checkpointer、interrupt/resume 和 UI 协议。

学习时不要看到“有 checkpoint”就认为“已经实现了断点续跑”。

## 6. 多 Agent 差异

Codex 和 Claude 的 mini 版都有子 Agent：

- Codex：`spawn_agent` / `send_input` / `wait_agent` / `close_agent`；
- Claude：`Task` / `SendMessage` / `TaskOutput` / `TaskList` / `CloseAgent`；
- 二者共用 `agent_runtime/` 的 mailbox 思路：消息在子 Agent 下一轮边界消费。

Hermes 真实版有 `delegate_task`，本 mini 版没有把子 Agent 作为主链路，而是优先
展示学习闭环。若扩展，可复用同一个 `agent_runtime`。

## 7. 怎么选

- 想学习“如何在代码仓库里安全地读、改、测” → 先看 `mini_codex`；
- 想学习“权限、hooks、CLAUDE.md、LangGraph 编排” → 看 `claude_harness`；
- 想学习“长期记忆、技能自动积累、历史检索、通用工具面” → 看 `hermes_harness`；
- 想做真正生产级编码 Agent → 在 Codex/Claude 的 sandbox、审批、持久 checkpoint 上继续加；
- 想做个人通用助理 → 在 Hermes 的 memory/skills/gateway 基础上继续加。

## 8. 源码入口

- `mini_codex/harness.py:99`：`run()` 和开发 turn
- `claude_harness/harness.py:316`：LangGraph 节点注册
- `hermes_harness/harness.py:156`：Hermes mini 主循环
- `hermes_harness/review.py:76`：后台复盘
- `hermes_harness/memory.py`：`MEMORY.md` / `USER.md`
- `hermes_harness/skills.py`：`SKILL.md` / curator
- `hermes_harness/sessions.py`：SQLite FTS5
