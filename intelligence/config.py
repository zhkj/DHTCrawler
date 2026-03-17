import os
import logging
from dotenv import load_dotenv

# 优先读项目根 .env，其次读 intelligence/ 目录下的 .env
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))
load_dotenv()  # fallback：intelligence/.env（如果有的话）

# ── 日志 ──────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.path.join(_root, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_datefmt = "%Y-%m-%d %H:%M:%S"

# 根 logger：intelligence 命名空间
_root_logger = logging.getLogger("intelligence")
_root_logger.setLevel(LOG_LEVEL)

# 控制台输出
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter(_log_format, datefmt=_log_datefmt))
_root_logger.addHandler(_console)

# 文件输出
_file = logging.FileHandler(os.path.join(LOG_DIR, "intelligence.log"), encoding="utf-8")
_file.setFormatter(logging.Formatter(_log_format, datefmt=_log_datefmt))
_root_logger.addHandler(_file)

# LLM（使用通义千问 OpenAI 兼容接口）
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-flash")

# MongoDB（复用爬虫数据库）
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB = "dht"

# ChromaDB
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = "dht_intelligence"

# Embedding
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # 支持中文

# 告警推送（留空则不推送该渠道）
NOTIFY_FEISHU_WEBHOOK = os.getenv("NOTIFY_FEISHU_WEBHOOK", "")
NOTIFY_DINGTALK_WEBHOOK = os.getenv("NOTIFY_DINGTALK_WEBHOOK", "")
NOTIFY_TELEGRAM_TOKEN = os.getenv("NOTIFY_TELEGRAM_TOKEN", "")
NOTIFY_TELEGRAM_CHAT_ID = os.getenv("NOTIFY_TELEGRAM_CHAT_ID", "")

# 触发检测关键词
SIGNAL_KEYWORDS = {
    "leak":     ["leak", "internal", "confidential", "unreleased", "private", "泄露"],
    "crack":    ["crack", "keygen", "patch", "activator", "bypass"],
    "document": ["whitepaper", "report", "confidential", ".pdf", ".docx"],
    "malware":  ["trojan", "ransomware", "payload", "backdoor"],
}
