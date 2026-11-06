# DeepSeek Harness（源码对照版）

DeepSeek Harness 是第四套 Mini Harness，直接对照本地
`D:\workspace\agent\deepseek-harness-upstream`（commit
`b0a7d2ce3b4c19d7452e364b2d7acbfa87e707ed`）实现。

## 已对照的核心源码

- `packages/core/session/src/types.ts::SessionEventMap`
- `packages/core/session/src/index.ts::Session.append / deriveMessages`
- `packages/core/agent-loop/src/agent.ts::ReactLoopAgent.turn / step`
- `packages/core/agent-loop/src/tool-calls.ts::executeToolCalls`
- `packages/llm/llm-retry/src/index.ts::backoff / recover`
- `packages/compaction/compaction-basic/src/region.ts`
- `packages/compaction/compaction-tool-result-pruner/src/index.ts`
- `packages/session/session-checkpoint-policy/src/index.ts`
- `docs/subsystems/session.zh.md`
- `docs/tool-execution-pipeline.zh.md`
- `docs/agent-lifecycle.zh.md`

## 本项目实现

```text
turn/start
  → step/start
  → user/message
  → request/header
  → session/flush
  → agent/request
  → assistant/message
  → tool/call → approval/* → tool/result
  → step/end
  → turn/end
```

保留的关键不变量：

- `session.v1.jsonl` 是 append-only 事件日志，模型历史从事件派生；
- 一个 turn 包含多个 step，每个 step 是一次模型请求；
- `tool/call` 先记录，再审批/执行，`tool/result` 通过 callId 回填；
- 工具异常变成 `tool/result.isError`，不会穿透主循环；
- 模型失败使用 `llm/retry` + `llm/retry-started` 持久重试事件；
- 压缩使用 `compaction/start → prune → summary → end`；
- 模型请求前、工具正文前、step 边界写 `session/flush` 检查点；
- 保留插件、MCP、多 Agent、审批、验证和 session memory。

## 产物

```text
.deepseek/runs/<run_id>/
├── events.jsonl          # Mini Harness Studio 可视化镜像
├── session.v1.jsonl      # 权威 append-only session event log
├── changes.diff
├── summary.md
└── timeline.md
.deepseek/session-memory.md
```

## 简化边界

没有实现 Cordis 插件树、profile/bundle patch、完整 projection、
并行工具 rolling pool、AbortSignal、持久化 generation 和 session repair。
这些边界在 `docs/source-provenance.md` 中有逐项说明。
