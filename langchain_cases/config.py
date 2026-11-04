"""统一的模型与网关配置。

设计原则：
- 所有密钥只从环境变量 / ``.env`` 读取，不散落在业务代码里；
- 默认值适配阿里云百炼 OpenAI 兼容接口；
- 模型名、Token 上限等都可以通过环境变量覆盖，便于换模型做实验。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


# ``config.py`` 在 ``langchain_cases`` 目录内，所以 parent.parent 才是项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# override=False：如果用户在 PowerShell 中显式设置了环境变量，优先使用外部值。
load_dotenv(ENV_FILE, override=False)


@dataclass(frozen=True)
class Settings:
    """项目运行所需的不可变配置集合。"""

    api_key: str
    base_url: str
    chat_model: str
    embedding_model: str
    temperature: float
    max_tokens: int
    timeout: float


def _normalize_base_url(raw: str) -> str:
    """把用户常见写法统一成 OpenAI 兼容接口的完整 Base URL。

    支持三种输入：
    - ``llm-xxx.aliyuncs.com``
    - ``https://llm-xxx.aliyuncs.com``
    - ``https://llm-xxx.aliyuncs.com/compatible-mode/v1``
    """

    value = raw.strip().rstrip("/")
    if not value:
        raise RuntimeError("BAILIAN_BASE_URL 不能为空")

    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if not value.endswith("/compatible-mode/v1"):
        value = f"{value}/compatible-mode/v1"
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存配置。

    使用 ``lru_cache`` 后，同一次进程运行中只解析一次 .env；
    测试或切换配置时，可调用 ``get_settings.cache_clear()`` 重新读取。
    """

    # 同时兼容项目自定义变量和百炼常见变量名，降低换机器后的配置成本。
    api_key = (os.getenv("BAILIAN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "未找到 API Key。请在项目根目录创建 .env，并设置 "
            "BAILIAN_API_KEY=sk-..."
        )

    base_url = _normalize_base_url(
        os.getenv("BAILIAN_BASE_URL", "llm-i9yh569m2mtagoyf.cn-beijing.maas.aliyuncs.com")
    )

    return Settings(
        api_key=api_key,
        base_url=base_url,
        # DeepSeek V4.1 Flash 在当前网关上已实测支持对话、工具调用与流式输出。
        chat_model=os.getenv("BAILIAN_CHAT_MODEL", "deepseek-v4.1-flash").strip(),
        # 当前 Key 对 embedding 接口返回 403，因此默认留空；RAG 案例会自动使用本地嵌入。
        embedding_model=os.getenv("BAILIAN_EMBEDDING_MODEL", "").strip(),
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0")),
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "1600")),
        timeout=float(os.getenv("MODEL_TIMEOUT", "90")),
    )
