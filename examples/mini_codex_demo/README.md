# Mini Codex Demo

先运行测试观察失败：

```powershell
python -m pytest -q
```

然后让 Mini Codex 修复：

```powershell
python -m mini_codex --workspace examples/mini_codex_demo `
  --task "修复 calculator.py 中 add 的 bug，运行测试并总结" `
  --verify-command "python -m pytest -q"
```
