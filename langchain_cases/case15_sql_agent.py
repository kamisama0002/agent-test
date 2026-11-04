"""案例 15：SQL 数据 Agent。

对应官方教程：
- SQL agent: https://docs.langchain.com/oss/python/langchain/sql-agent

用 SQLite 内存数据库模拟业务库。模型负责把自然语言问题转成 SQL，
工具负责执行并返回结果。这里故意做了三个安全约束：
1. 只允许单条 SELECT；
2. 限制返回行数；
3. 不把数据库写权限暴露给模型。

生产环境还应使用只读数据库账号、SQL 解析器、查询超时、行级权限和审计日志。
"""

from __future__ import annotations

import sqlite3

from langchain.agents import create_agent
from langchain.tools import tool

from .common import build_chat_model, console, message_text, print_panel


def _create_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE sales (
            product TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL
        );
        INSERT INTO sales (product, price, quantity) VALUES
            ('A 型传感器', 120.0, 35),
            ('B 型控制器', 450.0, 12),
            ('C 型网关', 800.0, 20);
        """
    )
    return connection


def run() -> None:
    connection = _create_database()

    @tool
    def get_database_schema() -> str:
        """返回当前 SQLite 数据库的表结构。不确定字段名时应先调用。"""

        return (
            "表 sales(product TEXT, price REAL, quantity INTEGER)\n"
            "示例数据：A 型传感器(120.0, 35)、B 型控制器(450.0, 12)、C 型网关(800.0, 20)"
        )

    @tool
    def run_readonly_sql(query: str) -> str:
        """执行一条只读 SELECT SQL（SQLite 方言），返回表头和数据行。

        数据库只有 sales(product, price, quantity) 一张表。
        """

        normalized = query.strip().rstrip(";").strip()
        lowered = normalized.lower()
        if not lowered.startswith("select"):
            return "SQL_REJECTED: 安全策略只允许 SELECT 查询"
        if ";" in normalized:
            return "SQL_REJECTED: 只允许单条 SQL"

        try:
            rows = connection.execute(normalized).fetchmany(20)
        except sqlite3.Error as exc:
            # 把数据库错误返回给模型，让它看到真实 schema 后自我纠正，
            # 而不是让整个 Agent 因一次错误 SQL 直接崩溃。
            return (
                f"SQL_ERROR: {exc}\n"
                "可用表：sales(product TEXT, price REAL, quantity INTEGER)。"
                "请只使用 SQLite 支持的语法。"
            )

        if not rows:
            return "查询结果为空"
        headers = list(rows[0].keys())
        lines = [" | ".join(headers)]
        for row in rows:
            lines.append(" | ".join(str(row[header]) for header in headers))
        return "\n".join(lines)

    agent = create_agent(
        model=build_chat_model(),
        tools=[get_database_schema, run_readonly_sql],
        system_prompt=(
            "你是数据分析助手。数据库只有一张 SQLite 表："
            "sales(product TEXT, price REAL, quantity INTEGER)。"
            "必须先调用工具获取真实数据，再依据结果回答。"
            "不要查询 information_schema，SQL 只能使用 SELECT。"
        ),
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "查询每个产品的销售额（price * quantity），告诉我销售额最高的产品。",
                }
            ]
        }
    )

    print_panel("SQL Agent 最终回答", message_text(result["messages"][-1]), border_style="green")

    console.print("\n[dim]工具内部才是权限边界；提示词不是安全边界。"
                  "生产环境务必让数据库账号本身只读，并限制可访问的表。[/dim]")


if __name__ == "__main__":
    run()
