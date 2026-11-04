"""售后小项目的业务规则测试（不访问任何模型）。"""

from __future__ import annotations

from support_project.domain import (
    calculate_refund,
    extract_order_id,
    lookup_order,
    policy_sections,
    search_policy,
)
from support_project.local_embedding import hash_vector


def test_extract_order_id() -> None:
    assert extract_order_id("订单 a1001 的耳机坏了") == "A1001"
    assert extract_order_id("没有订单号") is None


def test_quality_issue_gets_full_refund_and_approval() -> None:
    refund = calculate_refund("A1001", "耳机坏了，无法开机")
    assert refund["approved"] is True
    assert refund["amount"] == 599.0
    assert refund["requires_approval"] is True


def test_unopened_within_seven_days_gets_full_refund() -> None:
    refund = calculate_refund("B2002", "不喜欢颜色")
    assert refund["approved"] is True
    assert refund["amount"] == 89.0
    assert refund["requires_approval"] is False


def test_policy_index_source_is_not_empty() -> None:
    sections = policy_sections()
    assert len(sections) >= 5
    text = search_policy("拆封 数码 质量问题 退款")
    assert "质量问题" in text or "数码" in text


def test_hash_vector_is_deterministic() -> None:
    left = hash_vector("售后 退款 政策")
    right = hash_vector("售后 退款 政策")
    assert left == right
    assert len(left) == 512
