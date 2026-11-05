"""极简本地插件系统。

插件不是随便从网络加载代码，而是由用户显式指定目录，并必须包含
`plugin.json` 清单：

```text
my-plugin/
├── plugin.json
└── plugin.py
```

`plugin.json`：

```json
{
  "name": "text-utils",
  "version": "0.1.0",
  "tools": [
    {
      "name": "word_count",
      "description": "统计一段文本的词数",
      "entry": "plugin.py:word_count",
      "read_only": true
    }
  ]
}
```

入口函数使用普通 Python 类型注解，LangChain 会据此生成工具参数 schema。
这是学习版的插件边界：本地、显式、可审计，不做 pip 自动安装和远程下载。
"""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import StructuredTool

PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True)
class PluginToolSpec:
    name: str
    description: str
    entry: str
    read_only: bool = False
    destructive: bool = False
    plugin: str = ""


@dataclass
class LoadedPlugin:
    name: str
    version: str
    root: Path
    tools: list[Any] = field(default_factory=list)
    specs: list[PluginToolSpec] = field(default_factory=list)


class PluginRegistry:
    """从显式目录加载本地插件。"""

    def __init__(self, plugin_dirs: tuple[Path, ...] | list[Path] = (), *, event_bus=None) -> None:
        self.plugin_dirs = tuple(Path(path).resolve() for path in plugin_dirs)
        self.event_bus = event_bus
        self.plugins: list[LoadedPlugin] = []
        self.specs: dict[str, PluginToolSpec] = {}

    def _emit(self, event: str, message: str, **data) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event, "plugins", message, **data)

    @staticmethod
    def _load_module(path: Path, plugin_name: str):
        module_name = f"mini_plugin_{plugin_name}_{abs(hash(str(path))) & 0xFFFFFFFF}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件模块：{path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _resolve_entry(root: Path, entry: str) -> tuple[Path, str]:
        if ":" not in entry:
            raise ValueError(f"插件入口必须写成 file.py:function，实际为 {entry!r}")
        file_name, function_name = entry.split(":", 1)
        path = (root / file_name).resolve()
        if root.resolve() not in path.parents and path != root.resolve():
            raise ValueError(f"插件入口路径越界：{entry}")
        if not path.is_file():
            raise FileNotFoundError(f"插件入口文件不存在：{path}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name):
            raise ValueError(f"非法插件函数名：{function_name}")
        return path, function_name

    def _load_one(self, manifest_path: Path) -> LoadedPlugin:
        root = manifest_path.parent.resolve()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = str(data.get("name") or root.name).strip()
        if not PLUGIN_NAME_RE.fullmatch(name):
            raise ValueError(f"非法插件名：{name}")
        version = str(data.get("version") or "0.1.0")
        tool_data = data.get("tools")
        if not isinstance(tool_data, list) or not tool_data:
            raise ValueError(f"{manifest_path} 没有 tools 列表")
        plugin = LoadedPlugin(name=name, version=version, root=root)
        for raw in tool_data:
            if not isinstance(raw, dict):
                raise ValueError(f"插件工具定义必须是对象：{raw!r}")
            tool_name = str(raw.get("name") or "").strip()
            description = str(raw.get("description") or "").strip()
            entry = str(raw.get("entry") or "").strip()
            if not PLUGIN_NAME_RE.fullmatch(tool_name):
                raise ValueError(f"非法插件工具名：{tool_name}")
            if not description or not entry:
                raise ValueError(f"插件工具 {tool_name} 缺少 description/entry")
            module_path, function_name = self._resolve_entry(root, entry)
            module = self._load_module(module_path, name)
            function: Callable = getattr(module, function_name)
            if not callable(function):
                raise TypeError(f"插件入口不是函数：{entry}")
            spec = PluginToolSpec(
                name=tool_name,
                description=description,
                entry=entry,
                read_only=bool(raw.get("read_only", False)),
                destructive=bool(raw.get("destructive", False)),
                plugin=name,
            )
            if tool_name in self.specs:
                raise ValueError(f"插件工具名冲突：{tool_name}")
            tool = StructuredTool.from_function(
                func=function,
                name=tool_name,
                description=description,
            )
            plugin.tools.append(tool)
            plugin.specs.append(spec)
            self.specs[tool_name] = spec
        return plugin

    def load(self) -> list[Any]:
        tools: list[Any] = []
        for root in self.plugin_dirs:
            if not root.exists():
                raise FileNotFoundError(f"插件目录不存在：{root}")
            manifests = sorted(root.rglob("plugin.json"))
            for manifest in manifests:
                plugin = self._load_one(manifest)
                self.plugins.append(plugin)
                tools.extend(plugin.tools)
                self._emit(
                    "plugin_loaded",
                    f"loaded plugin {plugin.name}",
                    plugin=plugin.name,
                    version=plugin.version,
                    tools=[spec.name for spec in plugin.specs],
                )
        return tools

    def metadata(self, tool_name: str) -> PluginToolSpec | None:
        return self.specs.get(tool_name)
