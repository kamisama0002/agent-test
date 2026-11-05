# Runtime Extensions：插件、审批、MCP 与多 Agent

这份文档说明当前项目新增的共享运行时能力。它们不是三个 Harness 各写一份，
而是放在 `agent_runtime/` 中，再由 Codex、Claude、Hermes 分别接入。

## 1. 为什么需要这一层

一个 Agent 不只是“模型 + 一个 while 循环”。开发场景还需要：

- 工具注册和 Codex 风格工具别名；
- 本地插件；
- MCP 动态工具；
- 子 Agent；
- 写入/命令的审批边界；
- 事件流和可视化。

本项目的原则是：

```text
LangGraph 负责外层编排和工具循环
agent_runtime 负责共享运行时能力
各 Harness 负责上下文、权限和运行产物
```

## 2. Codex 风格的循环

Mini Codex 现在支持两种模式：

```powershell
# 默认：LangGraph 工具循环
uv run python -m mini_codex --workspace <dir> --task "..."

# 对照组：原来的过程式 for 循环
uv run python -m mini_codex --workspace <dir> --task "..." --engine loop
```

LangGraph 版本在 `agent_runtime/tool_loop.py`，结构是：

```text
START → model --有 tool_calls--> tools → model
             └─ 无 tool_calls ─────────→ END
```

外层 `MiniCodexHarness` 仍负责：

```text
bootstrap → context → plan → graph tool loop → verify → finalize
```

这是“外层图 + 内核工具循环”的混合结构，而不是把文件、命令、审批和流式输出
全部塞进 LangGraph 节点。

## 3. Tool Registry 和别名

Mini Codex 新增了贴近 Codex 的工具名：

- `exec_command`：命令执行别名；
- `apply_patch`：用 path + old/new 的简化补丁；
- `request_permissions`：演示审批边界。

原有的 `write_file`、`replace_in_file`、`run_command` 仍保留，方便对照。
Claude 使用自己的 `Read/Edit/Bash/TodoWrite`，Hermes 使用通用工具集。

## 4. 本地插件

插件必须由用户显式传入目录，不会自动从网络下载。

目录结构：

```text
examples/plugins/text_utils/
├── plugin.json
└── plugin.py
```

`plugin.json` 示例：

```json
{
  "name": "text-utils",
  "version": "0.1.0",
  "tools": [
    {
      "name": "word_count",
      "description": "统计一段文本的词数和字符数",
      "entry": "plugin.py:word_count",
      "read_only": true
    }
  ]
}
```

运行：

```powershell
uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "统计这段文本的词数：hello world" `
  --plugin-dir examples/plugins
```

Claude 和 Hermes 也接受：

```text
--plugin-dir examples/plugins
```

插件加载器在 `agent_runtime/plugins.py`，会检查：

- manifest 是否存在；
- 入口路径是否越出插件目录；
- 工具名是否冲突；
- 入口是否是函数；
- 工具是 read-only 还是 destructive。

## 5. 审批边界

共享实现：`agent_runtime/approval.py`。

支持：

| 模式 | 行为 |
|---|---|
| `auto` | 自动允许，适合本地可信 demo |
| `ask` | 有 callback 才允许，否则拒绝并记录 ask |
| `deny` | 拒绝写入/命令等副作用 |

Codex/Hermes 使用示例：

```powershell
uv run python main_mini.py --system codex --approval-mode deny --no-viewer
uv run python main_mini.py --system hermes --approval-mode ask --no-viewer
```

Claude 仍有自己的 permission mode：

```text
default / plan / acceptEdits / bypassPermissions / dontAsk
```

审批事件会写入：

```text
events.jsonl
  type=approval_decision
  data.behavior=allow|deny|ask
```

后台 review 和子 Agent 不应该绕过这层审批；它们只获得自己需要的最小工具面。

## 6. MCP

已存在的本地只读 MCP server 暴露：

- `repo_stats`
- `find_todos`

启用：

```powershell
uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "查看仓库统计" `
  --enable-mcp
```

Claude：

```powershell
uv run python -m claude_harness `
  --workspace $env:TEMP/claude_harness_demo `
  --task "调用 MCP repo_stats 后总结" `
  --enable-mcp --permission-mode acceptEdits --auto-approve
```

Hermes：

```powershell
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "调用 MCP repo_stats 后总结" `
  --enable-mcp
```

MCP 工具被当作只读工具接入；状态和错误会通过事件记录。它不是“把 MCP
server 的所有能力无脑暴露”，而是显式加载和合并。

## 7. 多 Agent

### Codex

```text
spawn_agent / send_input / wait_agent / list_agents / close_agent
```

### Claude

```text
Task / SendMessage / TaskOutput / TaskList / CloseAgent
```

### Hermes

```text
delegate_task / send_input / wait_agent / list_agents / close_agent
```

Hermes 的 `delegate_task` 默认只读，不能写文件、执行命令或修改记忆。

运行：

```powershell
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "用 delegate_task 研究 research.md，再总结" `
  --enable-multi-agent
```

所有实现共享 `agent_runtime/runtime.py` 的 mailbox 语义：

```text
父 Agent spawn 子 Agent
  → 子 Agent 独立上下文
  → 父 Agent send_input 进入 inbox
  → 子 Agent 在下一轮 model 采样前消费
  → 父 Agent wait_agent 读取结果
```

## 8. 统一交互入口

`main_mini.py` 可以启动三套 Harness，并自动打开实时 Viewer：

```powershell
uv run python main_mini.py --system codex
uv run python main_mini.py --system claude
uv run python main_mini.py --system hermes
```

它还会自动把对应 demo 复制到临时目录，避免修改 `examples/`。

每轮对话产生新的 run，Viewer 会自动跟随该 workspace 最新的 run。

常用参数：

```text
--task              只跑一次
--no-viewer         不启动实时图
--no-open           启动 Viewer 但不打开浏览器
--enable-multi-agent
--enable-mcp
--plugin-dir PATH
--approval-mode auto|ask|deny
--permission-mode ...  # Claude
--engine langgraph|loop # Codex
```

## 9. 当前边界

这是可运行的教学版，不是生产 Harness：

- 插件没有签名和依赖隔离；
- MCP 只演示 stdio 只读工具；
- 审批没有持久 UI 队列；
- 多 Agent 没有持久 mailbox、预算配额和跨进程恢复；
- LangGraph checkpoint 仍是可选的教学点，生产需要持久化 checkpointer；
- 没有 OS 级 sandbox。

对应的生产增强方向：

```text
插件签名 + 隔离环境
审批队列 + app-server / UI
MCP 鉴权 + 超时 + 命名空间
持久 mailbox + 子 Agent 预算
SqliteSaver / PostgresSaver
OS sandbox + 网络策略
```
