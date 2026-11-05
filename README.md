# LangChain + 五框架 Agent + Mini Codex + Claude + Hermes mini

这个项目现在包含五层内容：

1. **LangChain 核心能力教程**：15 个可独立运行的 Python 案例；
2. **五框架售后工单小项目**：同一业务分别用 LangChain、LangGraph、CrewAI、LlamaIndex、OpenAI Agents SDK 实现；
3. **Mini Codex**：用 LangChain 复刻 Codex 的开发 Agent Harness，包含上下文、规划、工具循环、验证和事件可视化。
4. **Claude-style Harness**：用 LangGraph 复刻 Claude Code 的 `queryLoop`、`CLAUDE.md`、权限模式、TodoWrite、上下文压缩、子 Agent 和 MCP。
5. **Hermes mini**：通用 Agent Harness，复刻 `MEMORY.md` / `USER.md`、`SKILL.md`、后台复盘、curator、session_search 和 toolset。

所有示例统一接入阿里云百炼的 OpenAI 兼容接口，默认模型为 `deepseek-v4.1-flash`。

> 第一次学习？先看 [从零开始：Agent 学习与项目使用指南](docs/beginner-guide.md)，按环境准备、基础案例、三套 Harness、实时图的顺序走。

## 快速开始

```powershell
# 安装依赖（包含 pytest、Jupyter 执行依赖）
uv sync

# LangChain 示例
uv run python main.py --check
uv run python main.py --list
uv run python main.py 1

# 五框架小项目
uv run python -m support_project.runner --list
uv run python -m support_project.runner --framework langgraph --full
uv run python -m support_project.runner --all

# Mini Codex：Copilot/Codex-style Harness
Copy-Item examples/mini_codex_demo $env:TEMP/mini_codex_demo -Recurse -Force
uv run python -m mini_codex --workspace $env:TEMP/mini_codex_demo `
  --task "修复 calculator.py 中 add 的 bug，运行测试并总结" `
  --verify-command "python -m pytest -q" --enable-multi-agent --enable-mcp

# Claude-style Harness：在演示仓库副本上完成一次真实开发任务
Copy-Item examples/claude_harness_demo $env:TEMP/claude_harness_demo -Recurse -Force
uv run python -m claude_harness --workspace $env:TEMP/claude_harness_demo `
  --task "用 Task/TaskOutput 委派 explore，调用 MCP repo_stats，修复 add 并运行测试" `
  --permission-mode acceptEdits --auto-approve --enable-mcp `
  --verify-command "python -m pytest -q"

# Hermes mini：通用任务与长期学习
Copy-Item examples/hermes_harness_demo $env:TEMP/hermes_harness_demo -Recurse -Force
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "阅读 research.md，提炼三条结论；以后请先给结论再给依据。" `
  --toolsets hermes

# 三套 mini 的统一交互入口（自动启动实时 Viewer）
uv run python main_mini.py --system codex
uv run python main_mini.py --system claude
uv run python main_mini.py --system hermes

# 只跑一次、关闭实时 Viewer
uv run python main_mini.py --system hermes --task "总结当前项目" --no-viewer

# 离线测试
uv run pytest
```

## 五框架小项目

同一笔订单、同一份售后政策、同一个问题：

> 订单 A1001 的降噪耳机坏了，想退款，是否符合政策？

| 框架 | 项目中的实现方式 | 核心优势 | 适合场景 |
|---|---|---|---|
| **LangChain** | 单 Agent + 订单/退款/政策三个工具 | 工具、模型、Middleware、集成生态最完整 | 通用助手、业务 API 调用 |
| **LangGraph** | 显式状态图：查询→政策→退款→LLM 组织回复 | 状态、分支、checkpoint、HITL、可恢复执行 | 审批流、长流程、强审计 |
| **CrewAI** | 订单分析员、政策审核员、客服写作专员三角色 | 角色/任务/团队抽象自然 | 研究、分析、审核、写作 |
| **LlamaIndex** | 政策 VectorIndex + QueryEngineTool + FunctionAgent | 数据接入、索引、检索、引用 | 企业知识库、文档问答 |
| **OpenAI Agents SDK** | Triage Agent → Handoff → Refund Specialist | handoff、guardrail、tracing、API 轻量 | 分流/专家接管、OpenAI 生态 |

完整选型说明：[docs/framework-selection.md](docs/framework-selection.md)

特色能力实现索引（状态恢复、时间旅行、可视化、Handoff、Guardrail 等）：[docs/framework-feature-map.md](docs/framework-feature-map.md)

```powershell
# 单独运行
uv run python -m support_project.runner --framework langchain --full
uv run python -m support_project.runner --framework langgraph --full
uv run python -m support_project.runner --framework crewai --full
uv run python -m support_project.runner --framework llamaindex --full
uv run python -m support_project.runner --framework openai_agents --full

# 一次比较全部；可能耗时 1～2 分钟并产生真实模型调用
uv run python -m support_project.runner --all
```


## Mini Codex：用 LangChain 复刻开发 Agent Harness

这不是一个只会聊天的 Agent，而是一个可执行完整开发闭环的 Harness：

```text
bootstrap → context → plan → agent(model ↔ tools) → verify → finalize
```

它参照 Codex 开源 Harness 的核心设计：

- `AGENTS.md`、环境、历史和工具结果进入上下文；
- 模型返回 tool call 就执行工具，再继续采样；
- 模型只返回 assistant message 时结束 turn；
- 每个阶段、工具调用、token 和压缩都通过事件流暴露；
- 运行后保留 `events.jsonl`、`timeline.md`、`summary.md`、`changes.diff`。

Mini Codex 暴露的开发工具：

- `list_files` / `read_file` / `search_text`
- `write_file` / `replace_in_file`（简化版 `apply_patch`）
- `run_command`（简化版 `exec_command`）
- `git_status` / `git_diff`
- `update_plan`

可选能力：

- `--enable-multi-agent`：增加 `spawn_agent` / `send_input` / `wait_agent` / `list_agents` / `close_agent`；
- `--enable-mcp`：通过 MCP 动态加载只读 `repo_stats` 和 `find_todos`。

运行：

```powershell
# 建议先在副本上跑，避免修改原 demo
Copy-Item examples/mini_codex_demo $env:TEMP/mini_codex_demo -Recurse

uv run python -m mini_codex `
  --workspace $env:TEMP/mini_codex_demo `
  --task "修复 calculator.py 中 add 的 bug，让 pytest 通过" `
  --verify-command "python -m pytest -q"
```

详细架构、Codex 源码映射和事件说明：[docs/mini-codex-architecture.md](docs/mini-codex-architecture.md)

多 Agent 通信细节：[docs/multi-agent-communication.md](docs/multi-agent-communication.md)

Notebook 演示：[MiniCodexHarness.ipynb](MiniCodexHarness.ipynb)

## Claude Code-style Harness

Claude 版不是把 Codex 的代码换个名字，而是按 Claude Code 的 `queryLoop` 重新组织：

```text
prepare → plan(TodoWrite) → model ↔ tools → compact → finalize
```

覆盖的 Claude 特色：

- `CLAUDE.md`、`.claude/CLAUDE.md`、`.claude/rules/*.md`、`CLAUDE.local.md`；
- `Read/Glob/Grep/Explore/Write/Edit/Bash/TodoWrite` 工具；
- `default/plan/acceptEdits/bypassPermissions/dontAsk` 权限模式；
- `microcompact` + `full compact`；
- session memory；
- `Task / SendMessage / TaskOutput / TaskList / CloseAgent` 多 Agent；
- MCP `repo_stats / find_todos`；
- 事件 JSONL、timeline、summary、diff。

详细实现：[docs/claude-harness-architecture.md](docs/claude-harness-architecture.md)
多 Agent 通信：[docs/multi-agent-communication.md](docs/multi-agent-communication.md)
Claude/GPT 与两套 Harness 的异同：[docs/claude-vs-codex.md](docs/claude-vs-codex.md)
Notebook：[ClaudeHarness.ipynb](ClaudeHarness.ipynb)

Claude 源码研究材料位于 `D:\workspace\agent\claudecode`，包括 `Claude-Code-Source-Study` 和恢复源码 `claude-code-sourcemap`。

## Hermes mini：通用 Agent 的学习闭环

Hermes 的重点不是“更会写代码”，而是**通用任务 + 长期成长**：

```text
prepare(SOUL/MEMORY/USER/Skills) → model ↔ tools → finalize → background_review
```

它复刻了 Hermes v0.22.6 的以下思路：

- `MEMORY.md`：环境事实和项目约定；
- `USER.md`：用户画像和稳定偏好；
- `skills/SKILL.md`：程序性经验，`skills_list` 只给索引，`skill_view` 才加载全文；
- `skill_manage`：创建、patch、添加 references/templates/scripts；
- `curator`：14 天 stale、30 天 archive，只归档不删除，pinned 豁免；
- `session_search`：SQLite FTS5 + 中文 bigram；
- `toolset`：file / terminal / memory / skills / session_search / research / safe / coding；
- `background_review`：回合后独立模型复盘，只允许写 memory/skills；
- 事件写入 `events.jsonl`、`timeline.md`，并保存 `summary.md`。

运行通用任务示例（会生成 `.hermes/`，已在 `.gitignore` 中忽略）：

```powershell
Copy-Item examples/hermes_harness_demo $env:TEMP/hermes_harness_demo -Recurse -Force
uv run python -m hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo `
  --task "阅读 research.md，提炼三条结论；以后请先给结论再给依据。" `
  --toolsets hermes
```

第一次运行后，后台复盘可以写入 `.hermes/memories/USER.md` 和技能库；第二次运行会用新会话重新注入。

详细说明：

- [Hermes mini 源码对照与架构](docs/hermes-harness-architecture.md)
- [Hermes / Codex / Claude Code 对比](docs/hermes-vs-codex-claude.md)
- [HermesHarness.ipynb](HermesHarness.ipynb)
- [源码级系统流程图](docs/system-maps/README.md)

## 源码级交互流程图

这些图由 Archify 生成，节点带源码路径/行号和 GitHub 链接，适合对照 `events.jsonl` 阅读。

- [Mini Codex：run_turn 工具循环](docs/system-maps/mini-codex.html)
- [Claude-style：LangGraph queryLoop](docs/system-maps/claude-harness.html)
- [Hermes mini：记忆、技能与后台复盘](docs/system-maps/hermes-harness.html)
- [Support Project：五框架对照](docs/system-maps/support-project.html)
- [图的说明与实时事件映射](docs/system-maps/README.md)

静态图之外，运行案例后可以启动实时逐步高亮页面：

```powershell
uv run python docs/system-maps/live_viewer.py --system hermes_harness `
  --workspace $env:TEMP/hermes_harness_demo --open
```


![实时逐步可视化](docs/system-maps/live-viewer-preview.png)
## Runtime Extensions

- [插件、审批、MCP、多 Agent 与统一入口](docs/runtime-extensions.md)
- `main_mini.py`：三套 mini 的交互式统一入口，自动启动实时 Viewer

## Jupyter Notebooks

在 IDE 中打开 Notebook，并选择能够读取项目 `.venv` 的 Python 内核。

本机已经注册了名为 `Python (agent测试)` 的 Jupyter kernel；如果换了机器，可执行：

```powershell
uv run python -m ipykernel install --user --name agent-test --display-name "Python (agent测试)"
```

| Notebook | 内容 |
|---|---|
| [HermesHarness.ipynb](HermesHarness.ipynb) | Hermes 记忆/Skills/会话检索/后台复盘/通用任务闭环 |
| [LangChain测试.ipynb](LangChain测试.ipynb) | 15 个 LangChain 核心能力 + 小项目接入 |
| [LangGraph测试.ipynb](LangGraph测试.ipynb) | StateGraph、条件路由、interrupt/HITL、状态历史、时间旅行、fork、Mermaid 可视化 |
| [CrewAI测试.ipynb](CrewAI测试.ipynb) | Agent/Task/Crew、Flow、@router 条件分支、三角色项目 |
| [Llamalnd测试.ipynb](Llamalnd测试.ipynb) | 索引、QueryEngine、source_nodes 引用、QueryEngineTool、FunctionAgent |
| [OpenAiAgentsSDK测试.ipynb](OpenAiAgentsSDK测试.ipynb) | Runner、function_tool、handoff、guardrail、RunResult 可观测性 |
| [框架对比.ipynb](框架对比.ipynb) | 同一业务运行 5 个框架并比较结果 |
| [MiniCodexHarness.ipynb](MiniCodexHarness.ipynb) | Mini Codex 的阶段、工具、事件时间线和完整开发任务 |
| [ClaudeHarness.ipynb](ClaudeHarness.ipynb) | Claude-style queryLoop、CLAUDE.md、权限、多 Agent、MCP 和完整开发任务 |
| [MultiAgentPatterns.ipynb](MultiAgentPatterns.ipynb) | Codex/Claude 两种 mailbox、SendMessage/TaskOutput、spawn/wait 对比 |

Notebook 里的示例都对应 `support_project/adapters/` 下的可运行代码，不是孤立片段。

## 配置

项目根目录的 `.env` 已配置好当前百炼网关。关键字段：

```dotenv
BAILIAN_API_KEY=sk-...
BAILIAN_BASE_URL=https://llm-i9yh569m2mtagoyf.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_CHAT_MODEL=deepseek-v4.1-flash
BAILIAN_EMBEDDING_MODEL=
```

- `.env` 已加入 `.gitignore`，不要把真实 Key 提交到仓库。
- 换模型只需修改 `BAILIAN_CHAT_MODEL`。
- 当前 Key 调用 embedding 接口返回 `403`，所以两套 RAG 示例都使用本地哈希向量，保证开箱即跑；开通权限后 LangChain 案例可切换 `OpenAIEmbeddings`，LlamaIndex 可替换成真实 `BaseEmbedding`。

## 项目结构

```text
.
├── main.py                         # LangChain 15 案例入口
├── main_mini.py                    # 三套 mini 的统一交互入口
├── LangChain测试.ipynb
├── LangGraph测试.ipynb
├── CrewAI测试.ipynb
├── Llamalnd测试.ipynb              # LlamaIndex
├── OpenAiAgentsSDK测试.ipynb
├── 框架对比.ipynb
├── MiniCodexHarness.ipynb
├── ClaudeHarness.ipynb
├── HermesHarness.ipynb
├── MultiAgentPatterns.ipynb
├── langchain_cases/                # LangChain 15 个独立案例
├── support_project/                # 五框架售后工单小项目
│   ├── domain.py                   # 订单、退款、政策（框架无关）
│   ├── local_embedding.py          # 本地哈希向量
│   ├── runner.py                   # 统一运行与对比
│   └── adapters/
│       ├── langchain_adapter.py
│       ├── langgraph_adapter.py
│       ├── crewai_adapter.py
│       ├── llamaindex_adapter.py
│       └── openai_agents_adapter.py
├── mini_codex/                     # LangChain 版 Codex Harness
│   ├── context.py                  # AGENTS.md / 环境 / 上下文压缩
│   ├── tools.py                    # 开发工具与命令边界
│   ├── events.py                   # 事件流与 timeline.md
│   ├── multi_agent.py              # spawn/send_input/wait_agent
│   ├── mcp_client.py               # MCP 工具桥接
│   └── harness.py                  # bootstrap/context/plan/agent/verify/finalize
├── claude_harness/                 # LangGraph 版 Claude Code-style Harness
│   ├── context.py                  # CLAUDE.md / session memory / compact
│   ├── permissions.py              # permission modes
│   ├── tools.py                    # Read/Edit/Bash/TodoWrite
│   ├── multi_agent.py              # Task/SendMessage/TaskOutput
│   ├── mcp_server.py               # 本地只读 MCP server
│   └── harness.py                  # LangGraph queryLoop
├── hermes_harness/                 # 通用 Agent + 记忆/技能/复盘 Harness
│   ├── memory.py                   # MEMORY.md / USER.md 有界记忆
│   ├── skills.py                   # SKILL.md / usage / curator
│   ├── sessions.py                 # SQLite FTS5 会话检索
│   ├── toolsets.py                 # toolset 裁剪
│   ├── review.py                   # background review
│   ├── tools.py                    # memory/skills/session/file/terminal
│   └── harness.py                  # prepare/model/tools/finalize
├── agent_runtime/                  # 两套 Harness 共用的 mailbox runtime
├── examples/
│   ├── mini_codex_demo/            # 可修复的最小 Python 项目
│   ├── claude_harness_demo/        # 带 CLAUDE.md 的最小 Python 项目
│   └── hermes_harness_demo/       # 通用任务与学习闭环演示
├── data/
│   ├── langchain_guide.md          # LangChain RAG 示例数据
│   └── support_policy.md           # 售后小项目政策库
├── docs/beginner-guide.md          # 小白学习路线与运行指南
├── docs/runtime-extensions.md      # 插件/审批/MCP/多 Agent
├── docs/framework-selection.md     # 五框架选型指南
├── docs/framework-feature-map.md   # 特色能力与案例位置索引
├── docs/mini-codex-architecture.md # Codex Harness 对照与实现说明
├── docs/claude-harness-architecture.md # Claude Code-style 实现说明
├── docs/multi-agent-communication.md   # 多 Agent 通信细节
├── docs/agent-systems-glossary.md      # Agent 名词表
├── docs/claude-vs-codex.md              # Claude/GPT 与 Harness 异同
├── docs/hermes-harness-architecture.md # Hermes mini 源码对照
├── docs/hermes-vs-codex-claude.md       # 通用 Agent 与开发 Agent 对比
├── docs/system-maps/                    # Archify 源码级交互流程图
├── tests/
├── .env
├── .env.example
└── pyproject.toml
```

## LangChain 15 个案例

| 编号 | 主题 | 覆盖内容 |
|---|---|---|
| 01 | 模型、消息与 LCEL | ChatOpenAI、消息类型、PromptTemplate、`prompt \| model \| parser` |
| 02 | 结构化输出 | Pydantic Schema、`with_structured_output` |
| 03 | 工具与 Agent | `@tool`、`create_agent` 工具循环 |
| 04 | 短期记忆 | `InMemorySaver`、`thread_id` |
| 05 | RAG | 文档切分、向量检索、检索工具 |
| 06 | 流式输出 | `model.stream()`、Agent 步骤流 |
| 07 | 中间件 | `before_model` / `after_model`、模型调用上限 |
| 08 | 人机协同 | HumanInTheLoopMiddleware、interrupt、resume |
| 09 | 多 Agent | 子 Agent 包装成工具 |
| 10 | MCP | 本地 FastMCP Server、MCP 工具发现 |
| 11 | LangGraph | StateGraph、条件路由 |
| 12 | 安全护栏 | 内容过滤、PII 脱敏 |
| 13 | 可观测性 | Callback 事件追踪 |
| 14 | 长期记忆 | InMemoryStore、ToolRuntime |
| 15 | SQL Agent | SQLite 只读查询 |

运行：`uv run python main.py <编号>`
完整菜单：`uv run python main.py --list`

## 实现边界与版本取舍

- 这些示例覆盖“核心能力 + 常见 Agent 场景”，不是把官网所有集成页逐条翻译。
- 百炼网关支持工具调用和流式输出，但不支持 OpenAI 的 `json_schema` 响应格式，因此 LangChain 结构化输出使用 `function_calling`。
- 当前 Key 无 embedding 权限，两套 RAG 都使用本地哈希向量；它不是语义 embedding，生产环境应替换。
- CrewAI 依赖 `mcp<2`，而 LangChain 最新 `langchain.mcp` beta 适配器依赖 `fastmcp>=4`，两者不能共存。项目统一使用兼容的 `langchain-mcp-adapters + fastmcp 2.x`。
- 为了满足 CrewAI 的依赖约束，项目锁定 `pydantic<2.13`、`rich<15` 和 `openai<3`。
- HITL / 审批示例为了无人值守演示会自动批准；真实业务必须交给人工。
- Mini Codex 是教学用简化 Harness：用路径限制和命令白名单/黑名单代替 Codex 的 OS sandbox，不包含 MCP、图片、多 Agent、插件和 app-server。
- Claude-style Harness 是教学用简化实现：不复制 Claude Code 的 Ink UI、完整 hooks 协议、OS sandbox、远程 Agent、任务 DAG 和真正 Claude API；当前使用百炼 DeepSeek 驱动。
- 耗时对比包含网络波动，不是严格 benchmark。

## 安全提醒

- 不要提交 `.env`，不要把 API Key 打印到日志或前端。
- 工具权限必须在 Python/后端实现，不能只靠提示词约束。
- SQL Agent 必须使用只读账号、白名单表、超时和行数限制。
- 长期记忆的 namespace/key 必须由服务端根据登录身份生成。
- 生产环境应把 InMemorySaver/InMemoryStore 换成持久化后端，并接入真实审计。


