# -*- coding: utf-8 -*-
"""上市公司公告同步

写入表: trade_stock_announcement

两个数据源（互补）：
  1. sync_announcement_daily()  —— 东财全市场增量
     ak.stock_notice_report(symbol='全部', date=YYYYMMDD)
     每天一次拉全市场公告（含东财 8 大类分类），覆盖广、省请求。
  2. track_stock_announcements() —— 巨潮 cninfo 股票池精确追踪
     ak.stock_zh_a_disclosure_report_cninfo(symbol, market, keyword, category, start, end)
     按股票池逐股拉官方一手公告，可按巨潮 27 类精确筛选，权威性高。

通用：标题关键词打标 is_important（业绩预告/减持/解禁/重组/立案等硬信号）。
"""
import logging
from datetime import date, datetime, timedelta

from app.database import execute_many, execute_query

logger = logging.getLogger(__name__)

# 重要公告关键词 -> (是否利好, 信号)
IMPORTANT_KEYWORDS: list[tuple[str, str]] = [
    ("业绩预告", "业绩预告"),
    ("业绩快报", "业绩快报"),
    ("预增", "业绩预增"),
    ("预减", "业绩预减"),
    ("扭亏", "业绩扭亏"),
    ("减持", "股东减持"),
    ("增持", "股东增持"),
    ("回购", "股份回购"),
    ("解禁", "限售解禁"),
    ("重组", "资产重组"),
    ("重大资产", "资产重组"),
    ("立案", "立案调查"),
    ("处罚", "监管处罚"),
    ("违规", "违规"),
    ("退市", "退市风险"),
    ("风险警示", "风险警示"),
    ("中标", "重大合同"),
    ("签署", "重大合同"),
    ("股权激励", "股权激励"),
    ("分红", "分红"),
    ("送转", "分红送转"),
    ("要约收购", "要约收购"),
    ("控制权", "控制权变更"),
    ("破产", "破产重整"),
]

# cninfo 重点分类（巨潮官方 27 类中的硬信号类），供 track 默认筛选
# 注意：必须与 akshare 巨潮分类字典完全一致（无"业绩快报"，只有"业绩预告"）
TRACK_CATEGORIES: list[str] = [
    "业绩预告",
    "权益分派",
    "股权变动",
    "解禁",
    "增发",
    "股权激励",
    "风险提示",
    "特别处理和退市",
]


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _fmt_date(d) -> str:
    """date/datetime/str -> YYYYMMDD"""
    if isinstance(d, str):
        return d.replace("-", "")
    return d.strftime("%Y%m%d")


def _clean_stock_code(code: str) -> str:
    return str(code).split(".")[0].strip()


def _mark_important(title: str) -> tuple[int, str | None]:
    """根据标题关键词判断是否重要公告，返回 (is_important, 命中的关键词csv)"""
    hits = [kw for kw, _ in IMPORTANT_KEYWORDS if kw in title]
    return (1, ",".join(hits)) if hits else (0, None)


def sync_announcement_daily(start_date=None, end_date=None, lookback_days: int = 3) -> dict:
    """东财全市场公告增量同步（每日拉最近 N 天）

    Args:
        start_date: 起始日期 YYYYMMDD/YYYY-MM-DD/date，默认今天向前 lookback_days 天
        end_date:   结束日期，默认今天
        lookback_days: 默认回看天数（覆盖周末/节假日）
    """
    import akshare as ak

    end = _fmt_date(end_date or date.today())
    start = _fmt_date(start_date or (date.today() - timedelta(days=lookback_days)))

    # 逐日拉取（东财接口只支持单日）
    rows_all: list[tuple] = []
    day = datetime.strptime(start, "%Y%m%d").date()
    end_d = datetime.strptime(end, "%Y%m%d").date()
    days = []
    while day <= end_d:
        days.append(day)
        day += timedelta(days=1)

    for d in days:
        try:
            df = ak.stock_notice_report(symbol="全部", date=d.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001 单日失败不阻塞整体
            logger.warning("[公告] 东财 %s 拉取失败，跳过", d, exc_info=True)
            continue
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            title = str(r.get("公告标题", "") or "").strip()
            code = _clean_stock_code(str(r.get("代码", "")))
            if not title or not code:
                continue
            is_imp, kw = _mark_important(title)
            rows_all.append((
                code, str(r.get("名称", "") or ""), title,
                str(r.get("公告类型", "") or ""), r.get("公告日期"),
                "eastmoney", str(r.get("网址", "") or ""), is_imp, kw,
            ))

    written = _upsert(rows_all)
    logger.info("[公告] 东财全市场 %s~%s 共 %d 天，写入 %d 条", start, end, len(days), written)
    return {"source": "eastmoney", "days": len(days), "fetched": len(rows_all), "written": written}


def track_stock_announcements(
    stock_codes: list[str],
    start_date=None,
    end_date=None,
    lookback_days: int = 7,
    categories: list[str] | None = None,
    only_important: bool = False,
) -> dict:
    """巨潮 cninfo 股票池公告精确追踪（逐股拉官方一手公告）

    Args:
        stock_codes: 股票代码列表（可带 .SH/.SZ 后缀）
        start_date/end_date: 日期区间，默认最近 lookback_days 天
        categories: 巨潮官方分类名列表，默认 None=全部；传 TRACK_CATEGORIES 可聚焦硬信号
        only_important: True 只保留命中关键词的重要公告
    """
    import akshare as ak

    end = _fmt_date(end_date or date.today())
    start = _fmt_date(start_date or (date.today() - timedelta(days=lookback_days)))

    rows_all: list[tuple] = []
    per_stock = []
    for code in stock_codes:
        code = _clean_stock_code(code)
        cats = categories or [""]
        for cat in cats:
            try:
                df = ak.stock_zh_a_disclosure_report_cninfo(
                    symbol=code,
                    market="沪深京",
                    keyword="",
                    category=cat,
                    start_date=start,
                    end_date=end,
                )
            except Exception:  # noqa: BLE001 单股失败不阻塞
                logger.warning("[公告] cninfo %s 分类[%s] 拉取失败，跳过", code, cat, exc_info=True)
                continue
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                title = str(r.get("公告标题", "") or "").strip()
                if not title:
                    continue
                is_imp, kw = _mark_important(title)
                if only_important and not is_imp:
                    continue
                rows_all.append((
                    code, str(r.get("简称", "") or ""), title,
                    cat or str(r.get("公告类型", "") or ""),
                    r.get("公告时间"), "cninfo",
                    str(r.get("公告链接", "") or ""), is_imp, kw,
                ))
        per_stock.append(code)

    written = _upsert(rows_all)
    logger.info("[公告] cninfo 追踪 %d 只股票(%s~%s)，写入 %d 条", len(per_stock), start, end, written)
    return {
        "source": "cninfo", "stocks": len(per_stock),
        "fetched": len(rows_all), "written": written,
        "only_important": only_important,
    }


def _upsert(rows: list[tuple]) -> int:
    """写入 trade_stock_announcement，按 (stock_code, ann_title, ann_date) 去重"""
    if not rows:
        return 0
    execute_many(
        "INSERT IGNORE INTO trade_stock_announcement "
        "(stock_code, stock_name, ann_title, ann_type, ann_date, source, source_url, "
        " is_important, keyword_hit) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        rows,
    )
    # 返回实际写入行数（INSERT IGNORE 的 affected rows 为 1=插入 0=忽略）
    return len(rows)


def query_announcements(
    stock_code: str | None = None,
    start_date=None,
    end_date=None,
    source: str | None = None,
    only_important: bool = False,
    limit: int = 100,
) -> list[dict]:
    """查询公告（供 API 使用）"""
    sql = "SELECT * FROM trade_stock_announcement WHERE 1=1"
    params: list = []
    if stock_code:
        sql += " AND stock_code=%s"
        params.append(_clean_stock_code(stock_code))
    if start_date:
        sql += " AND ann_date>=%s"
        params.append(_fmt_date(start_date))
    if end_date:
        sql += " AND ann_date<=%s"
        params.append(_fmt_date(end_date))
    if source:
        sql += " AND source=%s"
        params.append(source)
    if only_important:
        sql += " AND is_important=1"
    sql += " ORDER BY ann_date DESC, id DESC LIMIT %s"
    params.append(limit)
    return execute_query(sql, params)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = sync_announcement_daily()
    print("同步结果:", result)
