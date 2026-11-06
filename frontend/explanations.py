"""把 Harness 事件翻译成适合学习页面展示的分步说明。

这个模块不调用模型，也不读环境变量。所有解释都来自事件本身和
确定性的规则表，保证离线测试稳定、页面响应快速。
"""

from __future__ import annotations

import json


STAGE_LABELS = {
    "bootstrap": "启动与装载",
    "context": "上下文构建",
    "prepare": "上下文准备",
    "plan": "规划",
    "agent": "Agent 主循环",
    "model": "模型采样",
    "tools": "工具执行",
    "compact": "上下文压缩",
    "verify": "验证",
    "finalize": "收尾",
    "review": "后台复盘",
    "plugins": "插件装载",
    "subagent": "子 Agent",
    "harness": "Harness 错误处理",
}

EVENT_GUIDES: dict[str, dict[str, str]] = {
    "run_started": {
        "title": "启动一次运行",
        "why": "先固定任务、workspace 和运行目录，后续所有事件才有统一的归属。",
        "next": "检查工作区是否可用，然后装载仓库规则。",
    },
    "workspace_ready": {
        "title": "工作区校验完成",
        "why": "文件工具和命令工具都必须被限制在一个明确的工作目录内。",
        "next": "进入上下文构建阶段。",
    },
    "toolsets_resolved": {
        "title": "解析 Toolset",
        "why": "Hermes 先根据配置决定本轮暴露哪些内置工具，再绑定给模型。",
        "next": "把工具 schema 和上下文一起交给模型。",
    },
    "context_built": {
        "title": "构建上下文",
        "why": "模型不知道仓库规则、当前目录和 token 预算，必须先把这些事实组装进请求。",
        "next": "生成计划，再把计划和上下文一起装配成模型消息。",
    },
    "context_prepared": {
        "title": "准备上下文",
        "why": "Claude/Hermes 风格 Harness 会先读取项目规则、会话记忆或长期记忆，再开始模型循环。",
        "next": "创建 Todo（Claude）或直接进入模型采样（Hermes）。",
    },
    "context_assembled": {
        "title": "装配模型消息",
        "why": "这一步把各个上下文分区真正拼成 SystemMessage / HumanMessage 列表，是模型实际看到的输入。",
        "next": "调用模型；模型可能回答，也可能返回工具调用。",
    },
    "plan_created": {
        "title": "生成执行计划",
        "why": "先把任务拆成可检查的步骤，避免模型直接跳到修改代码。",
        "next": "进入 Agent 循环，模型可以读取仓库或更新计划状态。",
    },
    "todo_created": {
        "title": "创建 Todo",
        "why": "Claude 风格 Harness 用 TodoWrite 维护任务状态，让探索、修改、验证都有明确进度。",
        "next": "把 Todo 追加到消息，然后开始模型采样。",
    },
    "plugin_loaded": {
        "title": "装载插件",
        "why": "插件通过显式 manifest 把额外工具注册进同一个 Tool 池。",
        "next": "将插件工具加入模型可调用的工具列表。",
    },
    "plugin_tools_loaded": {
        "title": "插件工具可用",
        "why": "只有成功注册并进入 Tool 池的工具，模型才可能调用。",
        "next": "继续装载 MCP / 多 Agent 工具，或开始模型采样。",
    },
    "mcp_tools_loaded": {
        "title": "MCP 工具可用",
        "why": "MCP 让 Harness 从外部 server 动态发现工具，而不是把工具硬编码在 Harness 中。",
        "next": "将 MCP 工具和内置工具一起绑定给模型。",
    },
    "multi_agent_tools_loaded": {
        "title": "多 Agent 工具可用",
        "why": "spawn/send/wait/close 等工具让主 Agent 能把独立探索任务交给隔离子 Agent。",
        "next": "模型可以决定是否委派子任务。",
    },
    "model_request": {
        "title": "请求模型采样",
        "why": "Harness 把当前消息、工具 schema 和上下文一起提交给模型；模型只负责决策，不直接操作文件。",
        "next": "解析模型返回：文本回答，或一个/多个 tool_calls。",
    },
    "agent_message": {
        "title": "模型输出文本",
        "why": "这是模型对本轮上下文的自然语言判断，可能是中间说明，也可能是最终回答。",
        "next": "如果没有工具调用就收尾；有工具调用则先执行工具。",
    },
    "token_usage": {
        "title": "记录 Token 用量",
        "why": "Token 统计帮助判断上下文是否接近预算，以及何时需要压缩。",
        "next": "继续工具循环或进入最终汇总。",
    },
    "tool_started": {
        "title": "开始执行工具",
        "why": "模型只提出 tool_call；真正读取文件、写文件或执行命令的是 Harness 注册的本地工具。",
        "next": "等待工具返回真实观察结果，并写入 ToolMessage。",
    },
    "tool_finished": {
        "title": "工具执行完成",
        "why": "工具结果必须回填给模型，模型才能基于真实输出继续下一步，而不是脑补结果。",
        "next": "把 ToolMessage 放回上下文，再次请求模型采样。",
    },
    "approval_decision": {
        "title": "审批决策",
        "why": "写入和执行类操作需要经过统一策略，防止模型绕过权限边界。",
        "next": "允许则执行工具；拒绝则把拒绝原因作为工具结果回填。",
    },
    "permission_decision": {
        "title": "权限决策",
        "why": "Claude 风格 Harness 在 tool_use 真正执行前检查 permission mode 和工具元数据。",
        "next": "允许则进入工具执行；拒绝则返回权限错误给模型。",
    },
    "hook_pre_tool": {
        "title": "工具前置 Hook",
        "why": "Hook 可以在工具执行前做审计、参数改写或额外校验。",
        "next": "使用 Hook 处理后的参数执行工具。",
    },
    "hook_post_tool": {
        "title": "工具后置 Hook",
        "why": "工具执行后可以统一记录日志、检查输出或触发额外动作。",
        "next": "将最终工具输出写回模型上下文。",
    },
    "context_compacted": {
        "title": "压缩上下文",
        "why": "上下文窗口有限，较早的工具结果或历史消息必须被清理或摘要，否则后续模型请求会超预算。",
        "next": "使用压缩后的消息继续模型采样。",
    },
    "verification_completed": {
        "title": "验证完成",
        "why": "代码修改后需要真实执行测试或检查，不能只相信模型的自我描述。",
        "next": "根据 returncode 判断成功或失败，并写入最终摘要。",
    },
    "verification_skipped": {
        "title": "跳过验证",
        "why": "当前配置没有提供 verify_command，因此 Harness 明确记录没有执行验证。",
        "next": "进入最终汇总，并在结果中说明验证未配置。",
    },
    "turn_completed": {
        "title": "本轮完成",
        "why": "模型不再返回工具调用，Harness 将当前 assistant 文本视为本轮最终回答。",
        "next": "进入 finalize，保存摘要并结束运行。",
    },
    "query_completed": {
        "title": "Query 完成",
        "why": "Claude 风格 queryLoop 已经得到最终 assistant message，并保存 session memory。",
        "next": "返回最终答案，结束本次运行。",
    },
    "run_completed": {
        "title": "运行收尾",
        "why": "汇总变更文件、验证状态和运行产物，便于复盘。",
        "next": "运行结束，事件流保留供逐步回放。",
    },
    "review_completed": {
        "title": "后台复盘完成",
        "why": "Hermes 在主答案之后用隔离上下文复盘，把可复用经验写入长期记忆或技能库。",
        "next": "下一次运行会在 prepare 阶段重新注入这些记忆和技能索引。",
    },
    "memory_changed": {
        "title": "更新长期记忆",
        "why": "Hermes 将稳定偏好或经验持久化，而不是只依赖当前会话消息。",
        "next": "后续会话可通过 MEMORY.md / USER.md 重新读取。",
    },
    "skill_viewed": {
        "title": "查看技能正文",
        "why": "Skills Index 只放摘要，模型需要时再读取具体技能，属于渐进披露。",
        "next": "把技能正文作为工具观察写回上下文。",
    },
    "skill_changed": {
        "title": "更新技能库",
        "why": "后台复盘可以把重复出现的经验整理成可复用技能。",
        "next": "下一次 prepare 会在 Skills Index 中看到新技能。",
    },
    "subagent_spawned": {
        "title": "启动子 Agent",
        "why": "主 Agent 把独立探索任务交给子 Agent，避免污染主上下文。",
        "next": "子 Agent 在自己的消息历史里运行工具循环。",
    },
    "subagent_completed": {
        "title": "子 Agent 完成",
        "why": "子 Agent 返回压缩后的结果，主 Agent 只需要消费结论。",
        "next": "主 Agent 把结果纳入决策，继续自己的循环。",
    },
    "subagent_failed": {
        "title": "子 Agent 失败",
        "why": "隔离子任务失败不应直接终止主 Agent；错误会作为观察返回。",
        "next": "主 Agent 决定重试、换方法或报告失败。",
    },
    "error": {
        "title": "运行错误",
        "why": "Harness 需要把异常转成可观察事件，避免静默失败。",
        "next": "根据错误位置决定中止、降级或继续运行。",
    },
    "warning": {
        "title": "降级警告",
        "why": "某个可选能力失败时，Harness 可能使用默认策略继续运行。",
        "next": "继续执行，但需要在最终结果中保留风险说明。",
    },
}


EVENT_GUIDES.update({
    "fault_injected": {
        "title": "故障演练注入",
        "why": "学习 Harness 不能只跑正常路径；主动注入可控故障，能验证重试、降级、断路器和错误回填是否真的生效。",
        "next": "观察 fault_injected 之后的 error、retry_scheduled、fallback_applied 或 failure_summary。",
    },
    "fallback_applied": {
        "title": "启用降级路径",
        "why": "某个可选组件或一次工具调用失败，但主任务仍有机会继续，因此不能把整个 Agent 直接终止。",
        "next": "带着降级说明继续运行；最终结果会保留失败原因。",
    },
    "failure_summary": {
        "title": "记录终止原因",
        "why": "有些失败不能安全恢复，例如模型连续失败或模型陷入重复工具调用；此时必须有明确的停止条件。",
        "next": "停止当前循环，把可诊断信息返回给上层或用户。",
    },
    "retry_scheduled": {
        "title": "安排重试",
        "why": "网络超时、限流等瞬时错误适合有限次重试；无限重试会让成本和延迟失控。",
        "next": "等待退避时间后再次调用同一模型或工具。",
    },
    "retry_succeeded": {
        "title": "重试成功",
        "why": "重试成功说明错误更可能是瞬时的，而不是上下文或代码本身有问题。",
        "next": "继续正常主循环。",
    },
    "limit_reached": {
        "title": "达到运行上限",
        "why": "Agent 循环必须有硬上限，否则模型可能无限调用工具或持续采样。",
        "next": "返回带原因的部分结果，并标记需要人工介入。",
    },
    "checkpoint_saved": {
        "title": "保存检查点",
        "why": "把阶段状态持久化后，进程中断可以从最近状态恢复，而不必重新执行所有工具。",
        "next": "发生异常或恢复时，从对应检查点继续。",
    },
    "reasoning_content": {
        "title": "记录模型推理内容",
        "why": "DeepSeek 的 reasoning 字段属于模型输出的一部分，但不应和最终答案混在一起；单独记录便于调试和展示。",
        "next": "继续读取 assistant 的正文和 tool_calls，进入正常路由。",
    },
})

EVENT_GUIDES.update({
    "turn/start": {"title": "Turn 开始", "why": "dsh 先打开一个 turn，再在 turn 内领取输入并执行一个或多个 step。", "next": "进入 step/start，派生模型消息并准备请求。"},
    "turn/end": {"title": "Turn 结束", "why": "turn/end 记录结束原因，使 completed、error、max-tokens 或 blocked 都能从日志还原。", "next": "进入 finalize 或返回错误结果。"},
    "step/start": {"title": "Step 开始", "why": "每个 step 对应一次模型请求及其请求产生的工具调用。", "next": "记录 user/message、request/header 并请求模型。"},
    "step/end": {"title": "Step 结束", "why": "step 边界让助手结果和工具结果在下一次请求前完成持久化。", "next": "若有工具结果则进入下一个 step，否则关闭 turn。"},
    "user/message": {"title": "模型可见用户消息", "why": "用户任务或压缩摘要都是 user/message surface 事件，模型历史从它们派生。", "next": "与 request/header、assistant/message 一起构成模型请求。"},
    "request/header": {"title": "记录请求头", "why": "provider、model、cwd 和 reasoning effort 必须在请求前写入会话日志，才能重建请求。", "next": "执行 session flush，然后调用模型。"},
    "agent/request": {"title": "发起模型请求", "why": "这是实时协调事件，记录本轮请求实际带上的消息和工具面。", "next": "等待模型流式返回 assistant 内容。"},
    "assistant/message": {"title": "记录助手消息", "why": "成功模型调用的正文、reasoning block、tool_calls 和 usage 作为一条 surface 事件持久化。", "next": "如果有 tool_calls，进入工具流水线；否则关闭 turn。"},
    "assistant/attempt": {"title": "记录失败尝试", "why": "失败或重试的模型 attempt 不进入模型可见历史，但仍要留下可诊断的持久记录。", "next": "根据重试策略重跑同一 step，或让 turn 以 error 结束。"},
    "llm/retry": {"title": "安排模型重试", "why": "重试必须在等待前持久记录，确保崩溃或取消后仍能解释发生了什么。", "next": "等待退避，然后写入 llm/retry-started。"},
    "llm/retry-started": {"title": "重试开始", "why": "该事件把计划中的重试与真正开始的请求关联起来，并验证 retryId/turn/step。", "next": "在同一个打开的 step 内重新发起模型请求。"},
    "tool/call": {"title": "记录工具调用", "why": "tool/call 在工具正文执行前写入，确保有副作用的动作有持久意图记录。", "next": "进入审批/策略检查，随后执行工具正文。"},
    "tool/result": {"title": "记录工具结果", "why": "tool/result 是唯一的模型可见工具结果，并通过 callId 与 tool/call 关联。", "next": "将结果放入派生消息历史，进入下一 step。"},
    "approval/policy": {"title": "审批策略判定", "why": "read-only、approval mode 和工具风险共同决定是否需要询问。", "next": "进入 approve/deny 或直接执行。"},
    "approval/asked": {"title": "请求审批", "why": "有副作用的工具在审批模式下需要一次性人工确认。", "next": "记录 approval/decided。"},
    "approval/decided": {"title": "审批决定", "why": "允许或拒绝都要落日志；拒绝会转成工具错误结果，而不是静默跳过。", "next": "允许则执行工具，拒绝则产生 isError 的 tool/result。"},
    "session/flush": {"title": "会话检查点", "why": "模型请求前、工具正文前和 step 边界刷新 session 日志，降低崩溃时丢失已记录工作的风险。", "next": "安全检查点通过后继续模型或工具动作。"},
    "compaction/start": {"title": "压缩开始", "why": "压缩是一个有开始/结束标记的事务，而不是静默改写历史。", "next": "计算要裁剪的旧工具结果或摘要区域。"},
    "compaction/prune": {"title": "裁剪旧工具结果", "why": "先删除/遮蔽低价值旧工具输出，通常比直接调用摘要模型更便宜。", "next": "进入摘要或直接提交压缩结果。"},
    "compaction/summary": {"title": "生成压缩摘要", "why": "摘要事件记录被遮蔽的序列范围、token 估计和生成来源，便于重建 surface。", "next": "用一条 user/message 摘要替换旧 surface 区域。"},
    "compaction/end": {"title": "压缩结束", "why": "结束标记提交替换区域；失败时也会记录在 end 事件中。", "next": "从压缩后的 surface 派生下一次请求。"},
    "todo/write": {"title": "更新 Todo", "why": "dsh 的 todo 工具把结构化计划写入会话，而不是只留在模型文本里。", "next": "后续 step 会从 session 看到新的 todo 状态。"},
})

DESIGN_NOTES: dict[str, str] = {
    "sandbox/requested": "沙箱策略必须在任何外部副作用之前确定，否则工具已经执行后再补边界没有意义。",
    "sandbox/backend_selected": "把平台差异封装在 backend seam 后面，上层循环无需知道 Windows ACL、Linux landlock 或容器实现。",
    "sandbox/policy_applied": "策略事件把 mode、writable roots、network 和 approval 放在同一份可回放记录里，便于审计和故障定位。",
    "sandbox/mounts_prepared": "先建立路径映射再启动工具，才能保证所有文件访问都经过同一套边界。",
    "sandbox/started": "启动事件是生命周期检查点；真实实现会在此之后才允许执行受限命令。",
    "sandbox/exec_wrapped": "命令包装是 sandbox 真正生效的位置；只记录启动但不记录包装，就无法解释某条命令为什么被拒绝。",
    "sandbox/stop_requested": "资源释放和普通执行一样需要可观察的开始/结束，避免泄漏和半关闭状态。",
    "sandbox/stopped": "停止事件让运行结束后的资源状态可验证；教学版明确 simulated，避免误认为真的启动了进程。",
    "sandbox/mode": "把 sandbox mode 写入 session，下一次请求无需依赖进程内变量就能重建相同的安全策略。",
    "turn/start": "turn 是持久生命周期的容器，step 是真正可重试的模型请求边界；把两者分开，错误恢复、取消和 token 统计才有稳定坐标。",
    "turn/end": "显式结束原因使恢复逻辑能区分正常完成、模型错误、上下文溢出和中止，而不是靠最后一个消息猜测。",
    "step/start": "一个 step 只对应一次模型请求及其工具调用，重试时可以完整重跑同一 step，而不会把多个请求混在一起。",
    "step/end": "step 结束是 session checkpoint 的天然边界，保证上一响应和工具结果在下一请求前已持久化。",
    "request/header": "请求头固定 provider/model/cwd/reasoning effort，日志才能证明模型请求是从哪套配置重建的。",
    "assistant/message": "把正文、reasoning 和 tool_calls 放在同一条 assistant 事件里，避免 UI 与服务端各自拼接导致历史不一致。",
    "assistant/attempt": "失败 attempt 不应污染模型可见历史，但必须持久化用于诊断；因此它是独立 settlement 事件。",
    "tool/call": "先记录调用意图再执行，是副作用安全的关键顺序；崩溃时至少知道调用已经准备发生。",
    "tool/result": "工具错误也必须是正式 result，而不是抛异常穿透循环；这样模型能看见错误并决定重试或换路。",
    "session/flush": "存在外部副作用的 Agent 必须把持久化检查点放在模型请求和工具正文之前，否则崩溃恢复无法判断哪些动作已经发出。",
    "compaction/start": "压缩会改写模型可见 surface，所以不能静默执行；显式 start/end 让替换过程可审计。",
    "compaction/prune": "先 prune 旧工具结果再摘要，优先使用成本低、可预测的压缩手段。",
    "compaction/summary": "摘要事件记录被遮蔽事件范围与 token 估算，使下一次请求可以从日志重建而无需保留原始大文本。",
    "compaction/end": "即使压缩失败也要关闭事务，避免留下无法判断状态的悬空 compaction。",
    "fault_injected": "故障注入把不可控的生产异常变成可重复的教学实验。它只在显式选择时启用，避免把演示故障误认为真实故障；事件中同时记录 component 和 mode，便于区分模型、规划、插件和工具四类恢复路径。",
    "stage_started": "用阶段边界包围一组动作，能让异常定位、耗时统计和 UI 回放共享同一套坐标系；这比只记录最终答案更容易解释 Agent 为什么走到某一步。",
    "stage_completed": "把开始和完成拆成两个事件，才能表示“进行中”“成功完成”“异常退出”三种状态；只记录完成会让崩溃路径不可见。",
    "run_started": "先创建 run_id 和事件文件，再执行任何有副作用的动作，保证即使中途崩溃，也能留下可恢复、可审计的证据。",
    "context_built": "上下文分层而不是拼成一段字符串，便于按来源审计：系统规则、仓库规则、环境事实和用户任务各自可替换、可测试、可压缩。",
    "context_prepared": "不同 Harness 的记忆模型不同：Codex/Claude 偏向仓库规则和会话，Hermes 偏向长期身份与技能；统一事件名但保留各自分区，方便横向比较。",
    "context_assembled": "消息装配是模型调用前最后一个可检查边界。把它单独事件化，可以把“上下文构建成功”和“实际发送给模型的内容”区分开，避免只看到字符数。",
    "plan_created": "计划先行的设计把探索、修改、验证拆成可检查状态，降低模型一上来就改错文件的风险；同时让后续 update_plan 能反映真实进度。",
    "todo_created": "TodoWrite 是 Claude 风格的显式工作记忆。它不依赖隐藏的思维链，而是把进度变成模型可读写、用户可审计的结构化状态。",
    "plugin_loaded": "插件采用 manifest 和独立工具注册，而不是让 Harness 直接 import 任意代码；这样能明确版本、工具名、只读属性和冲突检测边界。",
    "plugin_tools_loaded": "工具注册和模型绑定分离：先验证工具 schema 是否合法，再让模型看到它，避免半加载的工具污染下一轮采样。",
    "mcp_tools_loaded": "MCP 把外部能力放到独立 server 进程/协议后面，Harness 只消费工具描述。这让工具生命周期与主进程解耦，也便于做权限和超时隔离。",
    "multi_agent_tools_loaded": "多 Agent 的核心是上下文隔离而不是并发本身。主 Agent 只接收子 Agent 的压缩结果，可以避免大量探索日志挤爆主上下文。",
    "model_request": "Harness 把“模型决策”和“工具执行”拆开：模型只能提出 tool_call，真正动作由受控工具层执行，这是安全边界成立的前提。",
    "agent_message": "assistant 文本既可能是过程说明也可能是最终答案，因此 Harness 必须结合是否还有 tool_calls 来路由，不能看到文本就立即结束。",
    "token_usage": "把 token 用量独立记录，而不是埋在某次响应的字符串里，是为了让预算、压缩和成本分析都有同一份可计算数据。",
    "tool_started": "工具开始事件先于实际执行写入，因此即使工具崩溃，事件流也能知道是哪一个工具、哪一组参数进入了危险区。",
    "tool_finished": "工具失败被转成 ToolMessage 而不是直接抛出，是 Agent 设计中的关键：错误本身也是观察，模型可以据此重试、换工具或停止。",
    "approval_decision": "审批放在工具执行之前，并且由独立策略层裁决，避免模型通过修改自然语言或循环调用绕过权限边界。",
    "permission_decision": "Claude 的 permission mode 把“探索”“编辑”“命令执行”分成不同风险等级，设计重点是最小授权，而不是给模型一个全局 allow。",
    "hook_pre_tool": "Hook 是横切关注点：审计、参数清洗、策略检查不需要侵入每个工具实现，因此放在执行边界最合适。",
    "hook_post_tool": "后置 Hook 让输出清洗、日志和指标采集有统一入口，同时不改变模型实际看到的 ToolMessage 结构。",
    "context_compacted": "压缩先做确定性清理、必要时再做摘要，是为了优先保留可预测性和低延迟；过早调用模型摘要会增加成本和新的失败点。",
    "verification_completed": "验证结果以 returncode 为准，而不是让模型自述“测试通过”。这是编码 Agent 从聊天机器人变成可交付工具的关键设计。",
    "turn_completed": "把“本轮结束”与“整个 run 结束”分开，才能支持外层验证、finalize 和后台复盘等后续阶段。",
    "query_completed": "queryLoop 结束时保存 session memory，让下一次请求可以复用稳定结论，而不是把所有历史消息原样重放。",
    "run_completed": "运行产物和事件流一起落盘，使结果不仅能被使用，还能被复盘、比较和重新播放。",
    "review_completed": "Hermes 把复盘放在主答案之后且使用隔离上下文，避免后台学习过程改写用户已经收到的回答，同时让长期知识持续积累。",
    "memory_changed": "长期记忆只保存稳定、可复用的事实，不保存所有对话；否则噪声会持续污染下一次上下文。",
    "skill_viewed": "技能采用渐进披露：索引只包含名称和描述，真正需要时才读取正文，降低上下文成本并减少无关指令干扰。",
    "skill_changed": "把经验整理成技能而不是直接塞进记忆，便于复用、审阅和版本化；这是 Hermes 区别于普通聊天记忆的核心设计。",
    "subagent_spawned": "子 Agent 使用独立消息历史，把探索噪声隔离在子上下文；主 Agent 只消费结构化结果，减少上下文膨胀。",
    "subagent_completed": "结果回传而不是共享全部过程，等价于一次受控的“上下文压缩 + 责任边界”设计。",
    "error": "错误被事件化而不是只打印堆栈，是为了让前端能定位失败阶段、展示恢复策略，并让测试可以断言失败路径。",
    "fallback_applied": "降级策略必须显式记录策略名和受影响组件，否则用户会误以为功能正常；可解释的失败比静默成功更安全。",
    "failure_summary": "硬失败需要明确终止边界，防止上层把部分结果误判为成功；同时保留错误摘要，便于人工接手。",
    "retry_scheduled": "有限重试配合退避，是应对瞬时网络/限流错误的常见折中；设置上限可以避免把故障放大成成本事故。",
    "limit_reached": "最大步数、最大轮数和最大 token 是 Agent 的断路器，用来保证系统在模型行为异常时仍然可预测地停止。",
    "checkpoint_saved": "检查点把“消息状态”和“执行进度”保存为可恢复对象，使长任务不必因为一次进程崩溃从头再来。",
    "reasoning_content": "推理内容和最终答案分栏保存，既方便学习模型如何决策，也避免把内部推理误当成对用户的承诺或事实。",
}

SYSTEM_NOTES: dict[str, str] = {
    "codex": "Codex 风格强调 turn loop、工具执行和验证闭环；计划与事件流服务于开发任务的审计，而不是通用闲聊。",
    "claude": "Claude 风格强调权限模式、hooks、TodoWrite 和 queryLoop；安全边界与工具前置检查是这套设计的中心。",
    "hermes": "Hermes 风格强调长期身份、记忆、技能和后台复盘；主对话与后台学习隔离，追求跨会话持续变强。",
    "deepseek": "DeepSeek 套件直接对齐 dsh 的 session event、agent-loop、tool-calls、llm-retry 与 compaction 语义：session 是唯一真源，turn/step 是生命周期，tool/call 与 tool/result 先记录后执行。",
}


EVENT_GUIDES.update({
    "sandbox/requested": {"title": "请求启用 Sandbox", "why": "在模型请求或工具副作用之前先确定沙箱策略，避免先执行再补安全边界。", "next": "选择可用 backend 并应用策略。"},
    "sandbox/backend_selected": {"title": "选择 Sandbox Backend", "why": "不同平台可用的隔离技术不同，必须先选择 backend 或明确失败。", "next": "应用文件/网络/命令策略。"},
    "sandbox/policy_applied": {"title": "应用 Sandbox 策略", "why": "把 sandbox mode、writable roots、network access 和审批模式变成可审计配置。", "next": "准备 workspace 挂载并记录启动完成。"},
    "sandbox/mounts_prepared": {"title": "准备 Sandbox 挂载", "why": "只把允许的 workspace 路径映射进沙箱，文件边界从这里开始生效。", "next": "记录 sandbox started。"},
    "sandbox/started": {"title": "Sandbox 模拟启动完成", "why": "本教学版只记录启动阶段，不真正创建容器或进程，但事件形状与真实生命周期一致。", "next": "后续工具命令应经过 sandbox 包装。"},
    "sandbox/exec_wrapped": {"title": "包装 Sandbox 命令", "why": "命令在执行前被 sandbox runner 包装，才能应用文件、网络和进程限制。", "next": "执行被包装的命令或记录 sandbox denial。"},
    "sandbox/stop_requested": {"title": "请求停止 Sandbox", "why": "停止也需要显式事件，确保资源释放和失败路径可回放。", "next": "记录 sandbox stopped。"},
    "sandbox/stopped": {"title": "Sandbox 已停止", "why": "结束事件关闭 sandbox 生命周期；教学版不会真正停止任何容器或进程。", "next": "结束本次运行。"},
    "sandbox/mode": {"title": "记录 Sandbox 模式", "why": "session 中的 sandbox/mode 事件让后续请求可以从日志重建安全策略。", "next": "模型和工具按该模式运行。"},
})

SOURCE_REFERENCES: dict[str, dict[str, list[str]]] = {
    "codex": {
        "sandbox/started": ["codex-rs/protocol/src/protocol.rs::SandboxPolicy", "codex-rs/core/src/sandboxing/"],
        "run_started": ["codex-rs/core/src/session/turn.rs::run_turn"],
        "context_built": ["codex-rs/core/src/agents_md.rs", "codex-rs/core/src/session/turn_context.rs::TurnContext"],
        "plan_created": ["codex-rs/core/src/tools/handlers/plan.rs", "codex-rs/protocol/src/plan_tool.rs"],
        "model_request": ["codex-rs/core/src/session/turn.rs::run_turn"],
        "tool_started": ["codex-rs/core/src/tools/spec_plan.rs::build_tool_router"],
        "tool_finished": ["codex-rs/protocol/src/protocol.rs::EventMsg"],
        "context_compacted": ["codex-rs/core/src/compact.rs"],
        "multi_agent_tools_loaded": ["codex-rs/core/src/agent/control/"],
    },
    "claude": {
        "sandbox/started": ["restored-src/src/utils/sandbox/sandbox-adapter.ts::SandboxManager", "restored-src/src/entrypoints/sandboxTypes.ts"],
        "context_prepared": ["restored-src/src/utils/claudemd.ts"],
        "todo_created": ["restored-src/src/tools/", "Claude Code TodoWrite"],
        "model_request": ["restored-src/src/query.ts::queryLoop"],
        "tool_started": ["restored-src/src/tools/"],
        "permission_decision": ["Claude Code Tool permission pipeline"],
        "hook_pre_tool": ["Claude Code hooks"],
        "context_compacted": ["restored-src/src/services/compact/"],
        "subagent_spawned": ["Claude Code Task / TaskOutput / SendMessage"],
        "mcp_tools_loaded": ["Claude Code MCP service"],
    },
    "hermes": {
        "sandbox/started": ["tools/environments/", "toolsets.py"],
        "context_prepared": ["agent/memory_context.py", "toolsets.py"],
        "memory_changed": ["tools/memory_tool_store.py::MemoryStore", "agent/memory_context.py"],
        "skill_viewed": ["tools/skills_tool.py", "tools/skill_manager_tool.py"],
        "skill_changed": ["tools/skill_manager_tool.py", "agent/curator.py"],
        "review_completed": ["agent/background_review.py"],
        "turn_completed": ["agent/conversation_loop.py::_run_conversation_turn"],
        "toolsets_resolved": ["toolsets.py"],
    },
    "deepseek": {
        "sandbox/started": ["packages/sandbox/sandbox/src/index.ts::SandboxPolicy", "packages/sandbox/sandbox-local/src/index.ts", "packages/sandbox/sandbox-windows-acl/src/index.ts"],
        "run_started": ["packages/core/agent-loop/src/agent.ts::ReactLoopAgent.turn"],
        "context_built": ["packages/core/agent-loop/src/agent.ts::step", "packages/core/session/src/index.ts::deriveMessages"],
        "turn/start": ["packages/core/agent-loop/src/agent.ts::turn", "packages/core/session/src/types.ts::SessionEventMap"],
        "step/start": ["packages/core/agent-loop/src/agent.ts::step"],
        "user/message": ["packages/core/session/src/types.ts::user/message"],
        "request/header": ["packages/core/session/src/types.ts::request/header"],
        "agent/request": ["packages/core/agent-loop/src/agent.ts::step"],
        "assistant/message": ["packages/core/session/src/types.ts::assistant/message"],
        "assistant/attempt": ["packages/core/session/src/types.ts::assistant/attempt"],
        "llm/retry": ["packages/llm/llm-retry/src/index.ts::backoff"],
        "llm/retry-started": ["packages/llm/llm-retry/src/index.ts::backoff"],
        "tool/call": ["packages/core/agent-loop/src/tool-calls.ts::appendToolCall"],
        "tool/result": ["packages/core/agent-loop/src/tool-calls.ts::appendToolResult"],
        "approval/policy": ["docs/tool-execution-pipeline.zh.md", "packages/core/agent-loop/src/tool-calls.ts"],
        "approval/asked": ["docs/tool-execution-pipeline.zh.md"],
        "approval/decided": ["docs/tool-execution-pipeline.zh.md"],
        "session/flush": ["packages/session/session-checkpoint-policy/src/index.ts"],
        "compaction/start": ["packages/compaction/compaction-basic/src/region.ts"],
        "compaction/prune": ["packages/compaction/compaction-tool-result-pruner/src/index.ts"],
        "compaction/summary": ["packages/compaction/compaction-basic/src/region.ts"],
        "compaction/end": ["packages/compaction/compaction-basic/src/region.ts"],
        "step/end": ["packages/core/agent-loop/src/agent.ts::step", "packages/core/session/src/types.ts::step/end"],
        "turn/end": ["packages/core/session/src/types.ts::turn/end"],
        "todo/write": ["packages/core/session/src/types.ts::todo/write"],
    },
}


def _json_preview(value: object, limit: int = 1800) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字符）"


def _plan_lines(plan: object) -> str:
    if not isinstance(plan, dict):
        return _json_preview(plan)
    items = plan.get("items") or plan.get("steps") or []
    lines: list[str] = []
    if plan.get("summary"):
        lines.append(f"摘要：{plan['summary']}")
    for index, item in enumerate(items, 1):
        if isinstance(item, dict):
            label = item.get("title") or item.get("content") or item.get("step") or "(未命名)"
            status = item.get("status") or "pending"
            lines.append(f"{index}. [{status}] {label}")
        else:
            lines.append(f"{index}. {item}")
    return "\n".join(lines) or _json_preview(plan)


def _snapshot_names(snapshot: object) -> str:
    if not isinstance(snapshot, dict):
        return ""
    return "、".join(str(key) for key in snapshot.keys())


def _message_roles(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    counts: dict[str, int] = {}
    for message in messages:
        role = str(message.get("role", "message")) if isinstance(message, dict) else "message"
        counts[role] = counts.get(role, 0) + 1
    return "、".join(f"{role}={count}" for role, count in counts.items())


def explain_event(system: str, event: dict) -> dict[str, str]:
    """把一条底层 events.jsonl 记录翻译成学习者可理解的五段解释。

    解释由确定性规则生成，不额外调用模型；它只描述这一事件为什么发生、
    输入是什么、输出是什么，以及 Harness 接下来会走向哪里。
    """

    event_type = str(event.get("event") or event.get("type") or "event")
    stage = str(event.get("stage") or "")
    stage_label = STAGE_LABELS.get(stage, stage or "未知阶段")
    message = str(event.get("message") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    session_data = data.get("session_data") if isinstance(data.get("session_data"), dict) else {}
    guide = EVENT_GUIDES.get(event_type, {
        "title": event_type.replace("_", " "),
        "why": "这是 Harness 写入的运行时事件，用来记录内部状态变化。",
        "next": "继续观察后续事件。",
    })
    title = guide["title"]
    why = guide["why"]
    input_text = f"阶段：{stage_label}"
    output_text = message or "（无文本输出）"
    next_text = guide["next"]

    if event_type == "stage_started":
        title = f"进入「{stage_label}」阶段"
        why = f"Harness 把一次运行拆成可观察阶段；当前开始执行「{stage_label}」。"
        input_text = message or f"阶段标识：{stage}"
        output_text = "阶段入口事件已记录，阶段内部动作会继续写入后续事件。"
        next_text = f"等待「{stage_label}」阶段内的具体动作完成。"
    elif event_type == "stage_completed":
        title = f"「{stage_label}」阶段完成"
        why = "阶段完成事件用于标记边界和耗时，便于确认流程走到哪里。"
        input_text = message or f"阶段标识：{stage}"
        output_text = f"status={data.get('status', 'unknown')}，elapsed_ms={data.get('elapsed_ms', '?')}"
        next_text = "进入下一个阶段。"
    elif event_type in {"context_built", "context_prepared"}:
        snapshot = data.get("context_snapshot")
        sections = _snapshot_names(snapshot)
        input_text = "读取 workspace 规则文件、环境信息和当前任务；不读取 .env 或凭据文件。"
        details = [message or "上下文已准备"]
        if sections:
            details.append(f"已加载分区：{sections}")
        if data.get("message_count") is not None:
            details.append(f"实际消息数：{data['message_count']}")
        output_text = "；".join(details) + "。完整内容见下方“完整上下文快照”。"
        next_text = "生成计划并装配为正式的模型消息。"
    elif event_type == "context_assembled":
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        roles = _message_roles(messages)
        input_text = f"上下文分区、计划和任务；实际消息 {len(messages)} 条"
        output_text = (message or "上下文已装配") + (f"；角色分布：{roles}" if roles else "")
        next_text = "发起第一次模型采样。"
    elif event_type in {"plan_created", "todo_created"}:
        input_text = "任务、仓库规则和可用工具列表"
        output_text = _plan_lines(data.get("plan"))
        next_text = "把计划状态注入上下文，然后开始模型循环。"
    elif event_type in {"plugin_loaded", "plugin_tools_loaded", "mcp_tools_loaded", "multi_agent_tools_loaded"}:
        tools = data.get("tools") or []
        input_text = f"装载来源：{data.get('plugin') or event_type}"
        output_text = (message or "工具已装载") + (f"；工具：{_json_preview(tools)}" if tools else "")
        next_text = "模型下一次采样时即可看到这些工具 schema。"
    elif event_type == "model_request":
        input_text = f"turn={data.get('turn', data.get('step', '?'))}；压缩后的消息历史 + 当前 Tool 列表"
        output_text = "请求已提交，等待模型返回 assistant message 或 tool_calls。"
        next_text = "解析模型返回并路由到回答或工具执行。"
    elif event_type == "agent_message":
        input_text = "模型采样返回的 assistant message"
        output_text = message or "（空文本，可能只有 tool_calls）"
        next_text = "有工具调用则执行工具；否则进入收尾。"
    elif event_type == "token_usage":
        usage_keys = ["input_tokens", "output_tokens", "total_tokens"]
        usage = {key: data[key] for key in usage_keys if key in data}
        input_text = f"本轮模型请求，stage={stage_label}"
        output_text = _json_preview(usage) if usage else message
        next_text = "用于预算判断；接近阈值时触发上下文压缩。"
    elif event_type == "tool_started":
        input_text = f"工具：{data.get('tool', 'unknown')}\n参数：{_json_preview(data.get('args', {}))}"
        output_text = "工具调用已发出，正在执行本地函数。"
        next_text = "读取真实返回值，并产生 tool_finished 事件。"
    elif event_type == "tool_finished":
        input_text = f"工具：{data.get('tool', 'unknown')}；call_id={data.get('call_id', '-')}"
        output_text = f"status={data.get('status', 'unknown')}，elapsed_ms={data.get('elapsed_ms', '?')}\n{message}"
        next_text = "将输出封装为 ToolMessage，继续模型采样。"
    elif event_type in {"approval_decision", "permission_decision"}:
        input_text = _json_preview(data)
        output_text = f"decision={data.get('behavior', data.get('decision', '?'))}，reason={data.get('reason', message)}"
        next_text = "根据决策执行或拒绝工具。"
    elif event_type in {"hook_pre_tool", "hook_post_tool"}:
        input_text = f"工具：{data.get('tool', '?')}\n参数/输出：{_json_preview(data.get('args', data.get('output', '')))}"
        output_text = message or "Hook 已完成"
        next_text = "继续工具执行或回填工具结果。"
    elif event_type == "fault_injected":
        input_text = f"显式故障演练 mode={data.get('mode', '?')}"
        output_text = f"component={data.get('component', '?')}；{message}"
        next_text = "观察 Harness 是否重新路由、重试、降级或安全终止。"
    elif event_type in {"fallback_applied", "failure_summary"}:
        input_text = f"失败组件：{data.get('component', '?')}；错误：{data.get('error', '见事件正文')}"
        output_text = (f"strategy={data.get('strategy', '?')}；{message}")
        next_text = "继续当前可恢复路径，或记录终止原因并返回结果。"
    elif event_type in {"retry_scheduled", "retry_succeeded"}:
        input_text = (f"step={data.get('step', '?')}，attempt={data.get('attempt', '?')}，"
                      f"max_attempts={data.get('max_attempts', '?')}")
        output_text = message or "重试状态已更新"
        next_text = "重试成功后继续主循环；耗尽后进入 failure_summary。"
    elif event_type == "limit_reached":
        input_text = f"component={data.get('component', '?')}；上限={data.get('max_steps', data.get('max_turns', '?'))}"
        output_text = message or "运行达到硬上限"
        next_text = "返回部分结果，并保留需要人工调整的提示。"
    elif event_type in {"turn/start", "step/start", "step/end"}:
        input_text = f"turn={data.get('turn', '?')}，step={data.get('step', '?')}"
        output_text = message or "生命周期事件已写入 session"
        next_text = "继续当前 turn/step 生命周期。"
    elif event_type == "turn/end":
        reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
        input_text = f"turn={data.get('turn', '?')}"
        output_text = f"reason.kind={reason.get('kind', '?')}；{message}"
        next_text = "结束运行并保留可诊断的结束原因。"
    elif event_type == "request/header":
        header = data.get("header") if isinstance(data.get("header"), dict) else (session_data.get("header") if isinstance(session_data.get("header"), dict) else {})
        input_text = f"provider={header.get('provider', '?')}，model={header.get('model', '?')}，cwd={header.get('cwd', '?')}"
        output_text = f"reason={data.get('reason', '?')}；请求头已持久化"
        next_text = "执行 session flush 后调用模型。"
    elif event_type == "agent/request":
        input_text = f"turn={data.get('turn', '?')}，step={data.get('step', '?')}，message_count={data.get('message_count', '?')}"
        output_text = "实时模型请求已发出；实际消息可在下方查看。"
        next_text = "等待 assistant/message 或 assistant/attempt。"
    elif event_type == "assistant/message":
        tool_calls = data.get("tool_calls") or []
        usage = data.get("usage") or {}
        input_text = f"turn={data.get('turn', '?')}，step={data.get('step', '?')}"
        output_text = f"tool_calls={len(tool_calls)}；usage={_json_preview(usage)}；{message}"
        next_text = "有 tool_calls 则进入工具流水线，否则关闭 turn。"
    elif event_type == "assistant/attempt":
        input_text = f"turn={data.get('turn', '?')}，step={data.get('step', '?')}"
        output_text = f"失败 attempt 已记录；{message}"
        next_text = "根据 retry 或 turn/end 决定恢复路径。"
    elif event_type == "tool/call":
        input_text = f"tool={session_data.get('name', data.get('tool', '?'))}；arguments={session_data.get('arguments', data.get('args', ''))}"
        output_text = f"callId={session_data.get('callId', data.get('call_id', '?'))}；调用已记录，等待策略/执行。"
        next_text = "审批通过后执行工具，并产生 tool/result。"
    elif event_type == "tool/result":
        input_text = f"callId={session_data.get('callId', data.get('call_id', '?'))}；name={session_data.get('name', data.get('tool', '?'))}"
        output_text = f"isError={session_data.get('isError', data.get('isError', '?'))}；{message}"
        next_text = "将结果加入派生历史，进入下一 step。"
    elif event_type.startswith("approval/"):
        input_text = f"tool={data.get('tool', '?')}；callId={data.get('callId', '?')}；mode={data.get('mode', '-')}"
        output_text = f"behavior={data.get('behavior', '-')}；reason={data.get('reason', message)}"
        next_text = "按策略决定是否执行工具正文。"
    elif event_type == "session/flush":
        input_text = f"phase={data.get('phase', '?')}，turn={data.get('turn', '?')}，step={data.get('step', '?')}"
        output_text = f"session_file={data.get('session_file', '?')}"
        next_text = "检查点成功后再继续模型请求或工具正文。"
    elif event_type.startswith("compaction/"):
        input_text = f"compactionId={data.get('compactionId', '?')}，turn={data.get('turn', '?')}"
        output_text = message or "压缩事务状态已更新"
        next_text = "完成后从压缩后的 session surface 派生下一次请求。"
    elif event_type.startswith("sandbox/"):
        input_text = (
            f"mode={data.get('mode', '-')}，backend={data.get('backend', '-')}，"
            f"writable_roots={data.get('writable_roots', data.get('writableRoots', []))}"
        )
        output_text = message or "sandbox 生命周期状态已更新"
        next_text = "继续 sandbox 生命周期或进入工具执行。"
    elif event_type == "context_compacted":
        input_text = f"压缩方法：{data.get('method', data.get('removed', '?'))}"
        output_text = (f"before_tokens={data.get('before_tokens', '?')}，"
                       f"after_tokens={data.get('after_tokens', '?')}；{message}")
        next_text = "用压缩后的消息继续模型请求。"
    elif event_type == "verification_completed":
        input_text = "verify_command 或已执行过的同一命令"
        output_text = f"returncode={data.get('returncode', '?')}；{message}"
        next_text = "根据返回码决定成功状态并写入摘要。"
    elif event_type == "verification_skipped":
        output_text = message or "没有配置验证命令"
        next_text = "进入 finalize，保留“未验证”风险。"
    elif event_type == "review_completed":
        review = data.get("review")
        output_text = _json_preview(review, 2400) if review is not None else message
        next_text = "后台记忆/技能更新完成，主答案不会被改写。"
    elif event_type.startswith("subagent_"):
        input_text = f"agent_id={data.get('agent_id', '?')}；tool={data.get('tool', '-')}"
        output_text = message or "子 Agent 状态已更新"
        next_text = "主 Agent 根据子 Agent 的结果继续决策。"
    elif event_type in {"memory_changed", "skill_viewed", "skill_changed"}:
        input_text = _json_preview(data)
        output_text = message or "记忆/技能状态已更新"
        next_text = "后续上下文准备或工具循环会读取最新状态。"

    return {
        "title": title,
        "why": why,
        "input": input_text,
        "output": output_text,
        "next": next_text,
        "system": system,
        "stage": stage_label,
        "design": DESIGN_NOTES.get(event_type, "这个事件把内部状态变成可观察事实，便于定位流程、复现问题和比较不同 Harness 的实现。"),
        "system_design": SYSTEM_NOTES.get(system, "不同 Harness 共享事件协议，但上下文、权限和持久化策略不同。"),
        "source_refs": SOURCE_REFERENCES.get(system, {}).get(event_type, []),
    }
