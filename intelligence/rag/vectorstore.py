"""
RAG 模块：向量化存储 + 语义检索
"""
import chromadb
from sentence_transformers import SentenceTransformer
from config import CHROMA_PATH, CHROMA_COLLECTION, EMBED_MODEL


# 单例，避免重复加载模型（模型文件较大）
_embed_model = None
_chroma_client = None
_collection = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        print(f"[RAG] 加载 Embedding 模型: {EMBED_MODEL}")
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
    """将种子记录转成可向量化的文本。"""
    name = torrent.get("name", "")
    files = torrent.get("files", [])
    file_names = " ".join([f[0] if isinstance(f, list) else str(f) for f in files[:10]])
    summary = torrent.get("external_summary", "")
    return f"种子名称: {name} 文件: {file_names} 外部信息: {summary}"


def index_torrents(torrents: list[dict]):
    """
    批量向量化种子数据存入 ChromaDB。
    Day 2 任务：从 MongoDB 读取数据后调用此函数。
    """
    collection = _get_collection()
    model = _get_embed_model()

    texts, ids, metadatas = [], [], []
    for t in torrents:
        info_hash = t.get("info_hash", "")
        if not info_hash:
            continue
        # 跳过已索引的
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
        print("[RAG] 无新数据需要索引")
        return

    embeddings = model.encode(texts).tolist()
    collection.add(embeddings=embeddings, ids=ids, metadatas=metadatas, documents=texts)
    print(f"[RAG] 已索引 {len(texts)} 条记录")


def search(query: str, top_k: int = 5) -> list[dict]:
    """
    语义搜索：输入自然语言，返回最相关的种子列表。
    """
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
            "relevance": round(1 - results["distances"][0][i], 3),  # 余弦相似度转相关度
        })

    return output


if __name__ == "__main__":
    # 测试：从 MongoDB 读取并索引
    from db.mongo_client import get_recent_torrents
    torrents = get_recent_torrents(limit=200)
    index_torrents(torrents)

    results = search("Python 编程教程")
    for r in results:
        print(r["relevance"], r["name"])
