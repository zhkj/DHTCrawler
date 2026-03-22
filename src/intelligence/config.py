import logging
import os

from dotenv import load_dotenv

# 加载项目根 .env
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(_root, ".env"))

# ── 日志 ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.path.join(_root, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_datefmt = "%Y-%m-%d %H:%M:%S"

_root_logger = logging.getLogger("intelligence")
_root_logger.setLevel(LOG_LEVEL)

_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter(_log_format, datefmt=_log_datefmt))
_root_logger.addHandler(_console)

_file = logging.FileHandler(os.path.join(LOG_DIR, "intelligence.log"), encoding="utf-8")
_file.setFormatter(logging.Formatter(_log_format, datefmt=_log_datefmt))
_root_logger.addHandler(_file)

# ── LLM ───────────────────────────────────────────────────────────
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-flash")

# ── MongoDB ───────────────────────────────────────────────────────
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB = "dht"

# ── BM25 ─────────────────────────────────────────────────────────
BM25_INIT_LIMIT = int(os.getenv("BM25_INIT_LIMIT", 10000))

# ── ChromaDB ──────────────────────────────────────────────────────
CHROMA_PATH = os.getenv("CHROMA_PATH", os.path.join(_root, "chroma_db"))
CHROMA_COLLECTION = "dht_intelligence"

# ── Embedding ─────────────────────────────────────────────────────
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# ── 告警推送 ──────────────────────────────────────────────────────
NOTIFY_FEISHU_WEBHOOK = os.getenv("NOTIFY_FEISHU_WEBHOOK", "")
NOTIFY_DINGTALK_WEBHOOK = os.getenv("NOTIFY_DINGTALK_WEBHOOK", "")
NOTIFY_TELEGRAM_TOKEN = os.getenv("NOTIFY_TELEGRAM_TOKEN", "")
NOTIFY_TELEGRAM_CHAT_ID = os.getenv("NOTIFY_TELEGRAM_CHAT_ID", "")

# ── 信号关键词 ────────────────────────────────────────────────────
SIGNAL_KEYWORDS = {
    "leak":     ["leak", "internal", "confidential", "unreleased", "private", "泄露"],
    "crack":    ["crack", "keygen", "patch", "activator", "bypass"],
    "document": ["whitepaper", "report", "confidential", ".pdf", ".docx"],
    "malware":  ["trojan", "ransomware", "payload", "backdoor"],
}
