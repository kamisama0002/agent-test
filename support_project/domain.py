"""售后工单小项目的共享业务域。

这一层故意与任何 Agent 框架解耦：
- 订单查询、退款计算、政策检索都是普通 Python 函数；
- 各框架适配器只负责把这些函数包装成自己的 Tool/Node/Task；
- 这样比较的是“框架编排能力”，而不是业务逻辑实现差异。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_cases.config import PROJECT_ROOT

POLICY_PATH = PROJECT_ROOT / "data" / "support_policy.md"

# 模拟订单库。金额单位：人民币元。
ORDERS: dict[str, dict[str, Any]] = {
    "A1001": {
        "order_id": "A1001",
        "product": "降噪耳机",
        "category": "数码",
        "amount": 599.0,
        "status": "已签收",
        "days_since_purchase": 12,
        "opened": True,
    },
    "B2002": {
        "order_id": "B2002",
        "product": "保温杯",
        "category": "家居",
        "amount": 89.0,
        "status": "已签收",
        "days_since_purchase": 4,
        "opened": False,
    },
}

QUALITY_KEYWORDS = ("坏", "故障", "质量", "破损", "无法使用", "异常", "不工作")


def extract_order_id(text: str) -> str | None:
    """从自然语言中提取形如 A1001 的订单号。"""

    match = re.search(r"\b([A-Z]\d{4})\b", text.upper())
    return match.group(1) if match else None


def lookup_order(order_id: str) -> dict[str, Any]:
    """查询订单。返回 found 字段，避免工具直接抛异常给模型。"""

    order = ORDERS.get(order_id.upper())
    if not order:
        return {"found": False, "order_id": order_id, "error": "未找到该订单"}
    return {"found": True, **order}


def policy_sections() -> list[dict[str, str]]:
    """把 Markdown 政策按二级标题拆成可检索的小节。"""

    text = POLICY_PATH.read_text(encoding="utf-8")
    sections: list[dict[str, str]] = []
    for block in re.split(r"\n## ", text):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        title = lines[0].lstrip("# ").strip()
        body = "\n".join(lines[1:]).strip()
        if body:
            sections.append({"title": title, "content": body})
    return sections


def search_policy(query: str, top_k: int = 2) -> str:
    """轻量关键词检索，供非 RAG 框架作为共享工具使用。

    LlamaIndex 适配器不会调用这个函数，而是用真正的索引/QueryEngine，
    以便体现“数据与检索优先”的框架特色。
    """

    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+", query)
    scored: list[tuple[int, dict[str, str]]] = []
    for section in policy_sections():
        haystack = f"{section['title']}\n{section['content']}"
        score = sum(1 for term in terms if term in haystack)
        # 给退款、质量、数码等关键词额外加权，让示例检索更稳定。
        score += sum(2 for keyword in ("退款", "质量", "数码", "拆封", "审批") if keyword in query and keyword in haystack)
        scored.append((score, section))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [section for score, section in scored[:top_k] if score > 0]
    if not selected:
        selected = [section for _, section in scored[:top_k]]

    return "\n\n".join(
        f"【{section['title']}】\n{section['content']}" for section in selected
    )


def calculate_refund(order_id: str, reason: str) -> dict[str, Any]:
    """根据订单、签收天数和退款原因计算退款结论。"""

    order = lookup_order(order_id)
    if not order["found"]:
        return {"approved": False, "amount": 0.0, "reason": order["error"], "requires_approval": False}

    quality_issue = any(keyword in reason for keyword in QUALITY_KEYWORDS)
    days = int(order["days_since_purchase"])
    amount = float(order["amount"])

    if quality_issue:
        approved = True
        decision = "检测到质量问题，按质量问题退款规则可全额退款，不受七天期限限制。"
    elif days <= 7 and not order["opened"]:
        approved = True
        decision = "签收 7 天内且商品未拆封，符合无理由退货条件。"
    elif days <= 7 and order["opened"] and order["category"] == "数码":
        approved = False
        decision = "已拆封数码商品且无质量问题，不支持无理由退货。"
    elif 7 < days <= 15:
        approved = False
        decision = "签收 7 至 15 天且非质量问题，原则上只支持换货。"
    else:
        approved = False
        decision = "超出政策支持范围，建议转人工进一步核实。"

    return {
        "approved": approved,
        "amount": amount if approved else 0.0,
        "reason": decision,
        "requires_approval": bool(approved and amount >= 500),
        "policy_basis": "质量问题退款" if quality_issue else "七天无理由 / 七至十五天换货政策",
    }


def compact_json(value: Any) -> str:
    """工具返回值统一使用中文 JSON，方便模型读取。"""

    return json.dumps(value, ensure_ascii=False)
