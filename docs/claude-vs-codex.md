# Claude 与 GPT：模型差异和 Harness 差异

## 先分清两个问题

“Claude 和 GPT 有什么不同”其实包含两层：

1. **模型层**：Anthropic Claude 和 OpenAI GPT 的 API、能力、推理控制、上下文和价格；
2. **Harness 层**：Claude Code 和 Codex 如何组织上下文、工具、循环、权限、事件和记忆。

模型能力不是 Harness 架构。Claude Code 可以用不同 Claude 模型，Codex 也可以用不同 GPT 模型；真正决定“用起来像不像”的很大一部分是 Harness。

## 模型层

| 维度 | Claude | GPT |
|---|---|---|
| API 形态 | Anthropic Messages API | OpenAI Responses / Chat Completions |
| 工具调用表达 | `tool_use` / `tool_result` 内容块 | function call / tool call + tool output |
| 推理控制 | 支持 thinking/adaptive thinking、effort 等模式 | 支持 reasoning effort；具体参数依模型 |
| 上下文与价格 | 按具体 Claude 模型变化 | 按具体 GPT 模型变化 |
| 提示缓存 | 有 prompt caching / cache breakpoint | 有 OpenAI 平台自己的 prompt caching 机制 |

重要：不要用“Claude 一定适合长文、GPT 一定适合代码”这种固定结论。模型版本、上下文窗口、工具协议和价格都会变化，应该按当前官方文档和实际评测选择。

官方参考：

- Claude tool use：https://docs.anthropic.com/en/docs/build-with-claude/tool-use/overview
- Claude thinking：https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
- Claude prompt caching：https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- OpenAI API：https://platform.openai.com/docs/

## Harness 层

| Harness 层 | Claude Code | Codex |
|---|---|---|
| 主要实现 | Bun/TypeScript/Ink CLI | Rust core + CLI/app-server |
| 单轮主循环 | `query.ts` 的 `queryLoop` AsyncGenerator 状态机 | `session/turn.rs` 的 `run_turn` |
| 项目指令 | `CLAUDE.md`、`.claude/rules/`、`CLAUDE.local.md` | `AGENTS.md`、`AGENTS.override.md` |
| 工具风格 | Read/Write/Edit/Bash/Glob/Grep/Agent/Task/MCP | exec_command/apply_patch/update_plan/MCP 等 |
| 权限 | permission mode + tool rules + hooks | sandbox + approval policy |
| 上下文压缩 | microcompact → full compact/session memory | token budget + compaction |
| 并行/子 Agent | AgentTool、Task、SendMessage、TaskOutput、fork subagent | spawn/send_input/wait/resume/close/list |
| 事件/UI | AsyncGenerator 消息 + Ink 终端 UI | EventMsg 流 + app-server/CLI UI |
| 记忆 | CLAUDE.md、Auto Memory、Session Memory、Agent Memory | AGENTS.md、会话历史、rollout/checkpoint |

## 相同点

两者都不是“直接调用一次模型”：

- 都有模型 ↔ 工具循环；
- 都要构建系统提示和项目上下文；
- 都有工具权限/执行边界；
- 都处理上下文窗口和压缩；
- 都会把过程拆成事件给 UI；
- 都支持 MCP 和某种形式的多 Agent。

## 不同点

### Claude Code 更突出“项目规则和权限模式”

- `CLAUDE.md` 的分层加载；
- `default` / `plan` / `acceptEdits` / `bypassPermissions` / `dontAsk` 等权限模式；
- `TodoWrite`、Task/SendMessage/TaskOutput、hooks；
- microcompact/full compact 和 session memory；
- 大量行为在 Prompt + Tool + Permission 三层协同。

### Codex 更突出“低层运行时和事件协议”

- Rust core 的 `Session` / `TurnContext` / `StepContext`；
- `run_turn` 的 sampling/tool loop；
- `EventMsg` 的结构化事件；
- `exec_command` + `apply_patch` + sandbox/approval；
- app-server 作为可嵌入产品的协议边界；
- 多 Agent 的 mailbox、wait、resume、close 生命周期。

## 本项目怎么复刻

- Codex-style：`mini_codex/`，复刻 `run_turn`、AGENTS.md、EventMsg 时间线和工具循环；
- Claude-style：`claude_harness/`，复刻 `queryLoop`、CLAUDE.md、权限模式、TodoWrite、microcompact、Task 和 MCP；
- 两套实现共用当前百炼 DeepSeek 模型，但保留各自的 Harness 结构。

因此：

- 想学“Agent 运行时/事件/沙箱/审批” → 先看 `mini_codex`；
- 想学“项目规则/权限/hooks/上下文压缩/子 Agent” → 先看 `claude_harness`；
- 想看两者对照 → 读 `docs/agent-systems-glossary.md` 和两个 Notebook。
