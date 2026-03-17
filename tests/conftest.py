"""共享 fixtures。"""
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def sample_torrent():
    return {
        "info_hash": "a" * 40,
        "name": "Ubuntu 24.04 LTS Desktop amd64.iso",
        "files": [
            {"path": "ubuntu-24.04-desktop-amd64.iso"},
        ],
        "date": "2024-04-25",
    }


@pytest.fixture
def sample_alert():
    return {
        "type": "signal",
        "user_id": "__system__",
        "info_hash": "b" * 40,
        "torrent_name": "confidential_report_2024.pdf",
        "matched_keywords": ["confidential", "report", ".pdf"],
        "categories": ["document", "leak"],
        "confidence": "high",
        "status": "active",
        "read": False,
    }


@pytest.fixture
def sample_torrents():
    """多条种子数据，用于 BM25/向量索引测试。"""
    return [
        {
            "info_hash": "a" * 40,
            "name": "Ubuntu 24.04 LTS Desktop amd64.iso",
            "files": [{"path": "ubuntu-24.04-desktop-amd64.iso"}],
            "date": "2024-04-25",
        },
        {
            "info_hash": "b" * 40,
            "name": "Python Programming Cookbook 2024.pdf",
            "files": [{"path": "python-cookbook.pdf"}],
            "date": "2024-05-01",
        },
        {
            "info_hash": "c" * 40,
            "name": "Confidential Internal Report Q1 2024",
            "files": [{"path": "report_q1.pdf"}, {"path": "appendix.xlsx"}],
            "date": "2024-06-01",
        },
        {
            "info_hash": "d" * 40,
            "name": "Linux Kernel Source 6.8",
            "files": [{"path": "linux-6.8.tar.xz"}],
            "date": "2024-03-10",
        },
        {
            "info_hash": "e" * 40,
            "name": "AI模型训练数据集泄露 GPT-internal",
            "files": [{"path": "training_data.jsonl"}],
            "date": "2024-07-01",
        },
    ]


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client，返回预设 response。"""
    with patch("intelligence.core.orchestrator.OpenAI") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client

        # 默认返回一个简单的文本回复
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "这是一个测试回复。"
        mock_response.choices[0].message.tool_calls = None
        mock_response.usage.total_tokens = 100
        client.chat.completions.create.return_value = mock_response

        yield client


@pytest.fixture
def mock_db():
    """Mock MongoDB 返回预设种子数据。"""
    with patch("intelligence.core.tools.get_torrent_by_hash") as mock_get_hash, \
         patch("intelligence.core.tools.get_recent_torrents") as mock_get_recent, \
         patch("intelligence.core.tools.rag_search") as mock_rag:

        mock_get_hash.return_value = {
            "info_hash": "a" * 40,
            "name": "Ubuntu 24.04 LTS Desktop amd64.iso",
            "files": [{"path": "ubuntu-24.04-desktop-amd64.iso"}],
            "date": "2024-04-25",
        }
        mock_get_recent.return_value = [
            {
                "info_hash": "a" * 40,
                "name": "Ubuntu 24.04 LTS Desktop amd64.iso",
                "files": [{"path": "ubuntu-24.04-desktop-amd64.iso"}],
                "date": "2024-04-25",
            }
        ]
        mock_rag.return_value = [
            {
                "info_hash": "a" * 40,
                "name": "Ubuntu 24.04 LTS Desktop amd64.iso",
                "relevance": 0.85,
            }
        ]

        yield {
            "get_torrent_by_hash": mock_get_hash,
            "get_recent_torrents": mock_get_recent,
            "rag_search": mock_rag,
        }
