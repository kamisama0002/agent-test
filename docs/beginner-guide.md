# 从零开始：Agent 学习与项目使用指南

这份文档写给第一次接触 LangChain、Agent Harness 和本项目的同学。

目标不是让你背 API，而是让你能够：

1. 把项目环境跑起来；
2. 按顺序理解 5 类案例；
3. 独立跑 Codex、Claude、Hermes 三套 mini Harness；
4. 看懂运行时事件和源码流程图；
5. 知道遇到报错时先检查什么。

---

## 0. 先建立一张地图

| 层 | 内容 | 你应该先学会什么 |
|---|---|---|
| 基础层 | LangChain 15 个案例 | 模型、消息、提示词、工具、RAG、Agent |
| 对比层 | 五框架售后工单项目 | LangChain / LangGraph / CrewAI / LlamaIndex / OpenAI Agents SDK |
| Codex mini | 开发型 Harness | `AGENTS.md`、工具循环、验证、事件 |
| Claude mini | Claude Code 风格 Harness | `CLAUDE.md`、权限、hooks、LangGraph、MCP |
| Hermes mini | 通用型 Harness | MEMORY、USER、SKILL、后台复盘、会话检索 |

推荐顺序：

```text
环境准备
  → LangChain 基础案例
  → 五框架对比
  → Codex mini
  → Claude mini
  → Hermes mini
  → 源码流程图和实时 Viewer
  → 自己改一个小功能
```

不要一开始就读完所有源码。先跑通，再看事件，最后看源码。

---

## 1. 环境准备

### 1.1 你需要什么

- Windows 10/11、PowerShell；
- Python 3.11 或更高版本；
- `uv`：项目依赖管理工具；
- Git：可选，但推荐安装；
- 一个可用的百炼 API Key。

先检查：

```powershell
python --version
uv --version
git --version
```

如果 `uv` 不存在，可以安装：

```powershell
winget install --id astral-sh.uv -e
```

或者：

```powershell
python -m pip install uv
```

安装后重新打开 PowerShell，再执行 `uv --version`。

### 1.2 获取项目

```powershell
git clone https://github.com/kamisama0002/agent-test.git
cd agent-test
```

如果已经有当前工作区，直接进入项目根目录即可。后面所有命令都默认在项目根目录执行。

### 1.3 安装依赖

```powershell
uv sync
```

第一次安装会下载 LangChain、LangGraph、CrewAI、LlamaIndex、OpenAI Agents SDK、FastMCP、pytest 和 Notebook 依赖，可能需要几分钟。

### 1.4 配置 API Key

```powershell
Copy-Item .env.example .env
```

打开 `.env`，填写：

```dotenv
BAILIAN_API_KEY=你的真实Key
BAILIAN_BASE_URL=https://llm-i9yh569m2mtagoyf.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_CHAT_MODEL=deepseek-v4.1-flash
BAILIAN_EMBEDDING_MODEL=
MODEL_TEMPERATURE=0
MODEL_MAX_TOKENS=1600
MODEL_TIMEOUT=90
```

注意：

- 文档和代码里不要写真实 Key；
- `.env` 已经在 `.gitignore` 中；
- 不要把 `.env` 发给别人或提交到 Git；
- 当前项目默认使用百炼的 OpenAI 兼容接口，模型名可以换，但工具调用能力要自己验证。

### 1.5 第一次健康检查

```powershell
uv run python main.py --check
uv run pytest -q
```

预期：

- `main.py --check` 能识别配置；
- 测试最后显示 `35 passed` 或类似结果；
- 出现 pydantic / LangSmith deprecation warning 不一定代表失败，先看 pytest 最后一行。

如果你的环境没有网络，`uv sync` 和真实模型调用会失败，但离线 pytest 和部分工具测试仍应尽量通过。

---

## 2. 先认识目录

```text
.
├── main.py                     # LangChain 15 个案例的统一入口
├── LangChain测试.ipynb
├── LangGraph测试.ipynb
├── CrewAI测试.ipynb
├── Llamalnd测试.ipynb
├── OpenAiAgentsSDK测试.ipynb
├── 框架对比.ipynb
├── MiniCodexHarness.ipynb
├── ClaudeHarness.ipynb
├── HermesHarness.ipynb
├── langchain_cases/            # 15 个独立 LangChain 案例
├── support_project/            # 五框架售后工单项目
├── mini_codex/                 # Codex 风格开发 Harness
├── claude_harness/             # Claude Code 风格 Harness
├── hermes_harness/             # 通用 Agent + 记忆/技能/复盘
├── examples/                   # 三个可运行 demo
├── docs/                       # 架构、名词表、系统图
├── tests/                      # 离线测试
├── docs/system-maps/           # Archify 源码图和实时 Viewer
└── .env                        # 本地配置，不提交
```

运行结束后还可能看到这些运行时目录：

```text
.mini_codex/     # Mini Codex 的运行记录
.claude/         # Claude mini 的运行记录和 session memory
.hermes/         # Hermes mini 的记忆、技能、会话和运行记录
```

它们都是本地运行数据，不要提交。

---

## 3. 第一阶段：LangChain 15 个案例

### 3.1 先看目录和列表

```powershell
uv run python main.py --list
```

先不要一次跑完 15 个案例。建议按主题分组：

1. 01-04：模型、结构化输出、工具、短期记忆；
2. 05-08：RAG、流式、middleware、人机协同；
3. 09-12：多 Agent、MCP、上下文工程、RAG 进阶；
4. 13-15：生产化、可观测性、综合案例。

### 3.2 从一个最小案例开始

```powershell
uv run python main.py 1
```

打开 `langchain_cases/` 里对应文件，边运行边看：

- 消息是怎么构造的；
- `prompt | model | parser` 的数据流；
- 模型返回的 `AIMessage` 和工具调用；
- 输出为什么是字符串或结构化对象。

### 3.3 第二个案例

```powershell
uv run python main.py 3
```

案例 03 是工具 Agent 的入口。重点观察：

```text
用户问题
  → 模型决定是否调用工具
  → LangChain 执行工具
  → ToolMessage 回到模型
  → 模型生成最终答案
```

### 3.4 用 Notebook 学习

打开 `LangChain测试.ipynb`，选择项目 `.venv` 对应的 Python kernel，按顺序运行。

建议先跑：

- 模型、消息、LCEL；
- 结构化输出；
- 工具 Agent；
- 短期记忆；
- RAG。

每次只改一个变量，例如：

- 修改 system prompt；
- 增加一个工具；
- 把 temperature 改为 0；
- 换一个更小的任务。

### 3.5 这一阶段的练习

完成下面任意两个：

- 给案例 01 增加一个“用中文回答”的 system prompt；
- 给案例 03 增加一个计算器工具；
- 给案例 05 换一份自己的 Markdown 文档；
- 观察一次工具调用的 `AIMessage.tool_calls` 和 `ToolMessage`。

不要急着看 Harness。先确认你能看懂“模型 → 工具 → 模型”的基本循环。

---

## 4. 第二阶段：五框架对比项目

同一笔售后问题，用五种方式实现：

```powershell
uv run python -m support_project.runner --list
```

先跑一个框架：

```powershell
uv run python -m support_project.runner --framework langchain --full
uv run python -m support_project.runner --framework langgraph --full
```

再跑全部：

```powershell
uv run python -m support_project.runner --all
```

`--all` 会调用真实模型，耗时和费用都比单个框架高。初学阶段不要反复跑全部。

### 4.1 看什么

| 框架 | 你应该观察什么 |
|---|---|
| LangChain | 模型的自主工具调用序列 |
| LangGraph | 固定节点、条件边、`trace` 状态 |
| CrewAI | 角色、任务依赖、顺序 Crew |
| LlamaIndex | 文档索引、QueryEngineTool、引用 |
| OpenAI Agents SDK | Triage、handoff、最终 Agent |

注意：五个 adapter 的 `trace` 语义并不完全一样。LangChain 和 LangGraph 更接近真实执行轨迹；CrewAI、LlamaIndex 目前有静态标签；OpenAI Agents SDK 主要暴露最终 Agent。

对应源码图：

- `docs/system-maps/support-project.html`

### 4.2 推荐阅读顺序

```text
support_project/domain.py
  → runner.py
  → adapters/langchain_adapter.py
  → adapters/langgraph_adapter.py
  → 其他三个 adapter
```

先看共享业务函数，再看每个框架怎么编排。不要让框架名词遮住业务逻辑。

### 4.3 这一阶段的练习

- 只运行 LangGraph，数一数状态图里有哪些节点；
- 对比 LangChain 和 LangGraph 的 `trace` 字段；
- 把售后问题换成一个“订单号不存在”的案例，观察错误路径；
- 说明你为什么会在某个业务场景选择其中一个框架。

---

## 5. 第三阶段：Mini Codex

### 5.1 它解决什么问题

Mini Codex 是一个开发型 Harness，主循环是：

```text
bootstrap → context → plan
  → model
  → 如果有 tool_calls：执行工具 → 回到 model
  → 如果没有 tool_calls：verify → finalize
```

它重点展示：

- `AGENTS.md` 项目指令；
- 文件读取、搜索、修改、命令执行；
- 计划 `PlanState`；
- 验证命令；
- `events.jsonl`、`timeline.md`、`summary.md`、`changes.diff`。

它没有动态 `SKILL.md` 技能系统。`AGENTS.md` 是指令层，不是 Hermes 的技能层。

### 5.2 跑 demo

先在临时目录运行，避免修改项目中的 demo：

```powershell
Copy-Item examples/mini_codex_demo $env:TEMP/mini_codex_demo -Recurse -Force
uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "修复 calculator.py 中 add 的 bug，运行测试并总结" `
  --verify-command "python -m pytest -q"
```

如果只想先看流程，不加 `--enable-multi-agent` 和 `--enable-mcp`。

### 5.3 看运行产物

```powershell
Get-ChildItem $env:TEMP/mini_codex_demo/.mini_codex/runs
```

进入最新 run 目录，查看：

```powershell
Get-Content events.jsonl
Get-Content timeline.md
Get-Content summary.md
```

重点观察：

- `bootstrap`、`context`、`plan`；
- 每次 `model_request`；
- `tool_started` / `tool_finished`；
- `verification_completed`；
- 最终 `run_completed`。

### 5.4 看源码

推荐顺序：

```text
mini_codex/harness.py       # 主循环和阶段
mini_codex/context.py       # AGENTS.md 和环境
mini_codex/tools.py         # 开发工具和路径边界
mini_codex/events.py        # 事件与 timeline
mini_codex/multi_agent.py   # 子 Agent
```

### 5.5 打开图

静态源码图：

- `docs/system-maps/mini-codex.html`

实时查看：

```powershell
uv run python docs/system-maps/live_viewer.py `
  --system mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --open
```

### 5.6 这一阶段的练习

- 把 `add` 改错，再让 Agent 修复；
- 观察一次失败验证和一次成功验证；
- 在 `events.jsonl` 中找到 `tool_started`，说出它对应哪个工具；
- 尝试加一条 `AGENTS.md` 规则，看模型是否遵守。

---

## 6. 第四阶段：Claude mini

### 6.1 它解决什么问题

Claude mini 用 LangGraph 表达 Claude Code 风格的 `queryLoop`：

```text
prepare → plan → model
  → tool_calls → tools → compact → model
  → no tool_calls → finalize
```

重点概念：

- `CLAUDE.md`、`.claude/rules/*.md`；
- permission mode；
- pre/post hooks；
- `TodoWrite`；
- microcompact / full compact；
- `Task / SendMessage / TaskOutput`；
- MCP 工具；
- `InMemorySaver` checkpoint。

注意：当前实现只有内存 checkpoint，所以不要把它误解成真正的“中断后持久恢复”。真实 HITL 还需要 durable checkpointer、interrupt/resume 和 UI 协议。

### 6.2 跑 demo

```powershell
Copy-Item examples/claude_harness_demo $env:TEMP/claude_harness_demo -Recurse -Force
uv run python -m claude_harness `
  --workspace $env:TEMP/claude_harness_demo `
  --task "先探索仓库，再修复 add 并运行测试" `
  --permission-mode acceptEdits `
  --auto-approve `
  --verify-command "python -m pytest -q"
```

想观察只读模式，可以改成：

```powershell
--permission-mode plan
```

这时写文件和执行命令会被拒绝。

### 6.3 看源码

```text
claude_harness/harness.py      # LangGraph 节点和条件边
claude_harness/context.py      # CLAUDE.md 和压缩
claude_harness/permissions.py  # 权限模式
claude_harness/tools.py        # Read/Edit/Bash/TodoWrite
claude_harness/hooks.py        # 工具前后 hook
claude_harness/multi_agent.py  # Task/SendMessage/TaskOutput
```

### 6.4 打开图

- 静态图：`docs/system-maps/claude-harness.html`
- 实时查看：

```powershell
uv run python docs/system-maps/live_viewer.py `
  --system claude_harness `
  --workspace $env:TEMP/claude_harness_demo `
  --open
```

### 6.5 这一阶段的练习

- 先用 `plan` 模式跑一次，确认写文件会被拒绝；
- 再用 `acceptEdits` 跑一次，观察权限事件；
- 在 `events.jsonl` 里找到 `permission_decision`；
- 比较 `prepare`、`model`、`tools`、`compact` 四个阶段的职责。

---

## 7. 第五阶段：Hermes mini

### 7.1 它和 Codex/Claude 最大的不同

Codex 和 Claude 主要回答：

> 如何在代码仓库里安全地完成任务？

Hermes 还回答：

> 完成任务以后，Agent 如何记住用户、环境和一类任务的做法？

Hermes mini 的主循环：

```text
prepare(SOUL/MEMORY/USER/Skills)
  → model ↔ tools
  → finalize
  → background_review
```

### 7.2 跑第一次

```powershell
Copy-Item examples/hermes_harness_demo $env:TEMP/hermes_harness_demo -Recurse -Force
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "阅读 research.md，提炼三条结论；以后请先给结论再给依据。" `
  --toolsets hermes
```

第一次运行后查看：

```powershell
Get-ChildItem $env:TEMP/hermes_harness_demo/.hermes -Recurse
Get-Content $env:TEMP/hermes_harness_demo/.hermes/memories/USER.md -ErrorAction SilentlyContinue
```

你可能看到：

- `USER.md` 多了用户偏好；
- `runs/<timestamp>/events.jsonl`；
- `summary.md`；
- `sessions/sessions.db`；
- `skills/` 下的技能或 `.usage.json`。

后台 review 是否真的写入内容，取决于模型是否判断值得保存。它不是固定模板。

### 7.3 跑第二次

再运行一次，但换一个任务：

```powershell
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "请用一句话总结当前项目的学习价值。" `
  --toolsets hermes
```

观察新会话是否自动带上 `MEMORY.md` 和 `USER.md`。这就是跨会话记忆。

### 7.4 看源码

```text
hermes_harness/harness.py   # prepare/model/tools/finalize/review
hermes_harness/memory.py    # MEMORY.md / USER.md
hermes_harness/skills.py    # SKILL.md、usage、curator
hermes_harness/sessions.py  # SQLite FTS5
hermes_harness/review.py    # 后台复盘
hermes_harness/toolsets.py  # 工具裁剪
```

### 7.5 打开图

- 静态图：`docs/system-maps/hermes-harness.html`
- 实时查看：

```powershell
uv run python docs/system-maps/live_viewer.py `
  --system hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --open
```

### 7.6 这一阶段的练习

- 第一次运行时明确说一个长期偏好；
- 第二次运行时问它“你知道我的偏好吗”；
- 查看 `USER.md` 和 `MEMORY.md`，说出两者分工；
- 打开 `skills/`，找到 `skills_list` 和 `skill_view` 的区别；
- 用 `session_search` 搜索第一次对话。

---

## 8. Notebook 怎么用

本机已经注册过名为 `Python (agent测试)` 的 Jupyter kernel。换机器时执行：

```powershell
uv run python -m ipykernel install --user --name agent-test --display-name "Python (agent测试)"
```

然后在 IDE 中选择这个 kernel。

| Notebook | 适合什么时候看 |
|---|---|
| `LangChain测试.ipynb` | 第一阶段 |
| `LangGraph测试.ipynb` | 学状态图、checkpoint、HITL |
| `CrewAI测试.ipynb` | 学角色/任务/Crew |
| `Llamalnd测试.ipynb` | 学索引、检索、引用 |
| `OpenAiAgentsSDK测试.ipynb` | 学 handoff/guardrail |
| `框架对比.ipynb` | 五框架横向比较 |
| `MiniCodexHarness.ipynb` | Codex 阶段 |
| `ClaudeHarness.ipynb` | Claude 阶段 |
| `HermesHarness.ipynb` | Hermes 记忆/技能/复盘 |
| `MultiAgentPatterns.ipynb` | Codex/Claude 多 Agent 对照 |

建议：

1. 先阅读 Markdown 单元；
2. 一次只运行一个代码单元；
3. 运行前确认 `.env`；
4. 有真实模型调用的单元不要无脑“Run All”；
5. 出问题先看单元输出的最后一段 traceback。

---

## 9. 一套 10 天学习计划

| 天 | 任务 | 产出 |
|---|---|---|
| 1 | 安装依赖、配置 `.env`、跑健康检查 | 能运行 `main.py --check` 和 pytest |
| 2 | LangChain 01-04 | 理解模型、结构化输出、工具、短期记忆 |
| 3 | LangChain 05-08 | 理解 RAG、stream、middleware、HITL |
| 4 | LangChain 09-15 | 理解多 Agent、MCP、上下文、生产化 |
| 5 | 五框架项目 | 能说清五个框架的差异 |
| 6 | Mini Codex | 能读 `events.jsonl` 和源码图 |
| 7 | Claude mini | 能比较 `plan` 和 `acceptEdits` |
| 8 | Hermes mini 第一次 | 看到 `USER.md`、skills、session |
| 9 | Hermes mini 第二次 | 验证跨会话记忆和 session_search |
| 10 | 实时 Viewer + 自改功能 | 能对着图解释一次运行 |

每天不要追求看完所有代码。每天有一个“能讲出来”的结论就够了。

---

## 10. 源码阅读路线

### 10.1 通用原则

按这个顺序读：

```text
入口文件
  → 主循环
  → 上下文/消息
  → 工具执行
  → 事件/结果
  → 测试
```

不要从工具函数列表开始读，否则很容易不知道这些工具为什么存在。

### 10.2 Codex

```text
mini_codex/harness.py
mini_codex/context.py
mini_codex/tools.py
mini_codex/events.py
tests/test_mini_codex_tools.py
```

问题清单：

- 一个 turn 从哪里开始、到哪里结束？
- 哪些消息会进入下一次模型调用？
- 工具结果如何变成 `ToolMessage`？
- `verification_passed` 什么时候为真？
- `events.jsonl` 哪些事件可以证明一个工具真的执行了？

### 10.3 Claude

```text
claude_harness/harness.py
claude_harness/context.py
claude_harness/permissions.py
claude_harness/tools.py
claude_harness/multi_agent.py
tests/test_claude_harness.py
```

问题清单：

- `queryLoop` 的节点和边分别是什么？
- 权限判断发生在工具执行前还是后？
- microcompact 和 full compact 有什么区别？
- `InMemorySaver` 能恢复什么，不能恢复什么？
- `Task` 和普通只读工具 `Explore` 有什么区别？

### 10.4 Hermes

```text
hermes_harness/harness.py
hermes_harness/memory.py
hermes_harness/skills.py
hermes_harness/sessions.py
hermes_harness/review.py
hermes_harness/toolsets.py
tests/test_hermes_harness.py
tests/test_hermes_memory_skills.py
```

问题清单：

- `MEMORY.md` 和 `USER.md` 分别保存什么？
- 为什么记忆要使用字符预算，而不是无限增长？
- 为什么 `skills_list` 不直接返回完整技能正文？
- 后台 review 为什么不能使用 `write_file`？
- curator 为什么只归档、不删除？
- FTS5 如何处理中文？

---

## 11. 源码图和实时 Viewer

### 11.1 静态图

先看静态图，对整体结构有印象：

- `docs/system-maps/mini-codex.html`
- `docs/system-maps/claude-harness.html`
- `docs/system-maps/hermes-harness.html`
- `docs/system-maps/support-project.html`

看图时注意：

- 节点上的 source 标记可以点开 GitHub 源码；
- 源码链接固定在某个 commit，不是当前工作区实时文件；
- 实线/条件边表示源码中的路径，不代表每次都会走到；
- Codex/Claude 图里的“skills”卡片是在提醒你：这两个 Harness 没有动态 `SKILL.md` 系统；
- Hermes 图里才有 MEMORY、USER、SKILL、FTS、review、curator。

### 11.2 实时一步步高亮

先跑案例，再启动：

```powershell
uv run python docs/system-maps/live_viewer.py `
  --system hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --open
```

页面会：

- 加载对应的 Archify HTML；
- 每 600ms 读取 `events.jsonl`；
- 当前节点用青色描边；
- 已走过的节点用绿色描边；
- 右侧显示事件流、当前节点、当前工具和进度；
- 支持暂停、继续、从头回放、速度控制。

Codex 和 Claude 只需换：

```text
--system mini_codex
--system claude_harness
```

注意：

- 这是浏览器里的近实时轮询，不是 WebSocket；
- 页面显示的是“事件流和源码节点的映射”，不是 IDE 的源码热更新；
- 如果还没跑案例，先运行案例，或显式传 `--run-dir`；
- Support Project 没有 EventBus，只有最终 trace，所以只做静态对照图。

### 11.3 三套 mini 的统一入口

如果不想分别记三个 `python -m ...` 命令，可以用：

```powershell
uv run python main_mini.py --system codex
uv run python main_mini.py --system claude
uv run python main_mini.py --system hermes
```

它会自动复制对应 demo 到临时目录，并启动实时 Viewer；每轮对话产生的新 run 会自动出现在图中。

不需要 Viewer 时加 `--no-viewer`；只跑一次时加 `--task`。

### 11.4 看图的顺序

1. 先看 prepare/context；
2. 再看 model；
3. 找到 tool_started 和 tool_finished；
4. 看 compact 或 review；
5. 最后看 finalize 和产物文件。

---

## 12. 常见问题排查

### 12.1 `uv sync` 失败

先看网络和 Python 版本：

```powershell
python --version
uv --version
uv sync -v
```

如果是网络问题，可以换网络或设置代理；如果提示 Python 版本不满足，安装 3.11+。

### 12.2 提示找不到 API Key

检查：

```powershell
Test-Path .env
Get-Content .env.example
```

确认 `.env` 存在，并且有 `BAILIAN_API_KEY`。不要把 Key 发到聊天或提交到 Git。

### 12.3 401 / 403 / 模型不存在

检查：

- Key 是否完整；
- `BAILIAN_BASE_URL` 是否包含 `/compatible-mode/v1`；
- `BAILIAN_CHAT_MODEL` 是否是网关上可用的模型；
- 当前 Key 是否有对应模型权限。

### 12.4 模型不调用工具

Agent 可能只是直接回答。尝试：

- 把任务写得更明确，例如“先读取文件，再修改，再运行测试”；
- 降低 `MODEL_TEMPERATURE`；
- 换一个工具调用能力稳定的模型；
- 先跑离线测试确认工具本身可用。

### 12.5 没有 events.jsonl

确认：

- 运行的是 `mini_codex`、`claude_harness` 或 `hermes_harness`；
- 看的是最新 run 目录；
- 不是在项目根目录误找 `.mini_codex`；
- `--workspace` 指向的是实际运行目录。

### 12.6 Viewer 端口被占用

```powershell
uv run python docs/system-maps/live_viewer.py `
  --system hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --port 8766 `
  --open
```

换一个端口即可。

### 12.7 Notebook 选错 Kernel

在 Notebook 右上角选择：

```text
Python (agent测试)
```

或者运行：

```powershell
uv run python -m ipykernel install --user --name agent-test --display-name "Python (agent测试)"
```

### 12.8 Windows 的续行符

PowerShell 的续行符是反引号 `` ` ``，不是反斜杠 `\`。

```powershell
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "总结项目"
```

复制多行命令时，反引号后面不要多按空格。

---

## 13. API 成本和运行安全

### 13.1 控制调用次数

- 初学先跑离线 pytest；
- `support_project.runner --all` 会运行五个框架，费用更高；
- Hermes 的 background review 会额外调用一次模型；
- 不需要复盘时加 `--no-review`；
- 需要限制轮数时使用 `--max-turns` / `--review-max-turns`。

### 13.2 不要把运行数据提交

应该在 `.gitignore` 中的内容：

```text
.env
.hermes/
.mini_codex/
.claude/
.archify/
```

提交前检查：

```powershell
git status --short
git diff --cached
```

### 13.3 不要把真实 Key 写进 Notebook

Notebook 单元会保存输出。即使你删除了代码，输出里仍可能留下 Key。正确做法：

- 从 `.env` 读取；
- 不把 Key 打 print 出来；
- 不把 `.env` 上传到聊天、GitHub 或网盘。

---

## 14. 小白必须掌握的 12 个名词

| 名词 | 先用一句话理解 |
|---|---|
| LLM | 接收消息、生成回答的模型 |
| Prompt | 给模型的指令和上下文 |
| Tool | 模型可以请求执行的外部函数 |
| Tool Call | 模型说“我要调用哪个工具、参数是什么” |
| Tool Result | Harness 执行工具后放回上下文的结果 |
| Agent Loop | 模型 → 工具 → 模型，直到模型给最终答案 |
| Harness | 包在模型外面的循环、工具、上下文、权限、状态 |
| Context | 本次模型能看到的系统提示、历史、工具结果 |
| Compact | 上下文太长时压缩旧消息 |
| Checkpoint | 保存图或会话状态，供恢复/检查 |
| Subagent | 由主 Agent 启动、拥有独立上下文的子 Agent |
| Trace / Event | 记录执行过程的结构化事件 |

完整名词表：

- `docs/agent-systems-glossary.md`

---

## 15. 推荐练习：做一个自己的小 Agent

当你跑通前面的案例后，做一个最小项目：

### 题目

做一个“个人学习资料助手”：

- 有一个 `notes/` 目录；
- 工具能列出、读取和搜索 Markdown；
- 用户问“帮我总结某一篇笔记”时，Agent 先搜索，再读取，再总结；
- 每次运行写一个 `events.jsonl`；
- 最后给出引用到的文件名。

### 要求

1. 不直接读取 `.env`；
2. 文件路径不能越出 workspace；
3. 至少有一个只读工具；
4. 如果文件不存在，返回明确错误，不要编造内容；
5. 在 README 中说明如何运行。

### 进阶

- 加入 `TODO` 计划；
- 加入一个只读子 Agent；
- 用 Hermes 的 `USER.md` 记录“我总是先要结论”；
- 用 Archify 给你的 Agent 画一张源码图；
- 用 `live_viewer.py` 的思路做事件高亮。

---

## 16. 推荐文档索引

先读：

- `README.md`：项目总览和命令；
- `docs/agent-systems-glossary.md`：名词表；
- 本文件：学习路线。

理解三套 Harness：

- `docs/mini-codex-architecture.md`
- `docs/claude-harness-architecture.md`
- `docs/hermes-harness-architecture.md`

理解差异：

- `docs/hermes-vs-codex-claude.md`
- `docs/claude-vs-codex.md`
- `docs/multi-agent-communication.md`
- `docs/runtime-extensions.md`

看源码图：

- `docs/system-maps/README.md`
- `docs/system-maps/mini-codex.html`
- `docs/system-maps/claude-harness.html`
- `docs/system-maps/hermes-harness.html`
- `docs/system-maps/support-project.html`

---

## 17. 每次运行前的 6 项检查

```text
[ ] 在项目根目录
[ ] .env 存在且有 Key
[ ] 已执行 uv sync
[ ] 示例先复制到临时目录
[ ] 知道这次会调用真实模型
[ ] 知道运行产物目录在哪里
```

每次运行后的 4 个动作：

```text
[ ] 看最终回答
[ ] 看 summary.md
[ ] 看 events.jsonl / timeline.md
[ ] 对照源码图找到对应节点
```

---

## 18. 一页命令速查

```powershell
# 环境
uv sync
uv run python main.py --check
uv run pytest -q

# LangChain
uv run python main.py --list
uv run python main.py 1
uv run python main.py 3

# 五框架
uv run python -m support_project.runner --list
uv run python -m support_project.runner --framework langgraph --full

# Codex mini
uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "修复 add 并运行测试" `
  --verify-command "python -m pytest -q"

# Claude mini
uv run python -m claude_harness `
  --workspace $env:TEMP/claude_harness_demo `
  --task "修复 add 并运行测试" `
  --permission-mode acceptEdits --auto-approve `
  --verify-command "python -m pytest -q"

# Hermes mini
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "阅读 research.md 并总结；以后先给结论再给依据。" `
  --toolsets hermes

# 实时查看器
uv run python docs/system-maps/live_viewer.py `
  --system hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --open

# 运行全部离线测试
uv run pytest -q
```

---

## 19. 最后一条建议

先让一个小案例真实跑通，再问“为什么”。

顺序永远是：

```text
能运行
  → 能看事件
  → 能读主循环
  → 能改一个工具
  → 能解释一次失败
```

当你能对着 `events.jsonl` 说出“现在在执行哪个节点、为什么进入这个分支”，你就不只是会调用 API，而是开始理解 Agent Harness 了。
