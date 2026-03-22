"""
Monitor Agent — 后台监控新入库种子，匹配告警关键词并触发告警。
支持 Human-in-the-Loop：高置信自动推送，中低置信待人工审批。
"""
import logging
import re
import threading
from datetime import datetime

from intelligence.config import SIGNAL_KEYWORDS
from intelligence.db import (
    get_all_alert_rules,
    get_db,
    save_alert_log,
)
from intelligence.monitor.confidence import refresh_false_positives
from intelligence.monitor.confidence import score as score_confidence
from intelligence.notify import push_all as _notify_push_all
from intelligence.notify.dispatcher import push_pending_review

logger = logging.getLogger("intelligence.monitor")

_POLL_INTERVAL = 60
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()
_alert_callbacks: list = []


def on_alert(callback):
    _alert_callbacks.append(callback)


def _build_signal_pattern() -> re.Pattern:
    all_words = []
    for words in SIGNAL_KEYWORDS.values():
        all_words.extend(words)
    return re.compile("|".join(re.escape(w) for w in all_words), re.IGNORECASE)


_signal_pattern = _build_signal_pattern()


def _normalize_text(text: str) -> str:
    """标准化文本：统一分隔符、转小写。"""
    text = text.lower()
    text = re.sub(r'[_\-./\\]', ' ', text)  # normalize separators
    return text


def _simple_stem(word: str) -> str:
    """简单词干化：去除常见英文后缀。"""
    word = word.lower()
    for suffix in ('ing', 'ed', 'er', 'ers', 's', 'es', 'tion', 'ment'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _match_torrent(torrent: dict, user_rules: list[dict]) -> list[dict]:
    name = torrent.get("name", "")
    files = torrent.get("files", [])
    file_names = []
    for f in files[:20]:
        if isinstance(f, dict):
            file_names.append(f.get("path", ""))
        elif isinstance(f, list) and f:
            file_names.append(str(f[0]))
        else:
            file_names.append(str(f))
    searchable = _normalize_text(f"{name} {' '.join(file_names)}")

    alerts = []
    now = datetime.now()
    info_hash = torrent.get("info_hash", "")

    # 1. 全局信号词匹配
    signal_matches = _signal_pattern.findall(searchable)
    matched_categories: set[str] = set()

    # Also check stemmed versions of signal keywords
    for cat, words in SIGNAL_KEYWORDS.items():
        for w in words:
            stem = _simple_stem(w)
            if stem in searchable or w.lower() in searchable:
                matched_categories.add(cat)
                if w.lower() not in [m.lower() for m in signal_matches]:
                    signal_matches.append(w)

    if signal_matches:
        matched_kws = list(set(m.lower() for m in signal_matches))
        cats = list(matched_categories)
        confidence = score_confidence(matched_kws, cats, is_user_rule=False)
        status = "active" if confidence == "high" else "pending_review"

        alerts.append({
            "type": "signal",
            "user_id": "__system__",
            "info_hash": info_hash,
            "torrent_name": name[:200],
            "matched_keywords": matched_kws,
            "categories": cats,
            "confidence": confidence,
            "status": status,
            "triggered_at": now,
            "read": False,
        })

    # 2. 用户自定义关键词匹配
    for rule in user_rules:
        user_id = rule.get("user_id", "")
        keywords = rule.get("keywords", [])
        if not keywords:
            continue
        matched = []
        for kw in keywords:
            kw_lower = kw.lower()
            kw_stem = _simple_stem(kw_lower)
            if kw_lower in searchable or kw_stem in searchable:
                matched.append(kw)
        if matched:
            confidence = score_confidence(matched, [], is_user_rule=True)
            alerts.append({
                "type": "user",
                "user_id": user_id,
                "info_hash": info_hash,
                "torrent_name": name[:200],
                "matched_keywords": matched,
                "categories": [],
                "confidence": confidence,
                "status": "active",
                "triggered_at": now,
                "read": False,
            })

    return alerts


def _check_batch(torrents: list[dict]) -> int:
    if not torrents:
        return 0

    user_rules = get_all_alert_rules()
    total_alerts = 0

    for torrent in torrents:
        alerts = _match_torrent(torrent, user_rules)
        for alert in alerts:
            save_alert_log(alert)
            total_alerts += 1

            if alert["status"] == "active":
                for cb in _alert_callbacks:
                    try:
                        cb(alert)
                    except Exception:
                        pass
            else:
                try:
                    push_pending_review(alert)
                except Exception:
                    pass

    if total_alerts:
        logger.info(f"[Monitor] 检测到 {total_alerts} 条告警")
    return total_alerts


def _poll_loop():
    logger.info(f"[Monitor] 轮询启动，间隔 {_POLL_INTERVAL}s")
    last_scan = datetime.now()
    refresh_false_positives()

    poll_count = 0
    while not _monitor_stop.wait(timeout=_POLL_INTERVAL):
        try:
            db = get_db()
            new_torrents = list(
                db.bt_infos.find(
                    {"date": {"$gt": last_scan}}, {"_id": 0},
                ).sort("date", -1).limit(200)
            )
            if new_torrents:
                _check_batch(new_torrents)
                last_scan = datetime.now()

            poll_count += 1
            if poll_count % 10 == 0:
                refresh_false_positives()

        except Exception as e:
            logger.warning(f"[Monitor] 轮询出错: {e}")

    logger.info("[Monitor] 轮询已停止")


def _stream_loop():
    logger.info("[Monitor] 尝试启动 Change Stream...")
    refresh_false_positives()
    try:
        db = get_db()
        with db.bt_infos.watch(
            [{"$match": {"operationType": "insert"}}],
            full_document="updateLookup",
        ) as stream:
            logger.info("[Monitor] Change Stream 已连接")
            for change in stream:
                if _monitor_stop.is_set():
                    break
                doc = change.get("fullDocument")
                if doc:
                    doc.pop("_id", None)
                    _check_batch([doc])
    except Exception as e:
        logger.warning(f"[Monitor] Change Stream 不可用 ({e})，回退到轮询")
        _poll_loop()


def start(use_stream: bool = False):
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return

    if _notify_push_all not in _alert_callbacks:
        _alert_callbacks.append(_notify_push_all)

    _monitor_stop.clear()
    target = _stream_loop if use_stream else _poll_loop
    _monitor_thread = threading.Thread(target=target, daemon=True, name="monitor-agent")
    _monitor_thread.start()


def stop():
    _monitor_stop.set()


def is_running() -> bool:
    return _monitor_thread is not None and _monitor_thread.is_alive()
