# LangChain 学习笔记

## LangChain 是什么

LangChain 是用于构建大模型应用的开发框架。它把模型、消息、工具、检索和运行时抽象成可组合组件。
LangChain 1.x 的核心入口是 `create_agent`，适合快速搭建可定制的 Agent harness。
Agent 可以理解为“模型 + 提示词 + 工具 + 中间件 + 循环”。

## create_agent 适合什么场景

`create_agent` 提供最小但可配置的 Agent 构造器。开发者可以传入模型、工具、system prompt、
middleware、结构化输出 Schema 和 checkpointer。它适合绝大多数常见的工具调用型 Agent，
例如客服问答、订单查询、数据分析助手和 RAG 问答。

它的优势是开发成本低、与 LangChain 生态集成直接、支持流式输出、工具调用和中间件。
如果业务只是“模型调用若干工具直到任务完成”，通常优先从 `create_agent` 开始。

## LangGraph 适合什么场景

LangChain 的 Agent 构建在 LangGraph 之上。LangGraph 是更低层的编排框架，
用 StateGraph 描述节点、边、条件路由和状态更新。
当业务流程需要确定性步骤、复杂分支、并行 fan-out、子图、时间旅行、
细粒度持久化或人在环路控制时，使用 LangGraph 更合适。

简单判断：常规 Agent 循环先用 `create_agent`；当“流程拓扑本身”成为核心复杂度时，
再下沉到 LangGraph。

## Middleware 中间件

Middleware 在 Agent 循环的模型调用和工具调用前后插入钩子，
可以实现日志、重试、回退、摘要、PII 检测、模型调用上限、人机审批等能力。
内置中间件包括 SummarizationMiddleware、HumanInTheLoopMiddleware、
ModelCallLimitMiddleware、PIIMiddleware 和 ToolRetryMiddleware。

## RAG 检索增强生成

RAG 的步骤包括：加载文档、切分、向量化、存入向量库、根据问题检索相关片段、
把片段作为上下文交给模型生成答案。RAG 能缓解模型知识过时和私有数据不可见的问题，
但仍需评估检索召回率、答案忠实度和引用准确性。

## Memory 记忆

短期记忆通过 checkpointer 和 thread_id 保存单次会话状态。
长期记忆通过 LangGraph Store 按 namespace 和 key 保存跨线程数据，
例如用户偏好、历史事实和业务画像。
