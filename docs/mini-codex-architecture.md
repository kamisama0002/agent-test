# Mini Codex：用 LangChain 复刻 Codex Harness

## 1. 先回答：一个 Agent 分成哪几块？

从 Harness 视角看，一个编码 Agent 至少包含：

| 层 | 作用 | Codex 对应 | Mini Codex 对应 |
|---|---|---|---|
| Model | 负责推理和选择工具 | 可配置模型 | `build_chat_model()` |
| Instructions | 角色、边界、开发规范 | base/developer instructions | `context.py` 的 `BASE_SYSTEM_PROMPT` |
| Context | 仓库、环境、AGENTS.md、历史、工具结果 | `TurnContext` / `StepContext` / world state | `ContextManager` |
| Tools | 读写文件、执行命令、更新计划 | `exec_command`、`apply_patch` 等 | `mini_codex/tools.py` |
| Loop | 采样 → 工具 → 观察 → 再采样 | `run_turn` | `MiniCodexHarness.run` |
| Policy | 沙箱、审批、命令边界 | sandbox + approval | workspace 路径限制 + 命令白名单/黑名单 |
| Events | 让 UI 看见每一步 | `EventMsg` 流 | `EventBus` → `events.jsonl` / `timeline.md` |
| State | 计划、变更、命令、可恢复状态 | history / rollout / checkpoint | `PlanState` / `ChangeTracker` / run 目录 |
| Stop | 什么时候结束 | assistant message 或 abort/limit | 无 tool_calls / max_steps / repeated call |

## 2. Codex 开源 Harness 实际怎么实现？

OpenAI 官方说明 Codex 的开源 Harness 负责：

> conversation state、stream execution、tools、sandbox/approval policies、跨 turn 继续工作。

参考：[Codex as a platform: build on the open agent harness](https://developers.openai.com/blog/codex-as-a-platform)

开源仓库：https://github.com/openai/codex

### 2.1 核心循环

看 `codex-rs/core/src/session/turn.rs` 的 `run_turn` 注释，循环非常清晰：

1. 向模型发起一次 sampling request；
2. 模型返回 function calls 或 assistant message；
3. 如果是 function call，执行工具，把 output 放回 conversation history，再次采样；
4. 如果只有 assistant message，记录后结束本 turn。

Mini Codex 的 `MiniCodexHarness.run()` 就是这个循环的 Python 版。

### 2.2 上下文

Codex 的上下文不是单一字符串，而是多段组合：

- base instructions；
- developer instructions；
- 项目 `AGENTS.md` / `AGENTS.override.md`；
- environment / world state；
- 历史消息、工具输出；
- token budget 提示、压缩摘要。

源码参考：

- `codex-rs/core/src/agents_md.rs`
- `codex-rs/core/src/context/`
- `codex-rs/core/src/session/turn_context.rs`
- `codex-rs/core/src/compact.rs`

Mini Codex 只保留开发所需的最小集合：

- `BASE_SYSTEM_PROMPT`
- `AGENTS.md`
- workspace/OS/Python/Git/top-level 文件
- 对话历史
- 工具结果
- `ContextManager.compact()` 的简单历史裁剪

### 2.3 工具面

Codex 开源 core 中可见的 native tool handlers 包括：

- `exec_command`
- `write_stdin`
- `apply_patch`
- `update_plan`
- `view_image`
- `request_permissions`
- `request_user_input`
- `tool_search`
- MCP resource tools
- multi-agent tools

不同配置/模型下暴露的工具会变化。源码入口：

- `codex-rs/core/src/tools/handlers/`
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/protocol/src/protocol.rs`

Mini Codex 只做开发场景，因此映射如下：

| Codex 工具/能力 | Mini Codex 工具 | 说明 |
|---|---|---|
| `exec_command` / `write_stdin` | `run_command` | 简化为一次性执行，不支持交互式 stdin |
| `apply_patch` | `write_file` / `replace_in_file` | 简化为整体写入和精确文本替换 |
| `update_plan` | `update_plan` | 保留同名计划工具 |
| 文件读取/搜索 | `read_file` / `list_files` / `search_text` | 方便模型安全地检查仓库 |
| Git 观察 | `git_status` / `git_diff` | 只读 |
| `view_image` | 未实现 | 非开发主流程，暂不引入 |
| MCP/多 Agent/插件 | 未实现 | 不混入简单版 |

### 2.4 事件与可视化

Codex 通过 `EventMsg` 把过程流给 app-server / UI，事件包括：

- `TurnStarted` / `TurnComplete`
- `AgentMessage` / `AgentReasoning`
- `ExecCommandBegin` / `ExecCommandOutputDelta` / `ExecCommandEnd`
- `PatchApplyBegin` / `PatchApplyUpdated` / `PatchApplyEnd`
- `PlanUpdate`
- `TokenCount`
- `ContextCompacted`
- `Error` / `Warning`

源码：`codex-rs/protocol/src/protocol.rs` 的 `enum EventMsg`。

Mini Codex 的 `EventBus` 保留了同样的结构：

- 控制台实时阶段和工具调用；
- `events.jsonl` 给机器回放；
- `timeline.md` 给人看阶段耗时；
- `changes.diff` 保存文件变更；
- `summary.md` 保存任务、计划、最终回答和命令记录。

## 3. Mini Codex 的阶段

| 阶段 | 做什么 | 可视产物 |
|---|---|---|
| `bootstrap` | 校验 workspace，创建 run 目录 | `stage_started/completed` |
| `context` | 加载 AGENTS.md、环境、token budget | `context_built` |
| `plan` | 使用结构化输出生成 3–6 步计划 | `plan_created` |
| `agent` | 模型采样 → 工具 → 观察 → 再采样 | `model_request`、`tool_started/finished`、`token_usage` |
| `verify` | 执行你指定的测试/lint 命令 | `verification_completed` |
| `finalize` | 汇总计划、diff、命令、最终回答 | `summary.md`、`timeline.md` |

## 4. 运行方式

```powershell
# 在示例仓库上运行（会修改示例仓库，建议先复制）
Copy-Item examples/mini_codex_demo $env:TEMP/mini_codex_demo -Recurse

uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "修复 calculator.py 中 add 函数的 bug，让 pytest 通过" `
  --verify-command "python -m pytest -q"
```

也可以运行当前项目：

```powershell
uv run python -m mini_codex `
  --workspace . `
  --task "给 tests 补一个测试并运行" `
  --verify-command "uv run pytest -q"
```

事件目录默认是：

```text
<workspace>/.mini_codex/runs/<timestamp>/
├── events.jsonl
├── timeline.md
├── summary.md
└── changes.diff
```

## 5. 这和完整 Codex 还差什么？

这是“简单版”，刻意没有做：

- OS 级 sandbox；
- 图形审批 UI / app-server 协议；
- Responses API / 真实 OpenAI 平台 tracing；
- MCP、插件、skills；
- 图片理解、语音；
- 多 Agent / subagent；
- 完整模型级 compaction 与服务端部署。

但它已经具备开发 Agent 的完整闭环：

**加载规范 → 构建上下文 → 规划 → 工具调用 → 修改文件 → 运行验证 → 输出 diff 和总结 → 留下可回放事件。**

## 6. 官方资料

- OpenAI Docs：Codex as a platform
  https://developers.openai.com/blog/codex-as-a-platform
- OpenAI Docs：Codex manual
  https://developers.openai.com/codex/codex-manual
- OpenAI Docs：Agent approvals & security
  https://developers.openai.com/codex/agent-approvals-security
- 开源仓库：https://github.com/openai/codex


## 7. Codex 源码地图与精确对应

| Codex 源码/符号 | Codex 中的作用 | Mini Codex 对应 |
|---|---|---|
| `codex-rs/core/src/session/turn.rs` → `run_turn` | 采样、执行工具、回填结果、判断 turn 完成 | `MiniCodexHarness.run()` 的 `agent` 阶段 |
| `codex-rs/core/src/session/turn_context.rs` → `TurnContext` | 保存本轮模型、环境、权限、设置 | `HarnessConfig` + `ContextManager` |
| `codex-rs/core/src/session/step_context.rs` → `StepContext` | 单次采样请求的上下文/工具快照 | 每次 `model.invoke(messages)` 前的消息压缩与工具绑定 |
| `codex-rs/core/src/agents_md.rs` | 从项目根到 CWD 发现并合并 `AGENTS.md` | `discover_agents_md()` |
| `codex-rs/core/src/compact.rs` | token 超限时生成压缩历史 | `ContextManager.compact()` |
| `codex-rs/protocol/src/protocol.rs` → `EventMsg` | 向 UI 流式发送模型/工具/patch/token 事件 | `EventBus.emit()` + `EventRecord` |
| `codex-rs/core/src/tools/spec_plan.rs` | 组装当前可用工具集 | `build_tools()` |
| `codex-rs/core/src/tools/handlers/plan.rs` → `update_plan` | 维护 TODO/checklist | `tools.py::update_plan` + `PlanState` |
| `codex-rs/core/src/tools/handlers/apply_patch_spec.rs` | 基于 patch 修改文件 | `write_file` + `replace_in_file`（简化） |
| `codex-rs/core/src/tools/handlers/shell_spec.rs` / `unified_exec/` | 执行 shell 命令、stdin、输出 | `run_command`（简化） |
| `codex-rs/protocol/src/plan_tool.rs` | 计划数据结构 | `state.py::Plan` / `PlanItem` |
| app-server / approval UI | 对外协议、审批请求、远程 UI | 未实现；用事件文件 + 本地命令策略替代 |

源码链接：

- 轮次主循环：https://github.com/openai/codex/blob/main/codex-rs/core/src/session/turn.rs
- Turn 上下文：https://github.com/openai/codex/blob/main/codex-rs/core/src/session/turn_context.rs
- 事件协议：https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs
- 工具 handler：https://github.com/openai/codex/tree/main/codex-rs/core/src/tools/handlers
- AGENTS.md 发现：https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs
- 上下文压缩：https://github.com/openai/codex/blob/main/codex-rs/core/src/compact.rs

## 8. 简略多 Agent 与 MCP

### 多 Agent

Mini Codex 的 `mini_codex/multi_agent.py` 提供：

- `spawn_agent(description, role)`：启动只读子 Agent，返回 `agent_id`；
- `send_input(agent_id, message)`：投递消息到 mailbox；
- `wait_agent(agent_id, timeout_sec)`：等待结果；
- `list_agents()`：查看状态；
- `close_agent(agent_id)`：请求停止。

底层共享 `agent_runtime/runtime.py`：

- 子 Agent 在独立线程和独立消息上下文中运行；
- 每轮模型采样前消费 inbox；
- 工具结果回填后继续采样；
- 父 Agent 通过 `wait_agent` 获取 snapshot。

对应 Codex 源码：

- `codex-rs/core/src/agent/control/mailbox.rs`
- `codex-rs/core/src/agent/control/spawn.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/`

运行：

```powershell
uv run python -m mini_codex --workspace ... --task ... --enable-multi-agent
```

### MCP

Mini Codex 的 `--enable-mcp` 会复用 `claude_harness/mcp_server.py` 的只读 MCP Server，
通过 `langchain-mcp-adapters` 加载 `repo_stats` 和 `find_todos`。

```powershell
uv run python -m mini_codex --workspace ... --task ... --enable-mcp
```

这部分是简化的 MCP：只演示 discovery、工具绑定和同步调用，不包含 MCP 鉴权、资源订阅、网络传输和多 server 命名空间。
