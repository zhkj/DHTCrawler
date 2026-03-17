"""Guardrails 安全防护模块。

三层防护：
1. 输入防护：检测 prompt injection 模式
2. 工具参数校验：用 Pydantic 校验 LLM 返回的工具参数
3. 输出防护：检测幻觉信号，添加 disclaimer
"""
import logging
import re

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("intelligence.core.guardrails")


# ── 输入防护 ──────────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    # 忽略/覆盖指令
    re.compile(r'ignore\s+(all\s+)?previous\s+instructions', re.IGNORECASE),
    re.compile(r'忽略(之前|以上|上面)(的)?(所有)?(指令|提示|规则)', re.IGNORECASE),
    re.compile(r'无视(之前|以上|上面)(的)?(所有)?(指令|提示|规则)', re.IGNORECASE),
    # System prompt 泄露
    re.compile(
        r'(show|tell|reveal|print|output)\s+(me\s+)?(your\s+)?(system\s+)?prompt',
        re.IGNORECASE,
    ),
    re.compile(r'(显示|输出|告诉我)(你的)?(系统|system)\s*(提示词|prompt)', re.IGNORECASE),
    # 角色扮演攻击
    re.compile(r'you\s+are\s+now\s+(a|an|the)\s+', re.IGNORECASE),
    re.compile(r'pretend\s+(to\s+be|you\s+are)', re.IGNORECASE),
    re.compile(r'act\s+as\s+(a|an|if)', re.IGNORECASE),
    re.compile(r'从现在起你(是|扮演)', re.IGNORECASE),
    # DAN / jailbreak
    re.compile(r'\bDAN\b.*mode', re.IGNORECASE),
    re.compile(r'jailbreak', re.IGNORECASE),
    # 指令注入分隔符
    re.compile(r'---+\s*(system|instructions|new\s+prompt)', re.IGNORECASE),
]


def check_input(user_message: str) -> tuple[bool, str]:
    """检测 prompt injection 模式。

    Args:
        user_message: 用户输入文本。

    Returns:
        (is_safe, reason): is_safe=True 表示安全，reason 为拦截原因。
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(user_message):
            return False, "检测到潜在的提示词注入攻击"

    # 长度限制
    if len(user_message) > 5000:
        return False, "输入长度超过限制（最大 5000 字符）"

    return True, ""


# ── 工具参数校验（Pydantic） ──────────────────────────────────────

class SearchDHTInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=20)


class GetTorrentDetailInput(BaseModel):
    info_hash: str = Field(..., min_length=40, max_length=40, pattern=r'^[a-fA-F0-9]{40}$')


class SearchHackernewsInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    days: int = Field(default=7, ge=1, le=30)


class SearchRedditInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    subreddit: str = Field(default="all", max_length=50)


class SearchNewsInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)


class GetTrendingInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


TOOL_VALIDATORS: dict[str, type[BaseModel]] = {
    "search_dht": SearchDHTInput,
    "get_torrent_detail": GetTorrentDetailInput,
    "search_hackernews": SearchHackernewsInput,
    "search_reddit": SearchRedditInput,
    "search_news": SearchNewsInput,
    "get_trending": GetTrendingInput,
}


def validate_tool_input(tool_name: str, tool_input: dict) -> dict:
    """用 Pydantic 校验 LLM 返回的工具参数。

    校验通过返回标准化后的参数，校验失败返回修正后的参数。

    Args:
        tool_name: 工具名称。
        tool_input: LLM 生成的工具参数。

    Returns:
        校验/修正后的参数字典。
    """
    validator_cls = TOOL_VALIDATORS.get(tool_name)
    if validator_cls is None:
        return tool_input

    try:
        validated = validator_cls(**tool_input)
        return validated.model_dump(exclude_unset=False)
    except ValidationError as e:
        logger.warning(f"工具参数校验失败 | tool={tool_name} errors={e.error_count()}")
        # 尝试修正常见问题
        fixed = _fix_common_issues(tool_name, tool_input, e)
        return fixed


def _fix_common_issues(tool_name: str, tool_input: dict, error: ValidationError) -> dict:
    """尝试自动修正常见的参数问题。"""
    fixed = tool_input.copy()

    for err in error.errors():
        field = err["loc"][0] if err["loc"] else ""
        err_type = err["type"]

        if err_type == "string_too_long" and field in ("query",):
            fixed[field] = fixed[field][:200]
        elif err_type == "greater_than_equal" and field in ("top_k", "limit", "days"):
            fixed[field] = 1
        elif err_type == "less_than_equal" and field in ("top_k",):
            fixed[field] = 20
        elif err_type == "less_than_equal" and field in ("limit",):
            fixed[field] = 50
        elif err_type == "less_than_equal" and field in ("days",):
            fixed[field] = 30

    return fixed


# ── 输出防护 ──────────────────────────────────────────────────────

def check_output(response: str, sources: list[dict] | None = None) -> str:
    """检测幻觉信号，必要时添加 disclaimer。

    Args:
        response: LLM 生成的回复文本。
        sources: 工具返回的数据源列表。

    Returns:
        可能附加了 disclaimer 的回复文本。
    """
    if not response:
        return response

    # 检测幻觉信号词
    hallucination_signals = [
        "据我所知", "根据我的训练数据", "as far as I know",
        "I believe", "我认为可能", "大概是",
    ]

    has_signal = any(signal in response for signal in hallucination_signals)

    # 如果没有提供数据源支撑，且响应中包含幻觉信号
    if has_signal and not sources:
        response += "\n\n⚠️ *以上部分内容未经数据源验证，仅供参考。*"

    return response
