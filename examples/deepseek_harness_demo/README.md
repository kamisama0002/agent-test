# DeepSeek Harness Demo

这是一个故意带有 bug 的最小 Python 项目，用于验证 DeepSeek Harness 的
上下文、推理记录、工具循环、checkpoint、审批和验证流程。

```powershell
uv run python -m pytest -q
```

然后让 Harness 修复：

```powershell
uv run python -m deepseek_harness --workspace examples/deepseek_harness_demo `
  --task "修复 calculator.py 中 add 的 bug，运行测试并总结" `
  --verify-command "python -m pytest -q"
```
