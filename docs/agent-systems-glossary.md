# Agent Systems 名词表：从模型到 Harness

这份表用于快速理解 Claude Code、Codex、Mini Codex、Claude-style Harness 和 Hermes mini 里的名词。
先记住一句话：

> Agent = Model + Instructions + Context + Tools + Loop + Policy + State + Events

## 1. 基本对象

| 名词 | 含义 | Codex 对应 | Claude Code 对应 |
|---|---|---|---|
| Agent | 能理解目标、选择工具并完成任务的运行体 | `Agent` / Coding Agent | 主 Agent、Task 子 Agent |
| Harness | 包在模型外面的运行时：上下文、工具、循环、权限、事件 | Codex core / app-server | `queryLoop`、Tool runtime、REPL |
| Session | 一段可恢复的工作会话 | `Session` | session / transcript |
| Thread | 一条独立的对话或任务线程 | `thread_id` | agentId / session |
| Turn | 用户发起的一次完整请求 | `run_turn` | `queryLoop` 的一次 query |
| Step / Round | Turn 内的一轮模型采样或工具执行 | `StepContext` | tool round / query iteration |

## 2. 上下文与压缩

| 名词 | 含义 |
|---|---|
| System Prompt | 常驻的模型行为说明 |
| Developer Instructions | 宿主应用追加的高优先级指令 |
| User Instructions | 用户/仓库提供的上下文 |
| `AGENTS.md` | Codex 自动加载的仓库级指令 |
| `CLAUDE.md` | Claude Code 自动加载的项目/用户级指令 |
| Context Window | 模型一次请求可接收的 token 空间 |
| Token Budget | Harness 为输入、输出和历史预留的 token 配额 |
| Compact | 上下文过大时，把旧历史压缩成摘要 |
| Microcompact | 不调用模型，先清理旧的工具结果 |
| Full Compact | 调用模型总结旧对话，再保留最近消息 |
| Prompt Cache | 复用稳定的系统提示、工具定义和历史前缀，降低延迟/成本 |
| Thinking / Reasoning | 模型的内部推理输出或推理预算，不同厂商参数不同 |

## 3. 工具与权限

| 名词 | 含义 |
|---|---|
| Tool | 暴露给模型的函数/能力 |
| Tool Call | 模型请求执行某个工具及参数 |
| Tool Result | 工具执行结果，回填到下一轮模型上下文 |
| Tool Registry | 当前可见工具的注册与过滤 |
| Read-only Tool | 不改变文件/外部状态的工具 |
| Destructive Tool | 删除、覆盖、发送等难以恢复的工具 |
| Permission Mode | 决定哪些工具自动允许、询问或拒绝 |
| Sandbox | 限制进程可访问路径、网络和系统资源的执行边界 |
| Approval | 在执行敏感命令或补丁前询问用户 |
| Hook | 在工具前/后执行确定性脚本或回调 |

## 4. 循环与编排

| 名词 | 含义 |
|---|---|
| Agent Loop | 模型 → 工具 → 结果 → 模型，直到模型不再调用工具 |
| `run_turn` | Codex 的一次 turn 主循环 |
| `queryLoop` | Claude Code 的 query 状态机/循环 |
| StateGraph | LangGraph 的显式节点、边、状态图 |
| Node | Graph 中执行一步工作的函数 |
| Edge | 节点之间的固定流转 |
| Conditional Edge | 运行时按状态选择下一节点 |
| Subgraph | 可嵌入父图的子流程 |
| Handoff | 把当前会话交给另一个 Agent |
| Subagent | 由主 Agent 派出、拥有独立上下文的子 Agent |
| Mailbox | Agent 之间异步传递消息的队列 |
| Pending Messages | 子 Agent 运行期间暂存、等待回合边界消费的消息 |
| Checkpointer | 保存图状态快照的组件 |
| Interrupt | 暂停图，等待人工输入 |
| Resume | 用外部输入继续被暂停的图 |
| Replay | 从历史 checkpoint 重放后续步骤 |
| Fork | 从历史 checkpoint 创建新分支 |

## 5. 事件与可观测性

| 名词 | 含义 |
|---|---|
| Event | Harness 产生的结构化状态变化 |
| `EventMsg` | Codex 的模型/工具/patch/token 事件协议 |
| Event Stream | 按时间顺序发送给 UI 的事件流 |
| Transcript | 一条线程的完整消息记录 |
| Rollout | Codex 保存的可回放执行记录 |
| Trace | 跨模型、工具、Agent 的调用链 |
| Token Count | 当前上下文/本轮调用的 token 使用量 |

## 6. 多 Agent 通信

### Codex

Codex 的多 Agent 工具面包含：

- `spawn_agent`：启动子 Agent；
- `send_input` / `send_message`：向子 Agent 邮箱发送消息；
- `wait_agent`：等待子 Agent 活动/完成；
- `resume_agent`：恢复子 Agent；
- `interrupt_agent`：打断子 Agent 当前任务；
- `close_agent`：关闭子 Agent；
- `list_agents`：列出 Agent 状态。

通信不是直接共享 Python 变量，而是：

1. 子 Agent 有独立 `thread_id` 和上下文；
2. 消息进入 mailbox；
3. 子 Agent 在回合/工具边界读取；
4. 终止结果通过活动/通知回传父 Agent；
5. 资源清理需要显式 close，避免后台进程泄漏。

源码入口：

- `codex-rs/core/src/agent/control/mailbox.rs`
- `codex-rs/core/src/agent/control/spawn.rs`
- `codex-rs/core/src/agent/control/interrupt.rs`
- `codex-rs/core/src/agent/control/completion.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/`

### Claude Code

Claude Code 的多 Agent 机制更偏任务/团队：

- `Task` / `AgentTool`：把子 Agent 包装成工具；
- `SendMessage`：向正在运行的 Agent 发送后续指令；
- `TaskOutput`：读取子 Agent 的输出；
- `TaskCreate/Get/List/Update`：维护任务状态；
- `LocalAgentTask`：后台本地 Agent 的生命周期；
- `forkSubagent`：复用父上下文和 prompt cache 的分支 Agent。

其核心通信语义：

1. 子 Agent 有独立 `agentId` 和上下文；
2. 父 Agent 通过 `pendingMessages` 投递消息；
3. 子 Agent 在 tool-round boundary 消费；
4. 任务状态和输出通过 AppState/transcript 暴露；
5. 结束后要清理任务、后台 shell、缓存和子 Agent 资源。

源码入口：

- `src/tools/AgentTool/`
- `src/tools/SendMessageTool/`
- `src/tools/TaskOutputTool/`
- `src/tasks/LocalAgentTask/`
- `src/tools/AgentTool/forkSubagent.ts`

### Hermes

Hermes 把“通用任务 + 长期学习”放在第一位：

- `MEMORY.md`：Agent 对环境的长期事实；
- `USER.md`：用户画像、偏好和沟通习惯；
- `SKILL.md`：可复用的程序性经验；
- `skills/.usage.json`：技能使用和生命周期 sidecar；
- `background review`：turn 结束后独立模型复盘；
- `curator`：按时间把旧技能标 stale / archive；
- `session_search`：SQLite FTS5 历史会话检索；
- `toolset`：按场景决定模型能看到哪些工具。

核心记忆边界：声明性记忆写 `MEMORY.md` / `USER.md`，程序性记忆写 `SKILL.md`；
两者不要混在一起。Hermes 的 curator 只归档不删除，且默认只管理 `created_by: agent` 的技能。

Hermes 主循环通常不是 LangGraph：它是过程式 turn loop，配合 SessionDB、文件 checkpoint、
callback/stream 事件和后台 review。本项目用 LangGraph 表达只是为了教学可视化。

## 7. MCP

| 名词 | 含义 |
|---|---|
| MCP | Model Context Protocol，模型应用和外部工具/资源之间的标准协议 |
| MCP Server | 暴露 tools/resources/prompts 的服务 |
| MCP Client | Harness 中负责发现和调用 MCP Server 的组件 |
| Discovery | 连接后列出 server 提供的工具 |
| Namespaced Tool | 避免多个 MCP server 同名工具冲突的前缀 |
| Transport | stdio、SSE、Streamable HTTP、WebSocket 等连接方式 |

Codex 和 Claude Code 都把 MCP 当作动态工具来源，而不是写死在主 Agent 中。
实际项目里还应做工具白名单、超时、鉴权、输出截断和错误隔离。

## 8. 本项目的代码地图

| 想学什么 | 先看哪里 |
|---|---|
| Codex 的核心 turn/事件/工具对照 | `docs/mini-codex-architecture.md` |
| Codex-style 可运行 Harness | `mini_codex/` |
| Claude Code 风格 queryLoop | `claude_harness/harness.py` |
| Claude 风格 CLAUDE.md 与压缩 | `claude_harness/context.py` |
| Claude 工具+权限 | `claude_harness/tools.py`、`claude_harness/permissions.py` |
| Claude 多 Agent Task | `claude_harness/multi_agent.py` |
| Claude 简略 MCP | `claude_harness/mcp_server.py`、`claude_harness/mcp_client.py` |
| 两套 Harness 共用 mailbox 运行时 | `agent_runtime/runtime.py` |
| 两套 Harness 的阶段可视化 | `MiniCodexHarness.ipynb`、`ClaudeHarness.ipynb` |
| Hermes 的记忆/技能/复盘 | `hermes_harness/`、`docs/hermes-harness-architecture.md` |
| Hermes 的阶段可视化 | `HermesHarness.ipynb`、`docs/system-maps/` |

## 9. 学习顺序

1. 看本表，理解 Agent 的九层。
2. 看 `docs/mini-codex-architecture.md`，理解 `run_turn` 和 `EventMsg`。
3. 看 `docs/claude-harness-architecture.md`，理解 `queryLoop`、`CLAUDE.md` 和权限。
4. 读 `mini_codex/harness.py` 与 `claude_harness/harness.py`。
5. 读工具和权限层，再看多 Agent/MCP。
6. 最后跑三个 Harness Notebook，对照控制台事件、timeline 和源码流程图。

