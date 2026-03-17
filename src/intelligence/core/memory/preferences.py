"""用户偏好（告警规则等）。"""
from intelligence.db import save_alert_rule, get_alert_rules


class UserPreferences:

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id

    def set_alerts(self, keywords: list[str]):
        save_alert_rule(self.user_id, keywords)

    def get_alerts(self) -> list[str]:
        return get_alert_rules(self.user_id)
