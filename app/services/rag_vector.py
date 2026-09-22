# -*- coding: utf-8 -*-
"""公告 RAG 向量库封装

向量库: ChromaDB（嵌入式持久化，零运维）
  - 数据目录: data/vector_db/chroma
  - 集合: announcements，按 (ann_id, chunk_index) 去重 upsert
Embedding: DashScope text-embedding-v4（走 OpenAI 兼容端点，与课程一致）

核心函数:
  upsert_ann_chunks() / query_announcements() / delete_ann() / collection_count()
"""
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# 固定嵌入维度（text-embedding-v4 支持 256/768/1024/2048/3072）
# 一旦集合创建，维度不可变，后续需保持一致
EMBEDDING_DIM = 768


def _client():
    """DashScope OpenAI 兼容客户端（懒加载，未配 key 时抛清晰错误）

    - 禁用环境/系统代理（DashScope 国内服务，直连更快更稳）
    - 设置超时，避免请求无限卡死
    """
    import httpx
    from openai import OpenAI

    key = settings.DASHSCOPE_API_KEY
    if not key:
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY，请在 .env 中配置（通义千问 DashScope API Key）"
        )
    return OpenAI(
        api_key=key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=httpx.Timeout(60.0, connect=15.0),
        http_client=httpx.Client(trust_env=False),
    )


def get_embeddings(texts: list[str], batch_size: int = 10) -> list[list[float]]:
    """批量文本 -> 向量（text-embedding-v4），自动分片（DashScope 单批上限 10 条）"""
    client = _client()
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIM,
        )
        # 按输入顺序返回
        ordered = sorted(resp.data, key=lambda x: x.index)
        out.extend(item.embedding for item in ordered)
    return out


def get_collection():
    """获取（或创建）公告向量集合，惰性导入 chromadb"""
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except ImportError:
        logger.warning("chromadb 未安装，向量检索功能不可用。安装方式: pip install chromadb")
        return None

    client = chromadb.PersistentClient(
        path=str(settings.VECTOR_DB_DIR / "chroma"),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name="announcements",
        metadata={"hnsw:space": "cosine"},  # 余弦相似度
    )


def _norm_date(d) -> int:
    """日期归一化为 YYYYMMDD 整数，确保 Chroma 元数据比较类型一致。"""
    if d is None:
        return 0
    s = str(d).replace("-", "").replace("/", "")[:8]
    try:
        return int(s)
    except (TypeError, ValueError):
        return 0


def upsert_ann_chunks(
    ann_id: int,
    chunks: list[str],
    *,
    stock_code: str,
    stock_name: str,
    ann_title: str,
    ann_date=None,
    ann_type: str = "",
    source: str = "eastmoney",
    is_important: int = 0,
) -> int:
    """将公告的切块写入向量库（同公告重复写入自动覆盖）

    返回写入 chunk 数
    """
    if not chunks:
        return 0
    coll = get_collection()
    if coll is None:
        logger.warning("[rag] chromadb 不可用，跳过向量写入")
        return 0
    # 用 DashScope 向量显式写入（避免 chromadb 默认英文模型 all-MiniLM）
    vecs = get_embeddings(chunks)
    ids = [f"{ann_id}-{i}" for i in range(len(chunks))]
    metas = [
        {
            "ann_id": str(ann_id),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "ann_title": ann_title,
            "ann_date": _norm_date(ann_date),
            "ann_type": str(ann_type or ""),
            "source": source,
            "is_important": int(is_important),
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]
    coll.upsert(ids=ids, embeddings=vecs, documents=chunks, metadatas=metas)
    logger.info("[rag] 写入公告 %s 共 %d 个切块", ann_id, len(chunks))
    return len(chunks)


def query_announcements(
    query: str,
    *,
    stock_code: Optional[str] = None,
    only_important: bool = False,
    start_date=None,
    end_date=None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """语义检索公告切块

    支持按股票 / 重要程度 / 日期区间过滤（Chroma metadata where）
    返回 [{ann_id, stock_code, stock_name, ann_title, ann_date, source,
           is_important, chunk, chunk_index, score}, ...]
    """
    coll = get_collection()
    if coll is None:
        logger.warning("[rag] chromadb 不可用，返回空结果")
        return []
    where: dict = {}
    if stock_code:
        where["stock_code"] = str(stock_code).split(".")[0]
    if only_important:
        where["is_important"] = 1
    date_filters: list[dict] = []
    if start_date:
        date_filters.append({"ann_date": {"$gte": _norm_date(start_date)}})
    if end_date:
        date_filters.append({"ann_date": {"$lte": _norm_date(end_date)}})
    if date_filters:
        where = {"$and": [where, *date_filters]} if where else date_filters[0] if len(date_filters) == 1 else {"$and": date_filters}

    try:
        # 用 DashScope 生成查询向量，避免 chromadb 默认英文模型
        qvec = get_embeddings([query])[0]
        res = coll.query(
            query_embeddings=[qvec],
            n_results=top_k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:  # noqa: BLE001 集合为空时查询会报错
        logger.exception(
            "[rag] 检索失败 query=%r stock_code=%s only_important=%s "
            "start_date=%s end_date=%s top_k=%s",
            query,
            stock_code or "-",
            only_important,
            start_date or "-",
            end_date or "-",
            top_k,
        )
        return []

    out: list[dict[str, Any]] = []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        m = meta or {}
        out.append({
            "ann_id": m.get("ann_id"),
            "stock_code": m.get("stock_code"),
            "stock_name": m.get("stock_name"),
            "ann_title": m.get("ann_title"),
            "ann_date": m.get("ann_date"),
            "source": m.get("source"),
            "is_important": m.get("is_important"),
            "chunk_index": m.get("chunk_index"),
            "chunk": doc,
            # Chroma 返回 distance（余弦距离），转相似度
            "score": round(1 - float(dist), 4),
        })
    return out


def delete_ann(ann_id: int) -> int:
    """删除某公告的全部切块（重同步前调用）"""
    coll = get_collection()
    if coll is None:
        logger.warning("[rag] chromadb 不可用，跳过删除操作")
        return 0
    coll.delete(where={"ann_id": str(ann_id)})
    return 0


def collection_count() -> int:
    """当前向量库切块总数"""
    try:
        coll = get_collection()
        if coll is None:
            return 0
        return coll.count()
    except Exception:  # noqa: BLE001
        return 0
