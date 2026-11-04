"""LangChain 核心用法示例集。

模块按编号拆分，方便按主题阅读和单独运行。
"""

import warnings

# Python 3.14 下 langchain-core 仍会探测 Pydantic V1 兼容层，产生一条无害告警。
# 本项目的示例全部使用 Pydantic V2，因此只屏蔽这一条已知告警，其他告警保留。
warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3.14.*",
    category=UserWarning,
)
# fastmcp 2.x 内部仍使用 authlib.jose；这是上游依赖告警，不影响示例。
warnings.filterwarnings("ignore", message=r"authlib\.jose module is deprecated.*")

__all__ = ["config", "common"]
