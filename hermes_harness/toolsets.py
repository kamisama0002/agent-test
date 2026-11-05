"""按场景裁剪的工具集。

Hermes 的 toolsets.py 不是把所有工具都塞给模型，而是根据平台/场景只暴露
必要能力。这里用一个小型注册表复刻这个思路：

- file / terminal 是开发能力；
- memory / skills / session_search 是长期学习与回忆能力；
- hermes 是通用默认组合；
- coding 是偏开发组合；
- research 是偏只读资料组合；
- safe 只提供只读和记忆能力。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str
    tools: tuple[str, ...]


TOOLSETS: dict[str, Toolset] = {
    "file": Toolset("file", "读取、写入、检索 workspace 文件", ("read_file", "write_file", "patch", "search_files")),
    "terminal": Toolset("terminal", "执行受限的开发命令", ("terminal",)),
    "memory": Toolset("memory", "维护 MEMORY.md / USER.md", ("memory",)),
    "skills": Toolset("skills", "索引、查看、创建和整理技能", ("skills_list", "skill_view", "skill_manage")),
    "session_search": Toolset("session_search", "检索历史会话", ("session_search",)),
    "todo": Toolset("todo", "维护当前任务清单", ("todo_list",)),
    "research": Toolset(
        "research",
        "只读查找与复用旧知识",
        ("read_file", "search_files", "memory", "skills_list", "skill_view", "session_search"),
    ),
    "safe": Toolset(
        "safe",
        "只读 + 记忆，不修改 workspace",
        ("read_file", "search_files", "memory", "skills_list", "skill_view", "session_search", "todo_list"),
    ),
    "coding": Toolset(
        "coding",
        "开发任务的基础组合",
        (
            "read_file", "write_file", "patch", "search_files", "terminal", "todo_list",
            "memory", "skills_list", "skill_view", "skill_manage", "session_search",
        ),
    ),
    "hermes": Toolset(
        "hermes",
        "通用 Hermes 组合：文件、命令、记忆、技能、历史、Todo",
        (
            "read_file", "write_file", "patch", "search_files", "terminal", "todo_list",
            "memory", "skills_list", "skill_view", "skill_manage", "session_search",
        ),
    ),
}


def resolve_toolsets(names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """展开 toolset 名称并保持首次出现的顺序。"""

    names = tuple(names)
    if not names:
        raise ValueError("至少选择一个 toolset")
    resolved: list[str] = []
    for name in names:
        if name == "all":
            for toolset in TOOLSETS.values():
                for tool in toolset.tools:
                    if tool not in resolved:
                        resolved.append(tool)
            continue
        toolset = TOOLSETS.get(name)
        if toolset is None:
            raise ValueError(f"未知 toolset：{name}；可用：{', '.join(TOOLSETS)}")
        for tool in toolset.tools:
            if tool not in resolved:
                resolved.append(tool)
    return tuple(resolved)


def describe_toolsets(names: tuple[str, ...] | list[str]) -> str:
    lines = []
    for name in names:
        if name == "all":
            lines.append("- all: 所有内置工具")
            continue
        toolset = TOOLSETS.get(name)
        if toolset:
            lines.append(f"- {name}: {toolset.description}（{', '.join(toolset.tools)}）")
    return "\n".join(lines)
