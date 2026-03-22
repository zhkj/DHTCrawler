"""
数据访问层 — 按领域拆分为独立 Repository。
统一从此处导入，业务层无需关心底层集合名。
"""
from intelligence.db.client import get_db
from intelligence.db.repo_alert import (
    approve_alert,
    get_alert_logs,
    get_alert_rules,
    get_all_alert_rules,
    get_false_positives,
    get_pending_alerts,
    mark_alerts_read,
    reject_alert,
    save_alert_log,
    save_alert_rule,
    save_false_positive,
)
from intelligence.db.repo_memory import (
    get_conversation_summaries,
    get_user_profile,
    save_conversation_summary,
    save_user_profile,
)
from intelligence.db.repo_torrent import (
    get_recent_info_hashs,
    get_recent_torrents,
    get_torrent_by_hash,
)
from intelligence.db.repo_trace import (
    get_evaluations,
    get_traces,
    save_evaluation,
    save_trace,
)

__all__ = [
    "get_db",
    # torrent
    "get_recent_torrents", "get_torrent_by_hash", "get_recent_info_hashs",
    # alert
    "save_alert_rule", "get_alert_rules", "get_all_alert_rules",
    "save_alert_log", "get_alert_logs", "mark_alerts_read",
    "get_pending_alerts", "approve_alert", "reject_alert",
    "save_false_positive", "get_false_positives",
    # memory
    "save_conversation_summary", "get_conversation_summaries",
    "save_user_profile", "get_user_profile",
    # trace
    "save_trace", "get_traces", "save_evaluation", "get_evaluations",
]
