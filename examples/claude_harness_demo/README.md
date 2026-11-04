# Claude Harness Demo

```powershell
Copy-Item examples/claude_harness_demo $env:TEMP/claude_harness_demo -Recurse -Force

uv run python -m claude_harness `
  --workspace $env:TEMP/claude_harness_demo `
  --task "修复 calculator.py 中 add 的 bug，让 pytest 通过" `
  --permission-mode acceptEdits `
  --auto-approve `
  --verify-command "python -m pytest -q"
```
