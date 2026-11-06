# DeepSeek Harness 小白 Demo

这是一个**离线、可重复、不需要 API Key** 的 DeepSeek Harness 演示。

```powershell
uv run python -m deepseek_harness.demo
```

它使用假模型，但运行的是项目真实的：

- `DeepSeekHarness`
- `DeepSeekSession`
- `DeepSeekToolPipeline`
- approval policy
- `session/flush`

## 怎么读输出

每一行事件都会打印：

```text
what   : 这一步做什么
why    : 为什么需要它
input  : 输入
output : 输出/观察
design : 为什么这样设计
next   : 下一步
source : 对应的上游源码文件/符号
```

## 正常场景

```text
turn/start
→ step/start
→ user/message
→ request/header
→ session/flush
→ assistant/message
→ tool/call
→ approval/policy
→ tool/result
→ step/end
→ turn/end
```

重点看：

1. `user/message` 和 `assistant/message` 是从 session event 派生的，不是额外的聊天数组；
2. `tool/call` 在执行前写入；
3. `tool/result` 是模型下一次请求看到的唯一工具结果；
4. 每个 step 边界都有 `session/flush`；
5. `turn/end` 记录结束原因，而不是静默停止。

## 故障演练

```powershell
uv run python -m deepseek_harness.demo --fault tool_error
uv run python -m deepseek_harness.demo --fault plugin_error
uv run python -m deepseek_harness.demo --fault model_error
```

可以观察：

- `fault_injected`
- `fallback_applied`
- `assistant/attempt`（模型失败）
- `turn/end` 的 error reason

## 真实模型的区别

Demo 只把模型替换成 `DemoModel`，其他事件、工具流水线、session、
审批和落盘逻辑与真实运行时相同。真实模型运行：

```powershell
uv run python -m deepseek_harness --workspace examples/deepseek_harness_demo `
  --task "修复 calculator.py 中 add 的 bug，运行测试并总结" `
  --verify-command "python -m pytest -q"
```
