# 多 Agent 通信：Codex 与 Claude Code

## 1. 先理解“为什么需要通信”

多 Agent 不是简单地把多个模型同时启动。真正的难点是：

1. 子 Agent 应该继承多少上下文？
2. 父 Agent 怎样知道子 Agent 正在运行/完成/失败？
3. 子 Agent 运行中收到新指令，如何不破坏当前模型调用？
4. 结果怎样返回，怎样避免重复和竞态？
5. 子 Agent 退出后，后台进程、线程和文件句柄怎样清理？

## 2. Codex 的通信模型

Codex 的核心概念：

- `spawn`：创建子 Agent，给它 thread_id 和独立上下文；
- `send_input` / `send_message`：把消息放进子 Agent mailbox；
- `followup_task`：投递消息并触发新的 turn；
- `wait_agent`：等待子 Agent 活动、mailbox 或超时；
- `resume_agent`：恢复已暂停/结束的子 Agent；
- `interrupt_agent`：中止当前任务；
- `close_agent`：关闭 Agent 并释放资源；
- `list_agents`：列出 Agent 状态。

关键源码：

- `codex-rs/core/src/agent/control/mailbox.rs`
  - `Mailboxes::enqueue()` 将消息放入每个 Agent 的 mailbox；
  - `Mailboxes::take()` 在回合边界取走消息；
  - `watch()` 让等待方收到 mailbox 活动通知。
- `codex-rs/core/src/tools/handlers/multi_agents_v2/send_message.rs`
  - `MessageDeliveryMode::QueueOnly`：只排队，不触发新 turn。
- `.../followup_task.rs`
  - `MessageDeliveryMode::TriggerTurn`：排队并触发新 turn。
- `.../wait.rs`
  - 等待 mailbox、steered input 或 timeout。
- `codex-rs/core/src/agent/control/spawn.rs`
  - fresh child history / fork history；
  - 继承动态工具和 Agent 配置。

## 3. Claude Code 的通信模型

Claude Code 的对应概念：

- `Task` / `AgentTool`：创建子 Agent，拥有独立 `agentId` 和上下文；
- `LocalAgentTask`：后台本地 Agent 的状态和生命周期；
- `SendMessage`：向子 Agent 投递后续消息；
- `TaskOutput`：读取子 Agent 输出；
- `TaskCreate/Get/List/Update`：任务清单状态；
- `forkSubagent`：从父上下文 fork，最大化 prompt cache 复用；
- `pendingMessages`：子 Agent 运行中暂存消息；
- tool-round boundary：在下一轮工具执行边界消费消息。

关键源码/研究文档：

- `claude-code-sourcemap/restored-src/src/tools/AgentTool/`
- `.../src/tools/SendMessageTool/`
- `.../src/tools/TaskOutputTool/`
- `.../src/tasks/LocalAgentTask/LocalAgentTask.tsx`
- `.../src/tools/AgentTool/forkSubagent.ts`
- `claudecode/Claude-Code-Source-Study/docs/12-Agent-系统.md`
- `.../docs/14-任务系统.md`

## 4. 两种模式的本质差异

| 维度 | Codex | Claude Code |
|---|---|---|
| 子 Agent 标识 | thread_id / agent_path | agentId / task id |
| 消息入口 | mailbox + send_input | pendingMessages + SendMessage |
| 结果读取 | wait_agent / event | TaskOutput / transcript |
| 生命周期 | spawn/resume/interrupt/close | Task lifecycle + background task |
| 上下文继承 | fresh 或 fork | fresh 或 fork subagent |
| 并发 | agent control / budget / mailbox | local/remote tasks + task registry |
| 典型通信 | queue + wait | queue + TaskOutput |

共同点：

- 都避免在模型生成中途直接改消息；
- 都在下一轮采样/工具边界消费消息；
- 都需要状态、结果、错误和清理；
- 都不会让子 Agent 共享父 Agent 的全部可变状态。

## 5. 本项目的共享实现

`agent_runtime/runtime.py` 实现了一个最小教学版：

- `spawn(name, prompt, system_prompt)` → `agent_id`；
- `send_input(agent_id, message)` → 放入 inbox；
- `wait(agent_id, timeout)` → 等待线程并返回 snapshot；
- `list_agents()`；
- `close(agent_id)`。

子 Agent 的模型循环：

```text
启动
  → 建立独立 System/Human messages
  → 每轮模型采样前 drain inbox
  → 模型调用
  → 有 tool_calls 就执行并追加 ToolMessage
  → 没有 tool_calls 就写 result 并结束
```

Claude 包装：

- `Task` → `spawn`
- `SendMessage` → `send_input`
- `TaskOutput` → `wait`
- `TaskList` → `list_agents`
- `CloseAgent` → `close`

Codex 包装：

- `spawn_agent` → `spawn`
- `send_input` → `send_input`
- `wait_agent` → `wait`
- `list_agents` → `list_agents`
- `close_agent` → `close`

## 6. 推荐阅读顺序

1. `docs/agent-systems-glossary.md`
2. 本文
3. `agent_runtime/runtime.py`
4. `claude_harness/multi_agent.py`
5. `mini_codex/multi_agent.py`
6. 对照 `Claude-Code-Source-Study/docs/12-Agent-系统.md` 和 `14-任务系统.md`

## 7. 本项目没有做的部分

- 跨进程/跨机器的持久 mailbox；
- 远程 Agent、云端任务；
- OS 级 sandbox；
- 完整的 fork prompt cache；
- 复杂的 Agent 预算、父子资源配额和审计；
- 真正的任务 DAG 调度器。
- 对已完成子 Agent 的完整 resume/replay；当前 `send_input` 只负责投递消息，
  子 Agent 运行中会在下一轮消费，已完成时只保留在 mailbox 快照中。

这些正是从“教学项目”走向“生产 Harness”需要补的部分。
