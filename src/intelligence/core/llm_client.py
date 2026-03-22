"""LLM 客户端单例 -- 统一管理 OpenAI 客户端、重试和降级。"""
import logging
import time
from functools import wraps

from openai import APITimeoutError, OpenAI, RateLimitError

from intelligence.config import LLM_API_KEY, LLM_BASE_URL

logger = logging.getLogger("intelligence.core.llm_client")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """获取 OpenAI 客户端单例。"""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=30.0,
            max_retries=0,  # We handle retries ourselves
        )
    return _client


def llm_call_with_retry(func):
    """装饰器：为 LLM 调用添加重试和降级逻辑。

    重试策略：指数退避，最多 3 次
    - RateLimitError: 等待后重试
    - APITimeoutError: 立即重试
    - 其他异常: 不重试，直接抛出
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                wait = min(2 ** attempt * 2, 30)
                logger.warning(
                    "RateLimitError, 等待 %ds 后重试 "
                    "(attempt %d/%d)",
                    wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
            except APITimeoutError:
                if attempt == max_retries:
                    raise
                wait = min(2 ** attempt, 10)
                logger.warning(
                    "APITimeoutError, %ds 后重试 "
                    "(attempt %d/%d)",
                    wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
        return None
    return wrapper
