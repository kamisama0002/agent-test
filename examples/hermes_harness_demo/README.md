# Hermes Mini 演示项目

这是一个“通用任务”而不是修 bug 的小仓库，用来观察 Hermes 的学习闭环：

1. 第一次运行：让 Agent 阅读 `research.md`，总结关键结论；
2. 在任务中表达一个长期偏好，例如“以后先给结论，再给依据”；
3. 后台复盘会把偏好写入 `.hermes/memories/USER.md`，把任务方法写成 `SKILL.md`；
4. 第二次运行：新会话会自动注入偏好和技能索引；
5. 用 `session_search` 可以检索第一次会话。

运行（在工作区副本上执行，避免把 `.hermes` 写回仓库）：

```powershell
Copy-Item examples/hermes_harness_demo $env:TEMP/hermes_harness_demo -Recurse -Force
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "阅读 research.md，提炼三条结论；以后请先给结论再给依据。" `
  --toolsets hermes
```

第一次运行后查看：

```text
$env:TEMP/hermes_harness_demo/.hermes/
├── memories/MEMORY.md
├── memories/USER.md
├── skills/
├── sessions/sessions.db
└── runs/<timestamp>/
    ├── events.jsonl
    ├── timeline.md
    └── summary.md
```
