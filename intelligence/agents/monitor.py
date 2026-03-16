"""
Monitor Agent — 后台监控新入库种子，匹配告警关键词并触发告警
两种运行模式：
1. 定时轮询（通用）：每隔 N 秒扫描 MongoDB 新增记录
2. Change Stream（需要 replica set）：实时监听新增
"""
import re
import threading
import logging
from datetime import datetime, timedelta

from config import SIGNAL_KEYWORDS
from db.mongo_client import (
    get_db, get_all_alert_rules, save_alert_log, get_recent_torrents,
)

logger = logging.getLogger(__name__)

# 轮询间隔（秒）
_POLL_INTERVAL = 60

# 全局状态
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()
# 告警回调：外部（如 UI）可注册，签名 callback(alert_log: dict)
_alert_callbacks: list = []


def on_alert(callback):
    """注册告警回调，每次触发告警时调用。"""
    _alert_callbacks.append(callback)


def _build_signal_pattern() -> re.Pattern:
    """将 SIGNAL_KEYWORDS 合并成一个正则，用于快速匹配。"""
    all_words = []
    for words in SIGNAL_KEYWORDS.values():
        all_words.extend(words)
    return re.compile("|".join(re.escape(w) for w in all_words), re.IGNORECASE)


_signal_pattern = _build_signal_pattern()


def _match_torrent(torrent: dict, user_rules: list[dict]) -> list[dict]:
    """
    对单条种子记录做关键词匹配，返回触发的告警列表。
    匹配源：种子名称 + 文件名
    匹配规则：用户自定义关键词 + 全局信号词 SIGNAL_KEYWORDS
    """
    name = torrent.get("name", "")
    files = torrent.get("files", [])
    # 拼接所有文件名
    file_names = []
    for f in files[:20]:
        if isinstance(f, dict):
            file_names.append(f.get("path", ""))
        elif isinstance(f, list) and f:
            file_names.append(str(f[0]))
        else:
            file_names.append(str(f))
    searchable = f"{name} {' '.join(file_names)}".lower()

    alerts = []
    now = datetime.now()
    info_hash = torrent.get("info_hash", "")

    # 1. 全局信号词匹配
    signal_matches = _signal_pattern.findall(searchable)
    if signal_matches:
        # 找出属于哪个分类
        matched_categories = set()
        for cat, words in SIGNAL_KEYWORDS.items():
            for w in words:
                if w.lower() in searchable:
                    matched_categories.add(cat)
        alerts.append({
            "type": "signal",
            "user_id": "__system__",
            "info_hash": info_hash,
            "torrent_name": name[:200],
            "matched_keywords": list(set(m.lower() for m in signal_matches)),
            "categories": list(matched_categories),
            "triggered_at": now,
            "read": False,
        })

    # 2. 用户自定义关键词匹配
    for rule in user_rules:
        user_id = rule.get("user_id", "")
        keywords = rule.get("keywords", [])
        if not keywords:
            continue
        matched = [kw for kw in keywords if kw.lower() in searchable]
        if matched:
            alerts.append({
                "type": "user",
                "user_id": user_id,
                "info_hash": info_hash,
                "torrent_name": name[:200],
                "matched_keywords": matched,
                "categories": [],
                "triggered_at": now,
                "read": False,
            })

    return alerts


def _check_batch(torrents: list[dict]) -> int:
    """对一批种子做告警检测，返回触发的告警数。"""
    if not torrents:
        return 0

    user_rules = get_all_alert_rules()
    total_alerts = 0

    for torrent in torrents:
        alerts = _match_torrent(torrent, user_rules)
        for alert in alerts:
            save_alert_log(alert)
            total_alerts += 1
            for cb in _alert_callbacks:
                try:
                    cb(alert)
                except Exception:
                    pass

    if total_alerts:
        logger.info(f"[Monitor] 检测到 {total_alerts} 条告警")
    return total_alerts


def _poll_loop():
    """定时轮询：每隔 _POLL_INTERVAL 秒扫描最近新增的种子。"""
    logger.info(f"[Monitor] 轮询启动，间隔 {_POLL_INTERVAL}s")
    # 记录上次扫描时间，避免重复检测
    last_scan = datetime.now()

    while not _monitor_stop.wait(timeout=_POLL_INTERVAL):
        try:
            # 拉取上次扫描后新增的种子
            db = get_db()
            new_torrents = list(
                db.bt_infos.find(
                    {"date": {"$gt": last_scan}},
                    {"_id": 0},
                ).sort("date", -1).limit(200)
            )
            if new_torrents:
                _check_batch(new_torrents)
                last_scan = datetime.now()
        except Exception as e:
            logger.warning(f"[Monitor] 轮询出错: {e}")

    logger.info("[Monitor] 轮询已停止")


def _stream_loop():
    """Change Stream 模式：实时监听新增种子。"""
    logger.info("[Monitor] 尝试启动 Change Stream...")
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
    """
    启动 Monitor Agent 后台线程。
    use_stream=True 尝试用 Change Stream，否则用定时轮询。
    """
    global _monitor_thread
    if _monitor_thread is not None and _monitor_thread.is_alive():
        logger.info("[Monitor] 已在运行")
        return

    _monitor_stop.clear()
    target = _stream_loop if use_stream else _poll_loop
    _monitor_thread = threading.Thread(target=target, daemon=True, name="monitor-agent")
    _monitor_thread.start()


def stop():
    """停止 Monitor Agent。"""
    _monitor_stop.set()


def is_running() -> bool:
    return _monitor_thread is not None and _monitor_thread.is_alive()
