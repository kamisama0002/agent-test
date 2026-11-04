# 五套 Agent 框架选型指南

> 这里比较的是项目根目录中 5 个 Notebook 对应的 5 套框架，不是 Jupyter 的 5 种内核。
> 小项目统一使用“订单 A1001 耳机故障退款”这个售后场景，保证比较的是框架差异，而不是业务差异。

## 一张表先看结论

| 框架 | 核心抽象 | 最强能力 | 主要代价 | 最适合 |
|---|---|---|---|---|
| LangChain | Model / Message / Tool / Agent / Middleware | 工具调用型 Agent、模型与集成生态 | 复杂流程仍要下沉 LangGraph | 一个助手调用多个 API、快速做通用 Agent |
| LangGraph | StateGraph / Node / Edge / Checkpointer | 显式状态、条件分支、持久化、HITL、可恢复执行 | 需要自己设计状态和拓扑，代码更“工程化” | 审批流、长流程、需要审计/暂停/重试的业务 |
| CrewAI | Agent / Task / Crew / Flow | 角色分工、任务委派、多 Agent 协作 | 默认控制流较“自治”，精细控制不如 LangGraph | 研究、分析、写作、审核等内容型团队 |
| LlamaIndex | Document / Index / QueryEngine / Workflow | 数据接入、索引、RAG、查询引擎、引用 | 通用 Agent 生态不如 LangChain 广 | 企业知识库、文档问答、PDF/网页检索 |
| OpenAI Agents SDK | Agent / Runner / Handoff / Guardrail | 轻量运行时、Handoff、Guardrails、Tracing | 与 OpenAI 生态绑定更深，部分能力依赖 Responses API | OpenAI 原生应用、分流/专家接管、快速上线 |

## 按问题选，不按名气选

### 1. 核心问题是“把文档变成可查询知识库” → LlamaIndex

优先级最高。LlamaIndex 的强项不是再发明一个通用 Agent，而是把：

- 文档加载；
- 节点切分；
- Embedding；
- 索引/向量库；
- Retriever；
- QueryEngine；
- 引用和响应合成；

串成一条数据管线。它适合“企业制度问答、产品手册、合同检索、论文库、客服知识库”。

在本项目中：

- `support_project/adapters/llamaindex_adapter.py`
- `Llamalnd测试.ipynb`
- 使用 `VectorStoreIndex + QueryEngineTool + FunctionAgent`

**什么时候不选：** 如果主要工作是调用十几个业务 API，而不是查文档，LlamaIndex 的 RAG 优势就用不上。

### 2. 核心问题是“流程必须按固定步骤走、可暂停、可恢复” → LangGraph

LangGraph 把应用写成状态图：

- Node 负责一步工作；
- Edge 决定下一步；
- State 在节点间传递；
- Checkpointer 保存每个 thread 的快照；
- Interrupt 支持人工审批和恢复。

它适合退款审批、订单风控、长任务、需要失败重试或人工介入的业务。
它不强迫你使用某个 Agent 框架，甚至可以在节点里调用 LangChain、LlamaIndex 或其他服务。

在本项目中：

- `support_project/adapters/langgraph_adapter.py`
- `LangGraph测试.ipynb`
- 节点顺序：`extract → lookup → policy → refund → LLM compose`

**什么时候不选：** 如果只是“模型调用几个工具直到完成”，直接 `create_agent` 更省代码。

### 3. 核心问题是“多个角色协作产出内容” → CrewAI

CrewAI 让你用角色、目标、背景故事和任务来组织团队：

- 谁负责查数据；
- 谁负责审核；
- 谁负责写最终回复；
- 任务之间通过 `context` 传递结果。

它特别适合研究简报、竞品分析、内容生产、报告生成、带有明确角色的审核链。
CrewAI 也有 `Flow`，可以用 `@start / @listen / @router` 写更生产化的状态流程；但如果你一开始就需要非常精细的图控制，LangGraph 更直接。

在本项目中：

- `support_project/adapters/crewai_adapter.py`
- `CrewAI测试.ipynb`
- 三个角色：订单分析员 → 政策审核员 → 客服写作专员

**什么时候不选：** 单 Agent 就能完成、且不需要角色分工时，CrewAI 会增加 Token 和调试成本。

### 4. 核心问题是“一个助手 + 很多工具/集成” → LangChain

LangChain 的强项是组件和生态：

- 统一的模型接口；
- 消息类型；
- Tool 抽象；
- `create_agent` 工具循环；
- Middleware；
- 结构化输出、流式、记忆、回调；
- 大量模型/向量库/工具集成。

它适合“客服助手、订单助手、运维助手、个人助理”这类标准工具型 Agent。

在本项目中：

- `support_project/adapters/langchain_adapter.py`
- `LangChain测试.ipynb`
- 单 Agent + `lookup_order / calculate_refund / search_policy` 三个工具

**什么时候不选：** 当流程本身是核心复杂度（分支、审批、并行、恢复）时，不要把所有逻辑塞进一个 Agent 提示词，应该用 LangGraph。

### 5. 核心问题是“OpenAI 生态内的分流、专家接管、护栏和追踪” → OpenAI Agents SDK

OpenAI Agents SDK 的重点非常明确：

- `Agent` 定义角色；
- `Runner` 执行循环；
- `function_tool` 暴露业务函数；
- `handoff` 把会话交给专家 Agent；
- `input_guardrail / output_guardrail` 做安全检查；
- 内置 tracing（当前自定义网关下应关闭或接自己的 tracing）。

它适合“前台分诊 + 专家接管”的客服/助手，也适合希望用较少代码快速搭 Agent 的团队。

在本项目中：

- `support_project/adapters/openai_agents_adapter.py`
- `OpenAiAgentsSDK测试.ipynb`
- `Triage Agent → Refund Specialist / General Support`

**什么时候不选：** 需要大量非 OpenAI 集成、复杂图编排、或者完全不想依赖 OpenAI SDK 抽象时，LangChain/LangGraph 更灵活。

## 决策树

```text
问题主要是“查文档、做知识库”吗？
├─ 是 → LlamaIndex
└─ 否
   └─ 流程必须严格可控、可暂停、可恢复吗？
      ├─ 是 → LangGraph
      └─ 否
         └─ 需要多个角色分工产出内容吗？
            ├─ 是 → CrewAI
            └─ 否
               └─ 是标准“一个助手 + 多个工具”吗？
                  ├─ 是 → LangChain
                  └─ 否 → 需要 OpenAI 生态的 handoff/guardrails 吗？
                     ├─ 是 → OpenAI Agents SDK
                     └─ 否 → 从 LangChain 或直接 SDK 开始
```

## 它们不是互斥的

实际项目里最常见的组合是：

1. **LlamaIndex 负责检索，LangGraph 负责流程**
   - 把 LlamaIndex QueryEngine 包成 LangGraph 节点；
   - 流程、审批、重试由 LangGraph 控制。

2. **LangChain 提供工具和模型适配，LangGraph 负责编排**
   - LangGraph 节点里调用 LangChain 的 Tool/Chain；
   - 这是 LangChain 官方推荐的进阶路径。

3. **CrewAI 负责研究/写作，LangGraph 负责生产流程**
   - CrewAI 产出报告或分析结果；
   - LangGraph 决定何时启动 Crew、如何审批和归档。

4. **OpenAI Agents SDK 负责前台分流，业务系统负责执行**
   - Triage Agent 只做意图识别和 handoff；
   - 退款、订单、风控在确定性的后端服务里完成。

## 本项目如何保证“基本跑通”

- 所有框架共享 `support_project/domain.py` 的订单、退款和政策逻辑；
- Agent 只负责理解、调用工具和组织语言，关键金额计算仍是确定性 Python；
- 当前百炼网关使用 OpenAI Chat Completions 兼容协议；
- LlamaIndex 使用 `OpenAILike`；
- CrewAI 使用 `openai/<model>` + `base_url`；
- OpenAI Agents SDK 使用 `OpenAIChatCompletionsModel`；
- 当前账号无 Embedding 权限，LlamaIndex 使用本地哈希向量，生产环境应换成真实 Embedding；
- CrewAI 与 `langchain.mcp` beta 存在 MCP 版本冲突，因此项目统一使用兼容的 `langchain-mcp-adapters + fastmcp 2.x`。

## 官方文档

- LangChain: https://docs.langchain.com/oss/python/langchain/overview
- LangGraph: https://docs.langchain.com/oss/python/langgraph/overview
- CrewAI: https://docs.crewai.com/
- LlamaIndex: https://developers.llamaindex.ai/python/framework/
- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
