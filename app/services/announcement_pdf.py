# -*- coding: utf-8 -*-
"""公告 PDF 处理：取直链 -> 下载 -> 解析 -> 切块 -> 写入向量库

依赖 announcement_sync 已入库的公告记录（trade_stock_announcement），
把每条公告的 PDF 原文解析成文本切块，同步到 Chroma 向量库（rag_vector.py）。

数据源差异:
  - eastmoney: source_url 是详情页 -> 调东财内容接口取 PDF 直链(attach_url_web)
  - cninfo   : source_url 本身就是巨潮 PDF 直链(.PDF 结尾)，直接用

pdf_status 状态机:
  none -> url(拿到直链) 
  -> downloaded(下载成功) -> parsed(解析出文本) 
  -> indexed(向量化)
  error: 任一步失败; empty: 已解析但无文本(扫描件, 需 OCR)

用法:
  python -m app.services.announcement_pdf            # 同步最近 7 天待处理公告
  python -m app.services.announcement_pdf --days 3 --limit 50
"""
import argparse
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import requests

from app.config import settings
from app.database import execute_query, execute_update
from app.services import rag_vector

logger = logging.getLogger(__name__)

# 东财公告内容接口（PDF 直链在此返回，页面 JS 也是调它动态填充）
CONTENT_API = "https://np-cnotice-stock.eastmoney.com/api/content/ann"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}

CHUNK_SIZE = 600      # 每块约 600 字符
CHUNK_OVERLAP = 100   # 块间重叠 100 字符


# ---------------------------------------------------------------- schema
def ensure_schema() -> None:
    """幂等补齐 trade_stock_announcement 的 PDF 相关列（老库用）"""
    cols = {r["COLUMN_NAME"] for r in execute_query(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='trade_stock_announcement'",
        (settings.DB_NAME,),
    )}
    add_map = {
        "pdf_url": "ADD COLUMN pdf_url varchar(500) DEFAULT NULL COMMENT '公告PDF直链' AFTER source_url",
        "pdf_path": "ADD COLUMN pdf_path varchar(500) DEFAULT NULL COMMENT '本地PDF路径' AFTER pdf_url",
        "pdf_status": "ADD COLUMN pdf_status varchar(20) NOT NULL DEFAULT 'none' COMMENT 'PDF状态:none/url/downloaded/parsed/indexed/error/empty' AFTER pdf_path",
    }
    for col, ddl in add_map.items():
        if col not in cols:
            execute_update(f"ALTER TABLE trade_stock_announcement {ddl}")
            logger.info("[pdf] 已新增列 %s", col)


# ---------------------------------------------------------------- 取直链
def get_pdf_url(record: dict) -> str | None:
    """按来源取 PDF 直链

    - cninfo: source_url 即巨潮 PDF 直链
    - eastmoney: source_url 为详情页，调东财接口取 attach_url_web
    """
    source = record.get("source", "eastmoney")
    url = (record.get("source_url") or "").strip()
    if not url:
        return None
    if source == "cninfo" or url.lower().endswith(".pdf"):
        return url

    m = re.search(r"/(AN\d{15,})\.html", url)
    if not m:
        return None
    try:
        resp = requests.get(
            CONTENT_API,
            params={"art_code": m.group(1), "client_source": "web", "page_index": 1},
            headers=HEADERS, timeout=20,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        return (data.get("attach_url_web") or data.get("attach_url") or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pdf] 公告 %s 取直链失败: %s", record.get("id"), exc)
        return None


# ---------------------------------------------------------------- 下载/解析
def download_pdf(pdf_url: str, ann_id: int) -> Path | None:
    """下载 PDF 到 data/pdfs/{ann_id}.pdf"""
    save_dir = settings.PDF_DIR
    save_dir.mkdir(parents=True, exist_ok=True)
    target = save_dir / f"{ann_id}.pdf"
    try:
        resp = requests.get(pdf_url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()
        with open(target, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        return target
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pdf] 公告 %s 下载失败: %s", ann_id, exc)
        if target.exists():
            target.unlink(missing_ok=True)
        return None


def parse_pdf(pdf_path: Path) -> list[str]:
    """用 PyMuPDF 提取文本，返回按页的文本列表（扫描件返回空列表）"""
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    try:
        pages = [page.get_text("text").strip() for page in doc]
    finally:
        doc.close()
    return [p for p in pages if p]


def chunk_text(pages: list[str], chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按页顺序切块（块间重叠，保留语义连续性）"""
    chunks: list[str] = []
    buf = ""
    for page_text in pages:
        buf += page_text
        while len(buf) > chunk_size:
            chunks.append(buf[:chunk_size])
            buf = buf[chunk_size - overlap:]
    if buf.strip():
        chunks.append(buf)
    return chunks


# ---------------------------------------------------------------- 主流程
def sync_announcement_pdfs(
    lookback_days: int = 7,
    limit: int = 100,
    stock_code: str | None = None,
    only_important: bool = False,
    reindex: bool = False,
) -> dict:
    """同步公告 PDF 到向量库（断点续跑：只处理 pdf_status='none'）

    Args:
        lookback_days: 回看天数
        limit: 本批处理条数上限
        stock_code: 只处理某只股票
        only_important: 只处理重要公告
        reindex: True 则同时重处理 error/empty 状态的公告（重试）
    """
    ensure_schema()

    start = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    status_sql = "pdf_status='none'"
    if reindex:
        status_sql = "pdf_status IN ('none','error','empty','parsed')"

    sql = (
        "SELECT id, stock_code, stock_name, ann_title, ann_type, ann_date, "
        "       source, source_url, is_important FROM trade_stock_announcement "
        f"WHERE {status_sql} AND source_url IS NOT NULL AND source_url<>'' "
        "  AND ann_date>=%s"
    )
    params: list = [start]
    if stock_code:
        sql += " AND stock_code=%s"
        params.append(str(stock_code).split(".")[0])
    if only_important:
        sql += " AND is_important=1"
    sql += " ORDER BY ann_date DESC, id ASC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    logger.info("[pdf] 待处理公告 %d 条(%s~)", len(rows), start)

    stat = {"total": len(rows), "indexed": 0, "empty": 0, "error": 0, "no_pdf": 0}

    for r in rows:
        ann_id = r["id"]
        try:
            pdf_url = get_pdf_url(r)
            if not pdf_url:
                _set_status(ann_id, "error")
                stat["no_pdf"] += 1
                continue
            _set_status(ann_id, "url", pdf_url=pdf_url)

            local = download_pdf(pdf_url, ann_id)
            if not local:
                _set_status(ann_id, "error")
                stat["error"] += 1
                continue
            _set_status(ann_id, "downloaded", pdf_path=str(local))

            pages = parse_pdf(local)
            if not pages:
                _set_status(ann_id, "empty")  # 扫描件，需 OCR 后续处理
                stat["empty"] += 1
                continue
            _set_status(ann_id, "parsed")

            chunks = chunk_text(pages)
            n = rag_vector.upsert_ann_chunks(
                ann_id, chunks,
                stock_code=r["stock_code"], stock_name=r["stock_name"],
                ann_title=r["ann_title"], ann_date=r["ann_date"],
                ann_type=r["ann_type"], source=r["source"],
                is_important=1 if r.get("is_important") else 0,
            )
            if n:
                _set_status(ann_id, "indexed")
                stat["indexed"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("[pdf] 公告 %s 处理异常: %s", ann_id, exc, exc_info=True)
            _set_status(ann_id, "error")
            stat["error"] += 1

    total_chunks = rag_vector.collection_count()
    logger.info(
        "[pdf] 完成: 索引 %d / 空文本 %d / 失败 %d / 无直链 %d，向量库共 %d 块",
        stat["indexed"], stat["empty"], stat["error"], stat["no_pdf"], total_chunks,
    )
    stat["vector_chunks"] = total_chunks
    return stat


def _set_status(ann_id: int, status: str, pdf_url: str | None = None, pdf_path: str | None = None) -> None:
    """更新公告 PDF 状态"""
    sets = ["pdf_status=%s"]
    params: list = [status]
    if pdf_url is not None:
        sets.append("pdf_url=%s")
        params.append(pdf_url)
    if pdf_path is not None:
        sets.append("pdf_path=%s")
        params.append(pdf_path)
    params.append(ann_id)
    execute_update(
        f"UPDATE trade_stock_announcement SET {', '.join(sets)} WHERE id=%s",
        params,
    )


def query_pdf_records(stock_code: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    """查询公告 PDF 处理状态（供 API 使用）"""
    sql = "SELECT id, stock_code, stock_name, ann_title, ann_date, source, source_url, pdf_url, pdf_path, pdf_status FROM trade_stock_announcement WHERE 1=1"
    params: list = []
    if stock_code:
        sql += " AND stock_code=%s"
        params.append(str(stock_code).split(".")[0])
    if status:
        sql += " AND pdf_status=%s"
        params.append(status)
    sql += " ORDER BY ann_date DESC, id DESC LIMIT %s"
    params.append(limit)
    return execute_query(sql, params)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="公告 PDF 同步到向量库")
    parser.add_argument("--days", type=int, default=7, help="回看天数")
    parser.add_argument("--limit", type=int, default=100, help="本批处理条数")
    parser.add_argument("--code", default=None, help="只处理某只股票")
    parser.add_argument("--important", action="store_true", help="只处理重要公告")
    parser.add_argument("--reindex", action="store_true", help="重试 error/empty 记录")
    args = parser.parse_args()

    result = sync_announcement_pdfs(
        lookback_days=args.days, limit=args.limit,
        stock_code=args.code, only_important=args.important, reindex=args.reindex,
    )
    print("PDF 同步结果:", result)
