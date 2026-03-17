"""置信度评分单元测试。"""
from intelligence.monitor.confidence import score


class TestConfidenceScore:

    def test_user_rule_always_high(self):
        assert score(["leak"], [], is_user_rule=True) == "high"

    def test_many_keywords_high(self):
        assert score(["leak", "confidential", "internal"], ["leak"], is_user_rule=False) == "high"

    def test_multiple_categories_high(self):
        assert score(["leak", "trojan"], ["leak", "malware"], is_user_rule=False) == "high"

    def test_two_keywords_medium(self):
        assert score(["leak", "internal"], ["leak"], is_user_rule=False) == "medium"

    def test_single_keyword_low(self):
        assert score(["patch"], [], is_user_rule=False) == "low"

    def test_empty_keywords_low(self):
        assert score([], [], is_user_rule=False) == "low"

    def test_one_keyword_one_category_medium(self):
        assert score(["confidential"], ["document"], is_user_rule=False) == "medium"
