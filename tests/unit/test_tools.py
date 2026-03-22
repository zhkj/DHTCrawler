"""工具集单元测试。"""
from intelligence.core.tools import (
    TOOLS_SCHEMA,
    _sanitize_results,
    _slim_torrent,
    _truncate,
)


class TestSanitize:

    def test_filters_nsfw(self):
        results = [
            {"name": "Ubuntu ISO"},
            {"name": "xxx adult content"},
        ]
        cleaned = _sanitize_results(results)
        assert len(cleaned) == 1
        assert cleaned[0]["name"] == "Ubuntu ISO"

    def test_filters_garbled(self):
        results = [{"name": "good name"}, {"name": "\ufffd\ufffd\ufffd broken"}]
        cleaned = _sanitize_results(results)
        assert len(cleaned) == 1


class TestSlimTorrent:

    def test_basic_fields(self, sample_torrent):
        slim = _slim_torrent(sample_torrent)
        assert slim["info_hash"] == "a" * 40
        assert slim["name"] == sample_torrent["name"]
        assert slim["file_count"] == 1
        assert len(slim["sample_files"]) == 1


class TestTruncate:

    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        long_text = "x" * 5000
        result = _truncate(long_text)
        assert len(result) < 5000
        assert result.endswith("[结果已截断]")


class TestToolsSchema:

    def test_all_tools_have_name(self):
        for tool in TOOLS_SCHEMA:
            assert "name" in tool["function"]

    def test_six_tools_defined(self):
        assert len(TOOLS_SCHEMA) == 6
