# Hermes 与通用 Agent 的研究笔记

Hermes 把“记忆”和“技能”分开：

- 声明性记忆回答“用户是谁、环境是什么”；
- 程序性技能回答“以后如何完成一类任务”。

每轮对话结束后，后台复盘可以 fork 一个独立 Agent，只开放 memory 和 skill 工具，
让它在不改变主对话的前提下更新长期资料。

技能使用渐进披露：系统提示只放 name、description、category，只有真正需要时才
调用 skill_view 加载完整正文和 references/templates/scripts。
