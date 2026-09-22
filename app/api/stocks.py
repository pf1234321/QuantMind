# -*- coding: utf-8 -*-
"""股票行情/财务/新闻/研报查询接口"""
from fastapi import APIRouter, HTTPException, Query

from app.database import execute_query

router = APIRouter(prefix="/stocks", tags=["股票数据"])


@router.get("/daily", summary="查询个股日K线行情")
def get_stock_daily(
    code: str = Query(..., description="股票代码，如 600519 或 600519.SH（自动忽略交易所后缀）"),
    start_date: str | None = Query(None, description="起始日期 YYYYMMDD，如 20240101"),
    end_date: str | None = Query(None, description="结束日期 YYYYMMDD，如 20241231"),
    limit: int = Query(100, ge=1, le=10000, description="返回记录条数上限，默认 100，最大 10000"),
):
    """查询指定股票的日K线行情数据（trade_stock_daily，baostock 数据源）。

    **返回字段**：股票代码、交易日期、开盘价、最高价、最低价、收盘价、成交量、成交额、换手率。

    **使用说明**：
    - 按交易日期**倒序**返回，最新的行情在最前面
    - 股票代码可带交易所后缀（600519.SH / 000001.SZ），接口会自动去除后缀
    - 可通过 start_date / end_date 限定查询区间

    **示例**：`GET /stocks/daily?code=600519&limit=10`
    """
    code = code.split(".")[0]
    sql = (
        "SELECT stock_code, trade_date, open_price, high_price, low_price, "
        "close_price, volume, amount, turnover_rate "
        "FROM trade_stock_daily WHERE stock_code=%s"
    )
    params: list = [code]
    if start_date:
        sql += " AND trade_date>=%s"
        params.append(start_date)
    if end_date:
        sql += " AND trade_date<=%s"
        params.append(end_date)
    sql += " ORDER BY trade_date DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, f"未找到 {code} 的行情数据")
    return {"code": code, "count": len(rows), "data": rows}


@router.get("/financial", summary="查询个股财务数据")
def get_stock_financial(
    code: str = Query(..., description="股票代码，如 600519（必填）"),
    limit: int = Query(8, ge=1, le=50, description="返回最近几个报告期的财务数据，默认 8 期，最大 50 期"),
):
    """查询个股的历史财务数据（trade_stock_financial）。

    **返回字段**：报告期、营业收入、净利润、每股收益(EPS)、净资产收益率(ROE)、总资产收益率(ROA)、
    毛利率、净利率、资产负债率、流动比率、经营现金流、总资产、净资产、数据来源。

    **使用说明**：
    - 按报告期**倒序**返回（最新的财报在最前面）
    - 适用于基本面分析、财务质量筛选

    **示例**：`GET /stocks/financial?code=600519&limit=5`
    """
    code = code.split(".")[0]
    rows = execute_query(
        "SELECT stock_code, report_date, revenue, net_profit, eps, roe, roa, "
        "gross_margin, net_margin, debt_ratio, current_ratio, operating_cashflow, "
        "total_assets, total_equity, data_source "
        "FROM trade_stock_financial WHERE stock_code=%s "
        "ORDER BY report_date DESC LIMIT %s",
        (code, limit),
    )
    if not rows:
        raise HTTPException(404, f"未找到 {code} 的财务数据")
    return {"code": code, "count": len(rows), "data": rows}


@router.get("/news", summary="查询个股新闻")
def get_stock_news(
    code: str = Query(..., description="股票代码，如 600519（必填）"),
    limit: int = Query(50, ge=1, le=200, description="返回新闻条数上限，默认 50，最大 200"),
    sentiment: str | None = Query(None, description="按情感过滤，取值：positive（正面）/ negative（负面）/ neutral（中性）"),
):
    """查询个股相关新闻（trade_stock_news）。

    **使用说明**：
    - 按发布时间**倒序**返回（最新新闻在最前面）
    - 可通过 sentiment 参数过滤情感倾向（正面/负面/中性）
    - 与情绪分析模块（/sentiment）联动，可查看新闻对应的情感打分

    **示例**：`GET /stocks/news?code=600519&sentiment=positive&limit=20`
    """
    code = code.split(".")[0]
    sql = "SELECT * FROM trade_stock_news WHERE stock_code=%s"
    params: list = [code]
    if sentiment:
        sql += " AND sentiment=%s"
        params.append(sentiment)
    sql += " ORDER BY published_at DESC LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    if not rows:
        raise HTTPException(404, f"未找到 {code} 的新闻")
    return {"code": code, "count": len(rows), "data": rows}


@router.get("/consensus", summary="查询个股研报一致预期")
def get_stock_consensus(
    code: str = Query(..., description="股票代码，如 600519（必填）"),
    limit: int = Query(20, ge=1, le=200, description="返回研报条数上限，默认 20，最大 200"),
):
    """查询个股的券商研报一致预期（trade_report_consensus）。

    **返回字段**：券商名称、报告日期、评级、目标价、当期/下期 EPS 预测、营收预测。

    **使用说明**：
    - 按报告日期**倒序**返回（最新研报在最前面）
    - 用于了解卖方机构对该股票的一致看法与目标价区间

    **示例**：`GET /stocks/consensus?code=600519&limit=10`
    """
    code = code.split(".")[0]
    rows = execute_query(
        "SELECT stock_code, broker, report_date, rating, target_price, "
        "eps_forecast_current, eps_forecast_next, revenue_forecast "
        "FROM trade_report_consensus WHERE stock_code=%s "
        "ORDER BY report_date DESC LIMIT %s",
        (code, limit),
    )
    if not rows:
        raise HTTPException(404, f"未找到 {code} 的研报一致预期")
    return {"code": code, "count": len(rows), "data": rows}


@router.get("/factors", summary="查询个股一致预期因子")
def get_stock_factors(
    code: str = Query(..., description="股票代码，如 600519（必填）"),
    limit: int = Query(10, ge=1, le=100, description="返回因子记录条数上限，默认 10，最大 100"),
):
    """查询个股研报一致预期衍生的量化因子（trade_factor_consensus）。

    **返回字段**：隐含收益率、目标价均值/中位数、评级动量(30/90日)、EPS 修正(30/90日)、
    分析师覆盖数、目标价离散度、EPS 离散度。

    **使用说明**：
    - 按交易日**倒序**返回
    - 这些因子常用于**预期差选股**与**研报情绪动量**策略研究
    - 离散度指标可反映分析师分歧程度

    **示例**：`GET /stocks/factors?code=600519&limit=10`
    """
    code = code.split(".")[0]
    rows = execute_query(
        "SELECT stock_code, trade_date, implied_return, target_price_mean, "
        "target_price_median, rating_momentum_30d, rating_momentum_90d, "
        "eps_revision_30d, eps_revision_90d, analyst_coverage, "
        "target_price_dispersion, eps_dispersion "
        "FROM trade_factor_consensus WHERE stock_code=%s "
        "ORDER BY trade_date DESC LIMIT %s",
        (code, limit),
    )
    if not rows:
        raise HTTPException(404, f"未找到 {code} 的因子数据")
    return {"code": code, "count": len(rows), "data": rows}


@router.get("/announcements", summary="查询上市公司公告")
def get_stock_announcements(
    code: str | None = Query(None, description="股票代码，如 002594（不传则查询全部股票）"),
    start_date: str | None = Query(None, description="起始日期，支持 YYYYMMDD 或 YYYY-MM-DD 格式"),
    end_date: str | None = Query(None, description="结束日期，支持 YYYYMMDD 或 YYYY-MM-DD 格式"),
    source: str | None = Query(None, description="数据来源：eastmoney（东方财富）/ cninfo（巨潮资讯）"),
    only_important: bool = Query(False, description="是否只看重要公告（业绩预告/分红/重组等），默认 False 全部返回"),
    limit: int = Query(100, ge=1, le=500, description="返回公告条数上限，默认 100，最大 500"),
):
    """查询上市公司公告（trade_stock_announcement）。

    **使用说明**：
    - 支持按股票代码、日期区间、数据来源多条件组合过滤
    - only_important=true 时可快速筛选重要公告（业绩预告、解禁、股权变动等）
    - 公告为**增量同步**数据，来源于东方财富 / 巨潮资讯

    **示例**：`GET /stocks/announcements?code=002594&only_important=true&limit=20`
    """
    from app.services.announcement_sync import query_announcements

    rows = query_announcements(
        stock_code=code,
        start_date=start_date,
        end_date=end_date,
        source=source,
        only_important=only_important,
        limit=limit,
    )
    return {"count": len(rows), "data": rows}


# ================================================================ 公告 RAG
@router.post("/announcements/pdf-sync", summary="触发公告PDF同步")
def sync_announcements_pdf(
    days: int = Query(7, ge=1, le=90, description="回看天数，默认 7 天内的公告"),
    limit: int = Query(100, ge=1, le=2000, description="本批处理条数上限，默认 100，最大 2000"),
    code: str | None = Query(None, description="只处理指定股票代码（不传则处理全部）"),
    only_important: bool = Query(False, description="是否只处理重要公告"),
    reindex: bool = Query(False, description="是否重试 error/empty 状态的失败记录"),
):
    """触发公告 PDF 同步流程：获取直链 -> 下载 PDF -> 解析文本 -> 写入向量库。

    **说明**：
    - **同步执行**，耗时较长（下载+解析+向量化），请耐心等待返回
    - 执行结果写入数据库，可通过 `GET /stocks/announcements/pdf-status` 查看处理状态
    - reindex=true 时只重试之前失败（error/empty）的记录

    **返回**：处理统计信息 stat（各状态数量）
    """
    from app.services.announcement_pdf import sync_announcement_pdfs

    stat = sync_announcement_pdfs(
        lookback_days=days, limit=limit,
        stock_code=code, only_important=only_important, reindex=reindex,
    )
    return {"status": "done", "stat": stat}


@router.get("/announcements/rag", summary="语义检索公告（RAG）")
def search_announcements_rag(
    query: str = Query(..., description="检索问题/关键词，如：茅台三季度净利润、2024年分红预案"),
    code: str | None = Query(None, description="限定股票代码，如 600519（不传则全库检索）"),
    only_important: bool = Query(False, description="是否只检索重要公告"),
    start_date: str | None = Query(None, description="起始日期 YYYYMMDD，过滤公告发布时间"),
    end_date: str | None = Query(None, description="结束日期 YYYYMMDD，过滤公告发布时间"),
    top_k: int = Query(8, ge=1, le=30, description="返回最相关的公告条数，默认 8，最大 30"),
):
    """基于向量数据库（ChromaDB）对公告进行**语义检索**，返回与问题最相关的公告片段。

    **与普通搜索的区别**：
    - 支持自然语言提问，如「茅台三季度净利润同比下降多少？」
    - 不依赖精确关键词，可理解语义相近的表述

    **使用说明**：
    - 返回结果包含相关度得分与公告原文片段
    - 检索前请确保已执行过 `POST /stocks/announcements/pdf-sync` 完成向量入库

    **示例**：`GET /stocks/announcements/rag?query=茅台三季度净利润&code=600519&top_k=5`
    """
    from app.services.rag_vector import query_announcements

    hits = query_announcements(
        query, stock_code=code, only_important=only_important,
        start_date=start_date, end_date=end_date, top_k=top_k,
    )
    return {"count": len(hits), "data": hits}


@router.post("/announcements/analyze", summary="公告五步法智能分析")
def analyze_announcements_five_step(
    code: str = Query(..., description="股票代码（必填），如 600519"),
    name: str | None = Query(None, description="股票名称，如 贵州茅台（用于提示词增强，可省略）"),
    top_k: int = Query(8, ge=1, le=30, description="参与分析的公告条数，默认 8，最大 30"),
    only_important: bool = Query(False, description="是否只基于重要公告进行分析"),
):
    """基于公告内容，调用大模型执行**国泰君安五步法**深度分析。

    **五步分析框架**：
    1. 信息差：挖掘公告中的增量信息
    2. 逻辑差：判断逻辑与市场认知的差异
    3. 预期差：对比一致预期，识别超预期/不及预期
    4. 催化剂：提炼后续可能的事件催化
    5. 结论：给出综合研判结论与建议

    **说明**：
    - 调用 LLM（约 30-60 秒），请耐心等待
    - 建议先执行 RAG 检索 / PDF 同步确保公告数据完整

    **返回**：五步分析的完整结构化结果
    """
    from app.services.rag_analysis import run_five_step_analysis

    result = run_five_step_analysis(code, name, top_k=top_k, only_important=only_important)
    return result


@router.get("/announcements/pdf-status", summary="查询公告PDF处理状态")
def get_announcements_pdf_status(
    code: str | None = Query(None, description="按股票代码过滤（不传则查询全部）"),
    status: str | None = Query(None, description="按处理状态过滤：none（未处理）/ url（已获取直链）/ downloaded（已下载）/ parsed（已解析）/ indexed（已入库）/ error（失败）/ empty（无内容）"),
    limit: int = Query(50, ge=1, le=500, description="返回记录条数上限，默认 50，最大 500"),
):
    """查询公告 PDF 同步各环节的处理状态（配合 `POST /stocks/announcements/pdf-sync` 使用）。

    **处理链路**：none -> url -> downloaded -> parsed -> indexed

    **使用说明**：
    - 通过 status 参数可筛选处于某环节的记录，例如 `status=error` 找出失败记录以便重试
    - 可用于监控向量库数据是否完整

    **示例**：`GET /stocks/announcements/pdf-status?code=600519&status=indexed`
    """
    from app.services.announcement_pdf import query_pdf_records

    rows = query_pdf_records(stock_code=code, status=status, limit=limit)
    return {"count": len(rows), "data": rows}


@router.get("/list", summary="查询股票基础信息列表")
def get_stock_list(
    keyword: str | None = Query(None, description="按股票代码或名称模糊搜索，如「茅台」或「600519」"),
    limit: int = Query(100, ge=1, le=5000, description="返回股票条数上限，默认 100，最大 5000"),
):
    """查询股票基础信息（trade_stock_status）。

    **返回字段**：股票代码、股票名称、上市日期、总股本、流通股本、行业分类（一级/二级/三级）。

    **使用说明**：
    - keyword 支持股票代码或名称的**模糊匹配**，用于股票搜索/选择器
    - 可作为其他接口（行情/财务/新闻）的股票代码来源

    **示例**：`GET /stocks/list?keyword=600&limit=20`
    """
    sql = (
        "SELECT stock_code, stock_name, list_date, total_shares, float_shares, "
        "sector_1, sector_2, sector_3 FROM trade_stock_status"
    )
    params: list = []
    if keyword:
        sql += " WHERE stock_code LIKE %s OR stock_name LIKE %s"
        like = f"%{keyword}%"
        params += [like, like]
    sql += " LIMIT %s"
    params.append(limit)
    rows = execute_query(sql, params)
    return {"count": len(rows), "data": rows}
