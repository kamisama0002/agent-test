"""一个故意带有 bug 的计算器，用于演示 Claude-style Harness。"""


def add(a: int, b: int) -> int:
    # BUG: 这里应该是加法。
    return a - b


def subtract(a: int, b: int) -> int:
    return a - b
