# Hermes mini：源码对照与架构说明

本文对应当前目录的 `hermes_harness/`。参考源码是本地安装的
**Hermes Agent v0.22.6**，commit `f0d94882e8`，不是把 Hermes 全量复制进项目。

## 1. Hermes 到底复刻了哪几层

完整的 Hermes 包含桌面端、消息网关、浏览器、语音、远程 sandbox、cron、外部
memory provider 等大量能力。本学习项目只复刻“通用 Agent 自主学习闭环”：

```text
SOUL.md 身份
  + MEMORY.md / USER.md 声明性长期记忆
  + skills/SKILL.md 程序性长期记忆
  + SQLite FTS5 session_search
  + toolset 裁剪
  + background review
```

主循环：

```text
prepare
  → model
  → tools（有 tool_calls）
  → model ...（直到无 tool_calls）
  → finalize
  → background_review
```

源码入口：`hermes_harness/harness.py:156` 的 `HermesHarness.run()`；
节点分别在 `prepare_node`、`model_node`、`tools_node`、`finalize_node`
（`hermes_harness/harness.py:188-279`）。

## 2. 和真实 Hermes 源码的映射

| 真实 Hermes 源码 | 作用 | 本项目的对应 |
|---|---|---|
| `run_agent.py::AIAgent` | 组合会话、工具、压缩、记忆等运行时 | `HermesHarness` |
| `agent/conversation_loop.py::_run_conversation_turn` | 过程式 turn loop | LangGraph 节点 `model/tools` |
| `agent/background_review.py` | turn 后独立 fork 复盘 | `hermes_harness/review.py` |
| `tools/memory_tool_store.py` | `MEMORY.md` / `USER.md` 有界存储 | `hermes_harness/memory.py` |
| `agent/memory_context.py` | memory-context 围栏 | `MemoryStore.context_block()` |
| `tools/skills_tool.py` | 技能索引与 `skill_view` | `hermes_harness/skills.py` |
| `tools/skill_manager_tool.py` | `skill_manage` 写入、read-before-write | `SkillStore` + `skill_manage` 工具 |
| `agent/curator.py` | stale / archive 生命周期 | `SkillStore.curate()` |
| `hermes_state_fts.py` | SQLite FTS5 与 CJK bigram | `hermes_harness/sessions.py` |
| `toolsets.py` | 按场景裁剪工具面 | `hermes_harness/toolsets.py` |

真实 Hermes 的 `AIAgent` 不使用 LangGraph；它主要是显式过程式循环。本项目为了让
学习者看清“每一步是什么”，用 LangGraph 把 `prepare/model/tools/finalize`
拆成节点。不要把 LangGraph 节点误认为 Hermes 原源码的一部分。

## 3. MEMORY.md / USER.md

路径：

```text
<workspace>/.hermes/
├── memories/MEMORY.md
└── memories/USER.md
```

保留的关键约束：

- 条目分隔符是 `"\n§\n"`；
- `MEMORY.md` 默认 2200 字符，`USER.md` 默认 1375 字符；
- `add` 幂等，重复内容不会重复写；
- `patch` / `remove` 的 `old_text` 必须唯一匹配；
- 批量操作先完整校验，再一次性原子落盘；
- 记忆注入使用 `<memory-context>` 围栏，并写明“不是新用户输入”；
- 文件写入使用临时文件 + `os.replace`。

简化点：没有实现 Hermes 的跨进程文件锁、完整 threat scan、外部 memory provider
和 memory write mirror。它们属于生产可靠性，不影响学习主链路。

## 4. Skills 自动整理

目录结构：

```text
.hermes/skills/
├── .usage.json
├── .archive/
└── [category/]<skill-name>/
    ├── SKILL.md
    ├── references/
    ├── templates/
    ├── scripts/
    └── assets/
```

渐进披露：

1. `skills_list` 只返回 `name / description / category`；
2. 模型需要细节时才调用 `skill_view`；
3. `skill_manage(action=create|patch|add_file|remove_file)` 写入技能；
4. 修改已有技能前必须先 `skill_view`，避免用旧 transcript 覆盖新文件。

`description` 在新建/修改时限制为 60 字符。`usage.json` 记录：

```json
{
  "use_count": 1,
  "view_count": 2,
  "patch_count": 1,
  "last_used_at": "...",
  "state": "active",
  "pinned": false
}
```

Curator 的两层设计：

- **确定性生命周期**：14 天未使用标 `stale`，30 天归档；
- 只处理 `created_by: agent` 的技能；
- pinned 技能跳过；
- 永不删除，只移动到 `.archive/`；
- LLM 合并/去重是完整 Hermes 的可选高级能力，本 mini 版未实现。

## 5. Background review

真实 Hermes 在用户回复交付后，fork 一个独立 Agent，重放对话快照并询问是否需要
保存记忆或技能。它只开放 `skills_list`、`skill_view`、`skill_manage`、
`memory`、`read_file`、`search_files` 等白名单工具，不允许后台改 workspace。

本项目的 `BackgroundReview.run()`：

```text
主 turn 完成
  → 构造 review system prompt
  → 注入当前 MEMORY/USER/Skills 与对话快照
  → 独立模型绑定 memory/skill 工具
  → 执行工具
  → 返回 ReviewResult
  → 失败只记录 error，不覆盖主答案
```

源码：`hermes_harness/review.py:76-136`。

学习重点不是“让模型自己决定记什么”，而是给自动学习加边界：

- 只保存有对话证据的事实；
- 用户偏好和 Agent 环境事实分开；
- 技能是类级别流程，不是一次事故日志；
- 未解决的失败不写成可靠流程；
- 复盘失败不能阻塞主任务。

## 6. session_search

`SessionStore` 创建：

```sql
CREATE TABLE sessions (...);
CREATE TABLE messages (...);
CREATE VIRTUAL TABLE messages_fts USING fts5(
    message_id UNINDEXED,
    content,
    search_text,
    tokenize='unicode61'
);
```

中文处理：

```text
长期记忆 → 长期 / 期记 / 记忆
```

写入 FTS 时额外保存 CJK bigram 文本，查询时使用同样 token。没有 FTS5 的环境
会退化为 `LIKE`，项目仍可运行。源码见 `hermes_harness/sessions.py`。

## 7. Toolset

`hermes_harness/toolsets.py` 当前提供：

- `file`：read/write/patch/search
- `terminal`：受限命令
- `memory`
- `skills`
- `session_search`
- `todo`
- `research`：只读 + 记忆/技能/历史
- `safe`：只读 + 记忆
- `coding`：文件 + 命令 + 记忆 + 技能
- `hermes`：通用默认组合

模型只看到被 toolset 选中的工具。这和把全部工具一次性塞给模型不同，也是 Hermes
面向多种使用场景的基础。

## 8. 明确没有复刻的部分

- Telegram/Discord/Slack/WhatsApp/Signal 多平台 gateway；
- 桌面端、TUI、Web dashboard；
- 浏览器、视觉、图像/视频、TTS/ASR；
- Docker/SSH/Modal/Daytona/Vercel 远程 terminal backend；
- Honcho 等外部 memory provider；
- cron 调度器、完整 delegate_task 生命周期；
- 完整 curator LLM 合并、回滚与并发锁；
- Hermes 的真实 provider/credential 体系。

这些能力很大，且有平台和部署依赖；学习版优先把“记忆 → 技能 → 复盘 → 复用”
闭环做通，而不是复制文件数量。
