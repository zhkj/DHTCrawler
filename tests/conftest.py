"""共享 fixtures。"""
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
