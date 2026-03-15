import os
from dotenv import load_dotenv

# 优先读项目根 .env，其次读 intelligence/ 目录下的 .env
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))
load_dotenv()  # fallback：intelligence/.env（如果有的话）

# LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-haiku-4-5-20251001"  # 快且便宜，适合开发阶段

# MongoDB（复用爬虫数据库）
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", 27017))
MONGO_DB = "dht"

# ChromaDB
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
CHROMA_COLLECTION = "dht_intelligence"

# Embedding
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # 支持中文

# 触发检测关键词
SIGNAL_KEYWORDS = {
    "leak":     ["leak", "internal", "confidential", "unreleased", "private", "泄露"],
    "crack":    ["crack", "keygen", "patch", "activator", "bypass"],
    "document": ["whitepaper", "report", "confidential", ".pdf", ".docx"],
    "malware":  ["trojan", "ransomware", "payload", "backdoor"],
}
