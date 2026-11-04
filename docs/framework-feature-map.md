# 五框架“特色能力”实现索引

这份文档回答三个问题：

1. 每个框架真正有辨识度的能力是什么？
2. 这些能力在代码/Notebook 里怎么做？
3. 有没有可运行案例，在哪里？

## 覆盖状态总表

| 框架 | 特色能力 | 是否已加案例 | 位置 |
|---|---|---|---|
| LangChain | Tool、Middleware、Memory、Streaming、Structured output、Callback | 已覆盖 | `LangChain测试.ipynb`、`langchain_cases/` |
| LangGraph | StateGraph、Checkpoint、状态历史、时间旅行、Fork、Interrupt、Mermaid 可视化 | 已覆盖 | `LangGraph测试.ipynb` §1–§4、`support_project/adapters/langgraph_adapter.py` |
| CrewAI | Agent/Task/Crew、Task context、Flow、`@router`、Async kickoff | 已覆盖 | `CrewAI测试.ipynb` §1–§3、`support_project/adapters/crewai_adapter.py` |
| LlamaIndex | Index、QueryEngine、`source_nodes` 引用、QueryEngineTool、FunctionAgent | 已覆盖 | `Llamalnd测试.ipynb` §1–§2、`support_project/adapters/llamaindex_adapter.py` |
| OpenAI Agents SDK | `function_tool`、Handoff、Input Guardrail、RunResult、Tracing 配置 | 已覆盖 | `OpenAiAgentsSDK测试.ipynb` §1–§4、`support_project/adapters/openai_agents_adapter.py` |

---

## LangGraph：每一步为什么能恢复、能回看？

### 原理

LangGraph 的图在每次 super-step 之后，通过 checkpointer 保存一个状态快照：

- `thread_id` 定位一条会话/流程；
- `checkpoint_id` 定位某一步；
- `StateSnapshot` 包含 `values`、`next`、`metadata.step`、`tasks`、`interrupts`；
- `get_state(config)` 看当前最新状态；
- `get_state_history(config)` 看整条历史（新 → 旧）；
- 用历史 snapshot 的 `config` 再 `invoke(None, config)` 就是从那个 checkpoint 重放；
- `update_state()` 可以基于旧 checkpoint 创建 fork；
- `get_graph().draw_mermaid()` 输出拓扑图。

### 重要限制

- **Replay 不是读缓存**：checkpoint 之后的节点会重新执行，LLM/API 会再次调用。
- `InMemorySaver` 只保存在当前进程；生产要换 Postgres/Mongo/Redis 等持久化 checkpointer。
- `interrupt()` 恢复时也会重新进入对应节点，恢复值通过 `Command(resume=...)` 传入。

### 对应案例

`LangGraph测试.ipynb`：

- §1：最小 StateGraph；
- §2：售后流程；
- §3：原生 `interrupt()` / `Command(resume=...)`；
- §4：`get_state_history`、replay、fork、Mermaid。

运行项目版本：

```powershell
uv run python -m support_project.runner --framework langgraph --full
```

---

## CrewAI：角色团队怎么协作？

### 原理

- `Agent`：角色、目标、背景、工具；
- `Task`：任务描述、期望输出、上下文依赖；
- `Crew`：把角色和任务组织成 sequential/hierarchical 流程；
- `Flow`：以状态和事件为中心，比 Crew 更适合生产流程；
- `@start` / `@listen` / `@router`：Flow 的启动、监听、条件路由；
- `context=[task1, task2]`：把前序任务结果传给后续任务；
- Jupyter 中应使用 `await crew.kickoff_async()` / `await flow.kickoff_async()`，不要在有事件循环的单元格里调同步 `kickoff()`。

### 对应案例

`CrewAI测试.ipynb`：

- §1：Agent/Task/Crew 最小团队；
- §2：Flow 状态；
- §2.1：`@router` 金额分流；
- §3：订单分析员 → 政策审核员 → 客服写作专员。

项目版本：`support_project/adapters/crewai_adapter.py`

---

## LlamaIndex：RAG 的“可解释性”在哪里？

### 原理

- `Document`：原始文档；
- `VectorStoreIndex`：建立向量索引；
- `QueryEngine`：检索 + 合成答案；
- `Response.source_nodes`：保留命中节点、metadata 和 score；
- `QueryEngineTool`：把整个 QueryEngine 包装成 Agent 工具；
- `FunctionAgent`：基于工具调用的 Agent。

### 对应案例

`Llamalnd测试.ipynb`：

- §1：政策文档建索引并查询；
- §1.1：打印 `source_nodes` 的来源与相似度；
- §2：QueryEngineTool + FunctionAgent。

项目版本：`support_project/adapters/llamaindex_adapter.py`

当前 API Key 没有 Embedding 权限，案例使用本地哈希向量；生产环境应替换成真正的 `BaseEmbedding`。

---

## OpenAI Agents SDK：Handoff、Guardrail、RunResult

### 原理

- `Agent`：角色和指令；
- `Runner.run()`：异步执行循环；
- `function_tool`：Python 函数 → 工具 Schema；
- `handoffs=[...]`：把会话交给专家 Agent；
- `input_guardrails=[...]`：模型调用前检查，`tripwire_triggered=True` 时中断；
- `RunResult`：`last_agent`、`new_items`、`raw_responses`、`to_input_list()`；
- `set_tracing_disabled(True)`：自定义 OpenAI 兼容网关没有 OpenAI 平台 tracing 时关闭上报。

### 对应案例

`OpenAiAgentsSDK测试.ipynb`：

- §1：function_tool + Runner；
- §2：Triage → Refund Specialist handoff；
- §3：密码输入 Guardrail；
- §4：RunResult 可观测性。

项目版本：`support_project/adapters/openai_agents_adapter.py`

---

## LangChain：通用能力如何覆盖？

LangChain 的 15 个案例已经分别覆盖：

- 模型、消息、LCEL；
- Pydantic 结构化输出；
- `@tool` + `create_agent`；
- `InMemorySaver + thread_id`；
- RAG；
- 流式输出；
- Middleware；
- HITL；
- 多 Agent；
- MCP；
- LangGraph 基础；
- 内容护栏/PII；
- Callback；
- 长期记忆；
- SQL Agent。

入口：`LangChain测试.ipynb` 或 `uv run python main.py --list`。

---

## 一句话选型

- **要“知道每一步发生了什么、能回放/分叉”** → LangGraph；
- **要“多个角色分工完成一份报告/审核”** → CrewAI；
- **要“文档知识库检索并给出依据”** → LlamaIndex；
- **要“一个助手调用很多业务工具”** → LangChain；
- **要“前台分流、专家接管、输入护栏”** → OpenAI Agents SDK。
