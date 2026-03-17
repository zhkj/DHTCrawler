"""execute_tool 单元测试 — 覆盖所有 6 个工具的调用 + 错误处理。"""
import json
from unittest.mock import patch, MagicMock
import pytest
from intelligence.core.tools import execute_tool, _sanitize_results, _slim_torrent, _truncate


class TestExecuteToolSearchDHT:

    @patch("intelligence.core.tools.rag_search")
    def test_returns_json_results(self, mock_rag):
        mock_rag.return_value = [
            {"info_hash": "a" * 40, "name": "test torrent", "relevance": 0.9},
        ]
        result = execute_tool("search_dht", {"query": "test", "top_k": 5})
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "test torrent"

    @patch("intelligence.core.tools.rag_search")
    def test_filters_nsfw(self, mock_rag):
        mock_rag.return_value = [
            {"name": "safe content"},
            {"name": "xxx adult porn content"},
        ]
        result = execute_tool("search_dht", {"query": "test"})
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["name"] == "safe content"

    @patch("intelligence.core.tools.rag_search", side_effect=Exception("DB error"))
    def test_handles_exception(self, mock_rag):
        result = execute_tool("search_dht", {"query": "test"})
        data = json.loads(result)
        assert "error" in data


class TestExecuteToolGetTorrentDetail:

    @patch("intelligence.core.tools.get_torrent_by_hash")
    def test_returns_torrent_detail(self, mock_get):
        mock_get.return_value = {
            "info_hash": "a" * 40,
            "name": "Ubuntu ISO",
            "files": [{"path": "ubuntu.iso"}],
            "date": "2024-01-01",
        }
        result = execute_tool("get_torrent_detail", {"info_hash": "a" * 40})
        data = json.loads(result)
        assert data["info_hash"] == "a" * 40
        assert data["name"] == "Ubuntu ISO"

    @patch("intelligence.core.tools.get_torrent_by_hash", return_value=None)
    def test_not_found(self, mock_get):
        result = execute_tool("get_torrent_detail", {"info_hash": "x" * 40})
        data = json.loads(result)
        assert "error" in data


class TestExecuteToolSearchHackernews:

    @patch("intelligence.core.tools.search_hackernews")
    def test_returns_results(self, mock_hn):
        mock_hn.return_value = [{"title": "HN Post", "url": "https://example.com"}]
        result = execute_tool("search_hackernews", {"query": "python", "days": 7})
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["title"] == "HN Post"


class TestExecuteToolSearchReddit:

    @patch("intelligence.core.tools.search_reddit")
    def test_returns_results(self, mock_reddit):
        mock_reddit.return_value = [{"title": "Reddit Post", "score": 100}]
        result = execute_tool("search_reddit", {"query": "python", "subreddit": "all"})
        data = json.loads(result)
        assert isinstance(data, list)


class TestExecuteToolSearchNews:

    @patch("intelligence.core.tools.search_rss")
    def test_returns_results(self, mock_rss):
        mock_rss.return_value = [{"title": "News Article"}]
        result = execute_tool("search_news", {"query": "AI"})
        data = json.loads(result)
        assert isinstance(data, list)


class TestExecuteToolGetTrending:

    @patch("intelligence.core.tools.get_recent_torrents")
    def test_returns_trending(self, mock_recent):
        mock_recent.return_value = [
            {"info_hash": "a" * 40, "name": "Popular", "files": [], "date": "2024-01-01"},
        ]
        result = execute_tool("get_trending", {"limit": 5})
        data = json.loads(result)
        assert isinstance(data, list)
        assert data[0]["name"] == "Popular"


class TestExecuteToolUnknown:

    def test_unknown_tool(self):
        result = execute_tool("nonexistent_tool", {})
        data = json.loads(result)
        assert "error" in data
        assert "未知工具" in data["error"]


class TestSanitizeResults:

    def test_filters_nsfw(self):
        results = [{"name": "Ubuntu ISO"}, {"name": "xxx adult content"}]
        cleaned = _sanitize_results(results)
        assert len(cleaned) == 1
        assert cleaned[0]["name"] == "Ubuntu ISO"

    def test_filters_garbled(self):
        results = [{"name": "good"}, {"name": "\ufffd\ufffd\ufffd broken"}]
        cleaned = _sanitize_results(results)
        assert len(cleaned) == 1

    def test_keeps_clean(self):
        results = [{"name": "file1"}, {"name": "file2"}]
        cleaned = _sanitize_results(results)
        assert len(cleaned) == 2


class TestSlimTorrent:

    def test_basic_fields(self, sample_torrent):
        slim = _slim_torrent(sample_torrent)
        assert slim["info_hash"] == "a" * 40
        assert slim["name"] == sample_torrent["name"]
        assert slim["file_count"] == 1
        assert len(slim["sample_files"]) == 1

    def test_limits_files(self):
        torrent = {
            "info_hash": "x" * 40,
            "name": "many files",
            "files": [{"path": f"file_{i}.txt"} for i in range(20)],
            "date": "2024-01-01",
        }
        slim = _slim_torrent(torrent)
        assert slim["file_count"] == 20
        assert len(slim["sample_files"]) == 5


class TestTruncate:

    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        result = _truncate("x" * 5000)
        assert len(result) < 5000
        assert result.endswith("[结果已截断]")
