"""RAG 模块：向量化存储 + 语义检索。"""
import logging
import chromadb
from sentence_transformers import SentenceTransformer
from intelligence.config import CHROMA_PATH, CHROMA_COLLECTION, EMBED_MODEL

logger = logging.getLogger("intelligence.rag")

_embed_model = None
_chroma_client = None
_collection = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        logger.info(f"加载 Embedding 模型: {EMBED_MODEL}")
        _embed_model = SentenceTransformer(EMBED_MODEL)
    return _embed_model


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _chroma_client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _torrent_to_text(torrent: dict) -> str:
    name = torrent.get("name", "")
    files = torrent.get("files", [])
    file_names = " ".join([f[0] if isinstance(f, list) else str(f) for f in files[:10]])
    summary = torrent.get("external_summary", "")
    return f"种子名称: {name} 文件: {file_names} 外部信息: {summary}"


def index_torrents(torrents: list[dict]):
    """批量向量化种子数据存入 ChromaDB。"""
    collection = _get_collection()
    model = _get_embed_model()

    texts, ids, metadatas = [], [], []
    for t in torrents:
        info_hash = t.get("info_hash", "")
        if not info_hash:
            continue
        existing = collection.get(ids=[info_hash])
        if existing["ids"]:
            continue

        texts.append(_torrent_to_text(t))
        ids.append(info_hash)
        metadatas.append({
            "name": t.get("name", ""),
            "magnet": t.get("magnet", ""),
            "date": str(t.get("date", "")),
        })

    if not texts:
        return

    embeddings = model.encode(texts).tolist()
    collection.add(embeddings=embeddings, ids=ids, metadatas=metadatas, documents=texts)
    logger.info(f"已索引 {len(texts)} 条记录")


def search(query: str, top_k: int = 5) -> list[dict]:
    """语义搜索：输入自然语言，返回最相关的种子列表。"""
    collection = _get_collection()
    model = _get_embed_model()

    embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "info_hash": results["ids"][0][i],
            "name": results["metadatas"][0][i].get("name", ""),
            "magnet": results["metadatas"][0][i].get("magnet", ""),
            "date": results["metadatas"][0][i].get("date", ""),
            "relevance": round(1 - results["distances"][0][i], 3),
        })
    return output
