# DeepSeek Harness（教学版）

DeepSeek Harness 是第四套 Mini Harness，复用共享工具基础设施，但单独展示：

- `reasoning_content` 与最终正文分栏记录；
- 模型调用有限重试 + 退避；
- 每步 checkpoint（模型后、工具后）；
- `DEEPSEEK.md` / `AGENTS.md` 分层上下文；
- session memory 跨轮注入；
- 插件、MCP、多 Agent、审批与验证；
- 工具失败回填、模型失败终止、重复调用断路；\n- Web 前端可选择故障演练：工具错误 / 规划失败 / 插件失败 / 模型失败。

## 运行

```powershell
uv run python -m deepseek_harness --workspace examples/deepseek_harness_demo --task "修复 calculator.py 中 add 的 bug，运行测试并总结" --verify-command "python -m pytest -q"
```

## 产物

```text
.deepseek/runs/<run_id>/
├── events.jsonl
├── checkpoint.json
├── changes.diff
├── summary.md
└── timeline.md
.deepseek/session-memory.md
```

## 与 Codex/Claude/Hermes 的差别

- Codex：开发 turn loop 与 AGENTS.md 最突出；
- Claude：权限模式、hooks、TodoWrite 最突出；
- Hermes：长期记忆、技能和后台复盘最突出；
- DeepSeek：推理字段、有限重试、checkpoint 和 session memory 最突出。

语音、宠物等外围功能不在本教学项目范围内。
