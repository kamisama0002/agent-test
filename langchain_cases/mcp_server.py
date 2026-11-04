"""案例 10 的本地 MCP Server。

MCP（Model Context Protocol）定义了模型应用与外部工具/资源之间的标准协议。
这个服务由 ``case10_mcp.py`` 通过 stdio 子进程启动，不需要单独开端口。

运行方式（通常不用手动执行）：
    python -m langchain_cases.mcp_server
"""

from __future__ import annotations

from fastmcp import FastMCP

mcp = FastMCP("langchain-demo-mcp")


@mcp.tool
def lookup_employee(employee_id: str) -> dict:
    """按员工编号查询员工姓名、部门和基本工资。"""

    employees = {
        "E1001": {"name": "陈晓", "department": "平台研发", "base_salary": 22000},
        "E1002": {"name": "周宁", "department": "数据产品", "base_salary": 20000},
    }
    return employees.get(employee_id.upper(), {"error": f"未找到员工 {employee_id}"})


@mcp.tool
def calculate_bonus(base_salary: float, performance_score: float) -> dict:
    """按绩效系数计算奖金：奖金 = 基本工资 × 绩效分 / 100 × 1.5。"""

    if not 0 <= performance_score <= 100:
        raise ValueError("performance_score 必须在 0 到 100 之间")
    bonus = round(base_salary * performance_score / 100 * 1.5, 2)
    return {"base_salary": base_salary, "performance_score": performance_score, "bonus": bonus}


if __name__ == "__main__":
    # FastMCP 默认使用 stdio transport，正好适合被本地客户端拉起。
    mcp.run(show_banner=False)
