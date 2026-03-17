"""
Monitor Agent — 后台监控新入库种子，匹配告警关键词并触发告警
支持 Human-in-the-Loop：置信度评分 → 高置信自动推送，中低置信待人工审批

两种运行模式：
1. 定时轮询（通用）：每隔 N 秒扫描 MongoDB 新增记录
2. Change Stream（需要 replica set）：实时监听新增
"""
import re
import threading
import logging
from datetime import datetime

from config import SIGNAL_KEYWORDS
from db.mongo_client import (
    get_db, get_all_alert_rules, save_alert_log, get_recent_torrents,
    get_false_positives, save_false_positive,
)
from agents.notifier import push_all as _notify_push_all, push_pending_review

logger = logging.getLogger("intelligence.monitor")

# 轮询间隔（秒）
_POLL_INTERVAL = 60

# 全局状态
_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()
# 告警回调：外部（如 UI）可注册，签名 callback(alert_log: dict)
_alert_callbacks: list = []
# 误报关键词缓存（定期从 MongoDB 刷新）
_false_positive_keywords: set = set()


def on_alert(callback):
    """注册告警回调，每次触发告警时调用。"""
    _alert_callbacks.append(callback)


def _refresh_false_positives():
    """从 MongoDB 刷新误报关键词缓存（count >= 2 视为高频误报）。"""
    global _false_positive_keywords
    try:
        fps = get_false_positives()
        _false_positive_keywords = {
            fp["keyword"].lower() for fp in fps if fp.get("count", 0) >= 2
        }
    except Exception:
        pass


def _build_signal_pattern() -> re.Pattern:
    """将 SIGNAL_KEYWORDS 合并成一个正则，用于快速匹配。"""
    all_words = []
    for words in SIGNAL_KEYWORDS.values():
        all_words.extend(words)
    return re.compile("|".join(re.escape(w) for w in all_words), re.IGNORECASE)


_signal_pattern = _build_signal_pattern()


# ── 置信度评分 ──────────────────────────────────────────────────────

def _score_confidence(matched_keywords: list[str], categories: list[str],
                      is_user_rule: bool) -> str:
    """
    根据匹配情况计算告警置信度。
    返回: "high" / "medium" / "low"

    评分规则：
    - 用户自定义规则命中 → high（用户明确关注的）
    - 系统信号词命中 3+ 关键词 或 2+ 分类 → high
    - 系统信号词命中 2 关键词 或 1 分类含多关键词 → medium
    - 仅 1 个泛化关键词命中 → low
    """
    if is_user_rule:
        return "high"

    # 过滤掉已知误报关键词
    effective_keywords = [
        kw for kw in matched_keywords
        if kw.lower() not in _false_positive_keywords
    ]
    if not effective_keywords:
        return "low"

    n_keywords = len(effective_keywords)
    n_categories = len(categories)

    if n_keywords >= 3 or n_categories >= 2:
        return "high"
    if n_keywords >= 2 or (n_categories >= 1 and n_keywords >= 1):
        return "medium"
    return "low"


def _match_torrent(torrent: dict, user_rules: list[dict]) -> list[dict]:
    """
    对单条种子记录做关键词匹配，返回触发的告警列表。
    每条告警包含 confidence 评分和 status 字段。
    """
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
    searchable = f"{name} {' '.join(file_names)}".lower()

    alerts = []
    now = datetime.now()
    info_hash = torrent.get("info_hash", "")

    # 1. 全局信号词匹配
    signal_matches = _signal_pattern.findall(searchable)
    if signal_matches:
        matched_categories = set()
        for cat, words in SIGNAL_KEYWORDS.items():
            for w in words:
                if w.lower() in searchable:
                    matched_categories.add(cat)

        matched_kws = list(set(m.lower() for m in signal_matches))
        cats = list(matched_categories)
        confidence = _score_confidence(matched_kws, cats, is_user_rule=False)

        # high → 自动推送(active)，medium/low → 待审批(pending_review)
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
        matched = [kw for kw in keywords if kw.lower() in searchable]
        if matched:
            confidence = _score_confidence(matched, [], is_user_rule=True)
            alerts.append({
                "type": "user",
                "user_id": user_id,
                "info_hash": info_hash,
                "torrent_name": name[:200],
                "matched_keywords": matched,
                "categories": [],
                "confidence": confidence,
                "status": "active",  # 用户规则始终直接推送
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

            if alert["status"] == "active":
                # 高置信度 → 直接推送所有渠道
                for cb in _alert_callbacks:
                    try:
                        cb(alert)
                    except Exception:
                        pass
            else:
                # pending_review → 推送待审批通知（飞书卡片带标记）
                try:
                    push_pending_review(alert)
                except Exception:
                    pass

    if total_alerts:
        active = sum(1 for a in [_match_torrent(t, user_rules) for t in torrents]
                     for al in a if al.get("status") == "active")
        pending = total_alerts - active
        logger.info(
            f"[Monitor] 检测到 {total_alerts} 条告警 "
            f"(auto={active}, pending={pending})"
        )
    return total_alerts


# ── Human-in-the-Loop: 审批处理 ─────────────────────────────────────

def approve_and_push(info_hash: str, user_id: str = "__system__"):
    """人工审批通过 → 触发正式推送。"""
    from db.mongo_client import approve_alert, get_db
    approve_alert(info_hash, user_id)

    # 查找该告警记录并推送
    db = get_db()
    alert = db.alerts_log.find_one(
        {"info_hash": info_hash, "user_id": user_id},
        {"_id": 0},
    )
    if alert:
        _notify_push_all(alert)
        logger.info(f"[HITL] 告警已审批并推送: {info_hash[:16]}...")


def reject_and_learn(info_hash: str, user_id: str = "__system__",
                     reason: str = "误报"):
    """人工拒绝告警 → 记录误报反馈，优化后续匹配。"""
    from db.mongo_client import reject_alert, get_db
    reject_alert(info_hash, user_id, reason)

    # 将该告警的关键词记录为误报
    db = get_db()
    alert = db.alerts_log.find_one(
        {"info_hash": info_hash, "user_id": user_id},
        {"_id": 0},
    )
    if alert:
        for kw in alert.get("matched_keywords", []):
            save_false_positive(kw, info_hash, reason)
        logger.info(
            f"[HITL] 告警已拒绝，误报关键词已记录: "
            f"{alert.get('matched_keywords', [])}"
        )

    # 刷新误报缓存
    _refresh_false_positives()


# ── 后台轮询 ────────────────────────────────────────────────────────

def _poll_loop():
    """定时轮询：每隔 _POLL_INTERVAL 秒扫描最近新增的种子。"""
    logger.info(f"[Monitor] 轮询启动，间隔 {_POLL_INTERVAL}s")
    last_scan = datetime.now()
    _refresh_false_positives()  # 启动时加载误报缓存

    poll_count = 0
    while not _monitor_stop.wait(timeout=_POLL_INTERVAL):
        try:
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

            # 每 10 次轮询刷新一次误报缓存
            poll_count += 1
            if poll_count % 10 == 0:
                _refresh_false_positives()

        except Exception as e:
            logger.warning(f"[Monitor] 轮询出错: {e}")

    logger.info("[Monitor] 轮询已停止")


def _stream_loop():
    """Change Stream 模式：实时监听新增种子。"""
    logger.info("[Monitor] 尝试启动 Change Stream...")
    _refresh_false_positives()
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

    if _notify_push_all not in _alert_callbacks:
        _alert_callbacks.append(_notify_push_all)

    _monitor_stop.clear()
    target = _stream_loop if use_stream else _poll_loop
    _monitor_thread = threading.Thread(target=target, daemon=True, name="monitor-agent")
    _monitor_thread.start()


def stop():
    """停止 Monitor Agent。"""
    _monitor_stop.set()


def is_running() -> bool:
    return _monitor_thread is not None and _monitor_thread.is_alive()
