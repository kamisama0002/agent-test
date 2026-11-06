"""DeepSeek Harness 的可运行小白 Demo。

这个 Demo 不调用真实模型，而是用一个两轮 Fake Model：
1. 第一轮假装模型决定调用 read_file；
2. 第二轮看到 tool/result 后返回最终答案。

它仍然运行真实的 DeepSeekHarness、真实的 session event、真实的
tool pipeline 和真实的 approval policy，因此看到的不是静态讲解，
而是项目当前实现的真实事件流。
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from frontend.explanations import explain_event
from .config import DeepSeekHarnessConfig
from .harness import DeepSeekHarness


class DemoModel:
    """可预测的两轮模型，用来替代真实 DeepSeek API。"""

    model_name = "deepseek-demo-offline"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "DemoModel":
        self.tools = tools
        return self

    def invoke(self, messages: list[Any]) -> AIMessage:
        has_tool_result = any(isinstance(message, ToolMessage) for message in messages)
        if not has_tool_result:
            return AIMessage(
                content="",
                additional_kwargs={
                    "reasoning_content": "先读取 README，确认项目内容后再总结。"
                },
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"path": "README.md"},
                        "id": "demo-call-1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(
            content="Demo 完成：这是一个用于验证 DeepSeek Harness 的最小项目。"
        )


def _load_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_demo(*, verbose: bool = True, fault_mode: str = "none") -> dict[str, Any]:
    source = Path(__file__).resolve().parent.parent / "examples" / "deepseek_harness_demo"
    workspace = Path(tempfile.mkdtemp(prefix="deepseek-harness-demo-"))
    shutil.copytree(source, workspace, dirs_exist_ok=True)

    config = DeepSeekHarnessConfig(
        workspace=workspace,
        max_steps=4,
        console=False,
        max_model_retries=0,
        fault_mode=fault_mode,  # type: ignore[arg-type]
    )
    result = DeepSeekHarness(config, model=DemoModel()).run(
        "读取 README.md，用一句话总结，不要修改文件。"
    )
    events = _load_events(result.run_dir)

    if verbose:
        print("=" * 78)
        print("DeepSeek Harness Demo：离线、可重复、逐步解释")
        print("=" * 78)
        print(f"workspace : {workspace}")
        print(f"run_dir   : {result.run_dir}")
        print(f"session   : {result.session_path}")
        print("=" * 78)
        for index, event in enumerate(events, 1):
            row = {
                "event": event.get("type", ""),
                "stage": event.get("stage", ""),
                "message": event.get("message", ""),
                "data": event.get("data", {}),
            }
            explanation = explain_event("deepseek", row)
            print(f"\n[{index:02d}] {row['event']}")
            print(f"  what   : {explanation['title']}")
            print(f"  why    : {explanation['why']}")
            print(f"  input  : {explanation['input']}")
            print(f"  output : {explanation['output']}")
            print(f"  design : {explanation['design']}")
            print(f"  next   : {explanation['next']}")
            if explanation.get("source_refs"):
                print(f"  source : {'; '.join(explanation['source_refs'])}")
        print("\n" + "=" * 78)
        print("最终回答：", result.final_answer)
        print(f"steps={result.steps} flushes={result.flushes} retries={result.retries}")
        print("=" * 78)

    return {
        "workspace": str(workspace),
        "run_dir": str(result.run_dir),
        "session_path": str(result.session_path),
        "final_answer": result.final_answer,
        "steps": result.steps,
        "flushes": result.flushes,
        "events": [event.get("type", "") for event in events],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek Harness 离线小白 Demo")
    parser.add_argument("--fault", choices=["none", "tool_error", "plugin_error", "model_error"], default="none")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    result = run_demo(verbose=not args.quiet, fault_mode=args.fault)
    if args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
