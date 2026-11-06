# 四套 Mini Harness 的源码溯源与复刻边界

这份文档只记录**实际参考过的源码**、本项目对应的代码位置、已经实现的核心不变量，以及明确简化的部分。它不是产品对比，也不是“架构相似”说明。

## 0. 源码版本

| Harness | 本地源码 | 上游 | Commit |
|---|---|---|---|
| Codex | `D:\workspace\rust\codex` | `https://github.com/openai/codex.git` | `89461ea6833832b0551ce24ee32205824d5c108d` |
| Claude Code | `D:\workspace\agent\claudecode\claude-code-sourcemap\restored-src` | npm `@anthropic-ai/claude-code` `2.1.88` 的 sourcemap 还原材料 | `a8a678cb6244e6770e1e421767ff0987a1d95549` |
| Hermes | `C:\Users\56870\AppData\Local\hermes\hermes-agent` | `https://github.com/NousResearch/hermes-agent.git` | `f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab` |
| DeepSeek Harness | `D:\workspace\agent\deepseek-harness-upstream` | `https://github.com/deepseek-ai/deepseek-harness.git` | `b0a7d2ce3b4c19d7452e364b2d7acbfa87e707ed` |

## 1. Codex mini

### 1.1 已对照的源码

| 上游源码/符号 | 用途 | 本项目对应 |
|---|---|---|
| `codex-rs/core/src/session/turn.rs::run_turn`（约第 173 行） | sampling → function call → tool output → 再 sampling | `mini_codex/harness.py::MiniCodexHarness.run`、`agent_runtime/tool_loop.py` |
| `codex-rs/core/src/session/turn_context.rs::TurnContext`（约第 323 行） | 汇总本轮模型、环境、策略和工具状态 | `mini_codex/config.py::HarnessConfig` + `mini_codex/context.py::ContextManager` |
| `codex-rs/core/src/agents_md.rs` | 发现 `AGENTS.md` / `AGENTS.override.md` | `mini_codex/context.py::discover_agents_md` |
| `codex-rs/core/src/compact.rs` | 上下文压缩、pre/post compact hook | `mini_codex/context.py::ContextManager.compact` |
| `codex-rs/protocol/src/protocol.rs::EventMsg`（约第 1469 行） | TurnStarted、AgentMessage、ExecCommand、PatchApply、PlanUpdate、TokenCount、ContextCompacted | `mini_codex/events.py::EventBus` |
| `codex-rs/core/src/tools/spec_plan.rs::build_tool_router` / `build_core_tool_registry`（约第 121/293 行） | 组装当前可用工具 | `mini_codex/tools.py::build_tools` |
| `codex-rs/core/src/tools/handlers/plan.rs`、`protocol/src/plan_tool.rs` | 计划工具和计划数据 | `mini_codex/state.py::Plan` / `PlanState`、`tools.py::update_plan` |
| `codex-rs/core/src/tools/handlers/apply_patch_spec.rs`、`shell_spec.rs` | patch 和 shell 工具 | `write_file` / `replace_in_file` / `run_command`（简化映射） |

### 1.2 已实现的关键不变量

- `run_started → workspace_ready → context_built → plan_created → agent loop → verify → run_completed`
- 模型没有 tool_calls 时结束本轮；有 tool_calls 时执行工具，把观察写回消息，再采样。
- `AGENTS.md` 进入上下文；事件流、计划和变更均有落盘。
- 工具错误转成 `ToolMessage`，而不是直接杀死整个流程。
- 重复工具调用、最大步数、模型失败、插件/MCP 失败均有显式终止或降级事件。
- 验证命令的真实 returncode 决定最终成功状态。

### 1.3 明确简化

- 没有 Codex 的 OS sandbox、app-server、Responses API、完整 approval UI。
- 工具只覆盖开发闭环的读写、搜索、命令、Git 和计划。
- 上下文压缩是确定性裁剪，不调用专门摘要模型。

## 2. Claude Code mini

### 2.1 已对照的源码

| 上游源码/符号 | 用途 | 本项目对应 |
|---|---|---|
| `restored-src/src/query.ts::queryLoop`（约第 241 行） | model → tool_use → tool_result → model | `claude_harness/harness.py::ClaudeHarness.run` 的 LangGraph 节点 |
| `restored-src/src/utils/claudemd.ts` | CLAUDE.md 发现与注入 | `claude_harness/context.py::discover_claude_md` |
| `restored-src/src/services/compact/` | microcompact / full compact | `ClaudeContextManager.maybe_compact` |
| `restored-src/src/services/SessionMemory/` | 跨 turn session memory | `ClaudeContextManager.save_session_memory` |
| `restored-src/src/tools/` | Read/Edit/Bash/TodoWrite 等工具形状 | `claude_harness/tools.py` |
| Claude Code 的 Tool permission / hooks 设计 | 工具前权限和 hook 检查 | `permissions.py`、`hooks.py`、`harness.py::tools_node` |
| Claude Code 的 Task / TaskOutput / SendMessage 思路 | 隔离子 Agent 与 mailbox | `agent_runtime/runtime.py`、`claude_harness/multi_agent.py` |

### 2.2 已实现的关键不变量

- `prepare → plan(TodoWrite) → model ↔ tools → compact → finalize`
- `default/plan/acceptEdits/bypassPermissions/dontAsk` 权限模式。
- 工具调用前执行 permission 和 pre-hook；拒绝会变成 `ToolMessage`。
- 旧工具结果先 microcompact，再按预算 full compact。
- session memory、Todo、MCP 工具、子 Agent、事件流均已接入。
- 验证被拒绝、工具异常、模型异常、最大轮数均有明确事件和终止原因。

### 2.3 明确简化

- 权限不是 OS 级 sandbox。
- full compact 使用确定性摘要，不调用专用 9 段摘要模型。
- Task/SendMessage 是单进程线程 mailbox，不是 Claude Code 的完整远程 Agent 运行时。
- Claude 源码来自非官方 sourcemap 还原材料，不能等同于 Anthropic 内部仓库。

## 3. Hermes mini

### 3.1 已对照的源码

| 上游源码/符号 | 用途 | 本项目对应 |
|---|---|---|
| `run_agent.py::AIAgent`（约第 214 行） | 组合会话、模型、工具和运行时 | `hermes_harness/harness.py::HermesHarness` |
| `agent/conversation_loop.py::_run_conversation_turn`（约第 1640 行） | 过程式 turn loop | `hermes_harness/harness.py` 的 LangGraph model/tools 节点 |
| `agent/background_review.py` | turn 后独立复盘 | `hermes_harness/review.py::BackgroundReview` |
| `agent/memory_context.py` | `<memory-context>` 围栏，声明不是新用户输入 | `MemoryStore.context_block` |
| `tools/memory_tool_store.py::MemoryStore`（默认 2200/1375 字符） | MEMORY/USER 有界存储 | `hermes_harness/memory.py::MemoryStore` |
| `tools/skills_tool.py`、`tools/skill_manager_tool.py` | Skills 索引、查看、创建、patch、附件 | `hermes_harness/skills.py::SkillStore`、`tools.py` |
| `agent/curator.py` | stale/archive 生命周期 | `SkillStore.curate` |
| `hermes_state_fts.py` | SQLite FTS5 与中文 bigram | `hermes_harness/sessions.py::SessionStore` |
| `toolsets.py` | 工具面按场景裁剪 | `hermes_harness/toolsets.py` |

### 3.2 已实现的关键不变量

- `SOUL.md + MEMORY.md + USER.md + Skills Index + Environment + Toolset` 在 prepare 注入。
- 记忆有预算、幂等 add、唯一匹配 patch/remove、原子替换写入。
- Skills 采用渐进披露：索引只给摘要，`skill_view` 才读正文。
- Curator 只处理 agent 创建的技能，stale/archive，不删除；pinned 豁免。
- 后台 review 用隔离上下文，只允许 memory/skills 白名单工具，失败不覆盖主答案。
- session_search 使用 FTS5；缺少 FTS5 时回退到 LIKE。
- 插件、MCP、多 Agent、approval、验证和 review 失败都有降级事件。

### 3.3 明确简化

- 没有 Telegram/Discord/Slack gateway、桌面端、浏览器、语音、cron、远程 terminal backend。
- 没有完整外部 memory provider、跨进程文件锁和大规模 skill hub。
- curator 的 LLM 合并/去重未实现，只保留确定性生命周期。

## 4. DeepSeek Harness mini

### 4.1 已对照的源码

| 上游源码/符号 | 用途 | 本项目对应 |
|---|---|---|
| `packages/core/session/src/types.ts::SessionEventMap`（约第 273 行起） | turn/step、user/assistant、tool call/result、attempt | `deepseek_harness/session.py::DeepSeekSession` |
| `packages/core/session/src/index.ts::Session.append` / `deriveMessages` | 事件唯一真源、消息派生 | `DeepSeekSession.append` / `derive_messages` |
| `packages/core/agent-loop/src/agent.ts::ReactLoopAgent.turn`（约第 257 行） | turn 生命周期和多个 step | `deepseek_harness/harness.py::DeepSeekHarness.run` |
| `packages/core/agent-loop/src/agent.ts::ReactLoopAgent.step`（约第 343 行） | 请求、模型输出、工具批次 | 同上 |
| `packages/core/agent-loop/src/tool-calls.ts::executeToolCalls`（约第 60 行） | tool/call → result、工具调度 | `deepseek_harness/tool_pipeline.py` |
| `packages/core/agent-loop/src/tool-calls.ts::appendToolCall` / `appendToolResult`（约第 263/269 行） | 持久化调用与结果 | `DeepSeekToolPipeline.execute` |
| `packages/llm/llm-retry/src/index.ts::backoff` / `recover` | llm/retry、llm/retry-started、持久重试 | `DeepSeekHarness._invoke_model` |
| `packages/compaction/compaction-basic/src/region.ts`（约第 191/217/457 行） | compaction/start → summary → end | `DeepSeekHarness._maybe_compact` |
| `packages/compaction/compaction-tool-result-pruner/src/index.ts`（约第 162 行） | compaction/prune | 同上 |
| `packages/session/session-checkpoint-policy/src/index.ts` | 模型请求前、工具正文前、step 边界 flush | `DeepSeekSession.flush`、`harness.py` 的 checkpoint 调用 |
| `docs/subsystems/session.zh.md`、`docs/tool-execution-pipeline.zh.md`、`docs/agent-lifecycle.zh.md` | 源码行为说明 | 事件与流水线设计 |

### 4.2 已实现的关键不变量

- `session.v1.jsonl` 是 append-only 事件日志，包含 `seq/time/type/data/surfaceOp/sourceEventSeqs`。
- 模型消息从 session 事件派生，不另外维护一份独立聊天历史。
- 一次 turn 包含多个 step；每个 step 是一次模型请求和其工具调用。
- 事件顺序：`turn/start → step/start → user/message → request/header → session/flush → assistant/message → tool/call → approval/* → tool/result → step/end → turn/end`。
- 工具调用先记录、再审批、再执行；工具异常也变成 `tool/result`，不会穿透循环。
- 模型失败在同一 step 内重试，先记录 `llm/retry`，再等待，再记录 `llm/retry-started`。
- 压缩使用 `compaction/start → compaction/prune → compaction/summary → compaction/end`，并用 surface replacement 遮蔽旧事件。
- 每个模型请求前、工具正文前、step 边界执行 `session/flush` 检查点。
- 支持插件/MCP/多 Agent/approval、验证、session memory 和故障演练。

### 4.3 明确简化

- 没有实现 Cordis 插件树、profile/bundle patch 体系、Cordis service seam。
- 没有实现完整 projection、并行工具 rolling pool、AbortSignal、JSONL persistence generation 和 session repair。
- 子 Agent 没有完全复刻 `ctx.agents` / subagent seam，只复用共享 runtime 的 mini 多 Agent。
- compaction 是简化确定性摘要，没有 upstream 的完整 surface stability 断言和模型摘要策略。

## 5. 机制保障对照

| 机制 | Codex | Claude | Hermes | DeepSeek |
|---|---|---|---|---|
| 显式 turn/step 生命周期 | 阶段 + loop | LangGraph 节点 | LangGraph 节点 | `turn/*`、`step/*` session 事件 |
| 事件日志 | `events.jsonl` | `events.jsonl` | `events.jsonl` | `session.v1.jsonl` + `events.jsonl` |
| 模型工具循环 | 有 | 有 | 有 | 有 |
| 工具错误回填 | 有 | 有 | 有 | 有，且 `tool/result.isError` |
| 权限/审批边界 | workspace + approval | permission modes + hooks | approval + toolset | approval/* + tool/call 前检查 |
| 插件 | manifest | manifest | manifest | manifest |
| MCP | 有 | 有 | 有 | 有 |
| 多 Agent | 有 | 有 | 有 | 有（共享 mini runtime） |
| 上下文压缩 | 确定性裁剪 | micro/full compact | 预算裁剪 | compaction/* 事件 |
| 模型重试 | 无/简化为失败终止 | 失败进入 finalize | 失败进入 finalize | llm/retry + llm/retry-started |
| 持久 checkpoint | run 目录 | LangGraph InMemorySaver | run 目录 | session flush |
| 验证 | verify_command | verify_command | verify_command | verify_command |
| 长期学习 | 无 | session memory | memory/skills/review | session memory |
| 失败降级 | 插件/MCP/模型/工具 | 权限/hook/压缩/模型 | review/记忆/技能/MCP | retry/approval/tool/compaction |

## 6. Sandbox 源码依据

- Codex：`codex-rs/protocol/src/protocol.rs::SandboxPolicy`、`codex-rs/core/src/sandboxing/`、`linux-sandbox`、`windows-sandbox-rs`。
- Claude Code：`restored-src/src/utils/sandbox/sandbox-adapter.ts::SandboxManager`、`restored-src/src/entrypoints/sandboxTypes.ts`。
- Hermes：`tools/environments/`、`toolsets.py`。
- DeepSeek：`packages/sandbox/sandbox/src/index.ts::SandboxPolicy`、`sandbox-local`、`sandbox-windows-acl`、`packages/core/session/src/types.ts::sandbox/mode`。

对应实现：`agent_runtime/sandbox_sim.py`。该实现只产生
`sandbox/requested → backend_selected → policy_applied → mounts_prepared → started → stopped`
等生命周期日志，不创建真实容器或进程。详细说明见 `docs/sandbox-simulation.md`。

## 7. 教学扩展（不是上游事件）

以下事件/机制是本教学项目为了可视化、故障演练和安全兜底新增的，不应误认为上游原生事件：

- `run_started`、`workspace_ready`、`context_built`：本地 UI 的阶段入口；
- `fault_injected`：显式故障演练，只在用户选择故障模式时触发；
- `fallback_applied`、`failure_summary`、`limit_reached`：统一的可解释降级/终止事件；
- `plugin_loaded`、`mcp_tools_loaded`、`multi_agent_tools_loaded`：本地共享 runtime 的可视线；
- DeepSeek 的 `fault_mode`、`session/flush` 可视化镜像和 `events.jsonl` 镜像：教学层，上游实际实现分别对应持久化 flush、session event 和 persistence backend。

## 8. 使用原则

- 需要源码级行为时，先看上游 path 和 symbol，再看本项目对应实现，不要从 UI 文案反推。
- 需要新增机制时，先确认它属于上游的哪个 seam；没有源码依据的机制必须标成教学扩展。
- 运行 `uv run pytest -q`；DeepSeek 还要检查 `session.v1.jsonl` 和 `events.jsonl` 两种日志。
