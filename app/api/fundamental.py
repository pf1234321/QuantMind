# -*- coding: utf-8 -*-
"""基本面分析接口"""
import logging
from fastapi import APIRouter, Query, HTTPException

from app.database import execute_query
from app import scheduler

router = APIRouter(prefix="/fundamental", tags=["基本面分析"])
logger = logging.getLogger(__name__)


@router.get("/analyze", summary="个股基本面分析")
def analyze_fundamental(
    stock_code: str = Query(..., description="股票代码，如 600519"),
    auto_sync: bool = Query(True, description="当数据不存在时是否自动同步财务数据"),
):
    """分析个股基本面指标，并与同行业公司对比。

    **返回内容**：
    - 个股最新财务指标（ROE、ROA、毛利率、净利率、资产负债率等）
    - 同行业（申万二级）公司的指标分布（均值、中位数、排名）
    - 个股在行业中的相对位置（优秀/良好/一般/较差）

    **自动同步**：
    - 当股票财务数据不存在时，会自动触发财务数据同步
    - 同步完成后返回分析结果
    """
    # 1. 查询个股最新财务数据和行业信息
    stock_data = execute_query(
        "SELECT f.stock_code, s.stock_name, s.sector_1, s.sector_2, s.sector_3, "
        "       f.report_date, f.revenue, f.net_profit, f.eps, "
        "       f.roe, f.roa, f.gross_margin, f.net_margin, f.debt_ratio, "
        "       f.current_ratio, f.operating_cashflow, f.total_assets, f.total_equity "
        "FROM trade_stock_financial f "
        "JOIN trade_stock_status s ON f.stock_code = s.stock_code "
        "WHERE f.stock_code = %s "
        "ORDER BY f.report_date DESC LIMIT 1",
        (stock_code,),
    )

    # 如果没有数据且允许自动同步，则触发同步
    if not stock_data and auto_sync:
        logger.info(f"股票 {stock_code} 没有财务数据，触发自动同步")

        # 检查股票是否存在
        stock_exists = execute_query(
            "SELECT stock_code, stock_name FROM trade_stock_status WHERE stock_code = %s",
            (stock_code,),
        )

        if not stock_exists:
            raise HTTPException(status_code=404, detail=f"股票代码 {stock_code} 不存在，请检查代码是否正确")

        try:
            # 触发财务数据同步
            from app.services.financial_sync import sync_financial

            logger.info(f"开始同步股票 {stock_code} ({stock_exists[0]['stock_name']}) 的财务数据...")
            sync_result = sync_financial(
                stock_codes=[stock_code],
                quarters=4,
                enrich_detail=True,
            )

            logger.info(f"财务数据同步完成: {sync_result}")

            # 重新查询财务数据
            stock_data = execute_query(
                "SELECT f.stock_code, s.stock_name, s.sector_1, s.sector_2, s.sector_3, "
                "       f.report_date, f.revenue, f.net_profit, f.eps, "
                "       f.roe, f.roa, f.gross_margin, f.net_margin, f.debt_ratio, "
                "       f.current_ratio, f.operating_cashflow, f.total_assets, f.total_equity "
                "FROM trade_stock_financial f "
                "JOIN trade_stock_status s ON f.stock_code = s.stock_code "
                "WHERE f.stock_code = %s "
                "ORDER BY f.report_date DESC LIMIT 1",
                (stock_code,),
            )

            if not stock_data:
                raise HTTPException(
                    status_code=500,
                    detail=f"财务数据同步完成，但未能获取到股票 {stock_code} 的数据，可能该股票暂无公开财务报表"
                )

        except Exception as e:
            logger.exception(f"同步股票 {stock_code} 财务数据失败")
            raise HTTPException(
                status_code=500,
                detail=f"自动同步财务数据失败: {str(e)}"
            )

    if not stock_data:
        raise HTTPException(
            status_code=404,
            detail=f"未找到股票 {stock_code} 的财务数据，请先同步财务数据或检查股票代码是否正确"
        )

    stock = stock_data[0]
    sector_2 = stock["sector_2"]

    if not sector_2:
        raise HTTPException(status_code=404, detail=f"股票 {stock_code} 缺少行业分类信息")

    # 2. 检查同行业公司数量，如果数据不足则自动同步（限制数量避免 API 限流）
    if auto_sync:
        # 查询同行业有财务数据的公司数量
        industry_financial_count = execute_query(
            "SELECT COUNT(DISTINCT f.stock_code) as cnt "
            "FROM trade_stock_financial f "
            "JOIN trade_stock_status s ON f.stock_code = s.stock_code "
            "WHERE s.sector_2 = %s AND f.roa IS NOT NULL AND f.net_margin IS NOT NULL",
            (sector_2,),
        )

        # 查询同行业总公司数量
        industry_total_count = execute_query(
            "SELECT COUNT(*) as cnt FROM trade_stock_status WHERE sector_2 = %s",
            (sector_2,),
        )

        financial_count = industry_financial_count[0]["cnt"] if industry_financial_count else 0
        total_count = industry_total_count[0]["cnt"] if industry_total_count else 0

        logger.info(f"行业 {sector_2}: 总公司数 {total_count}, 有详细数据 {financial_count}")

        # 如果有详细数据的公司少于5家，则同步部分公司（避免 API 限流）
        if financial_count < min(5, total_count):
            logger.info(f"同行业详细财务数据不足（{financial_count}/{total_count}），开始同步部分同行业公司...")

            try:
                # 获取同行业前10家公司（限制数量避免 API 限流）
                industry_stocks = execute_query(
                    "SELECT stock_code FROM trade_stock_status WHERE sector_2 = %s LIMIT 10",
                    (sector_2,),
                )

                industry_codes = [row["stock_code"] for row in industry_stocks]

                if industry_codes:
                    from app.services.financial_sync import sync_financial

                    logger.info(f"开始同步 {len(industry_codes)} 只同行业股票的详细财务数据（限流保护）")

                    # 分批同步，每次3只，避免 API 限流
                    import time
                    batch_size = 3
                    for i in range(0, len(industry_codes), batch_size):
                        batch = industry_codes[i:i+batch_size]
                        logger.info(f"同步批次 {i//batch_size + 1}: {batch}")

                        sync_result = sync_financial(
                            stock_codes=batch,
                            quarters=2,  # 只同步2个季度，加快速度
                            enrich_detail=True,
                        )
                        logger.info(f"批次同步完成: {sync_result}")

                        # 每批之间等待2秒，避免 API 限流
                        if i + batch_size < len(industry_codes):
                            time.sleep(2)

            except Exception as e:
                # 同步失败不影响主流程，只记录日志
                logger.warning(f"同步同行业财务数据失败: {e}")

    # 3. 查询同行业所有公司的最新财务数据
    industry_data = execute_query(
        "SELECT f.stock_code, s.stock_name, f.roe, f.roa, f.gross_margin, "
        "       f.net_margin, f.debt_ratio, f.revenue, f.net_profit "
        "FROM trade_stock_financial f "
        "JOIN trade_stock_status s ON f.stock_code = s.stock_code "
        "WHERE s.sector_2 = %s "
        "  AND f.report_date = ("
        "    SELECT MAX(f2.report_date) FROM trade_stock_financial f2 "
        "    WHERE f2.stock_code = f.stock_code"
        "  )",
        (sector_2,),
    )

    # 3. 计算行业统计数据
    def calc_stats(values, current_value):
        """计算统计数据和排名"""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None

        valid_values_sorted = sorted(valid_values, reverse=True)
        avg = sum(valid_values) / len(valid_values)
        median = valid_values_sorted[len(valid_values_sorted) // 2]

        # 计算排名（从大到小，值越大排名越前）
        if current_value is not None:
            rank = sum(1 for v in valid_values if v > current_value) + 1
            percentile = (len(valid_values) - rank + 1) / len(valid_values) * 100
        else:
            rank = None
            percentile = None

        return {
            "avg": round(float(avg), 4) if avg else None,
            "median": round(float(median), 4) if median else None,
            "rank": rank,
            "total": len(valid_values),
            "percentile": round(percentile, 2) if percentile else None,
        }

    # 提取各指标的值
    roe_values = [row["roe"] for row in industry_data if row["roe"] is not None]
    roa_values = [row["roa"] for row in industry_data if row["roa"] is not None]
    gross_margin_values = [row["gross_margin"] for row in industry_data if row["gross_margin"] is not None]
    net_margin_values = [row["net_margin"] for row in industry_data if row["net_margin"] is not None]
    debt_ratio_values = [row["debt_ratio"] for row in industry_data if row["debt_ratio"] is not None]

    # 计算个股指标的行业排名
    industry_comparison = {
        "roe": calc_stats(roe_values, stock["roe"]),
        "roa": calc_stats(roa_values, stock["roa"]),
        "gross_margin": calc_stats(gross_margin_values, stock["gross_margin"]),
        "net_margin": calc_stats(net_margin_values, stock["net_margin"]),
        "debt_ratio": calc_stats(debt_ratio_values, stock["debt_ratio"]),
    }

    # 4. 生成评级（根据行业百分位）
    def get_rating(percentile):
        if percentile is None:
            return "无数据"
        if percentile >= 80:
            return "优秀"
        elif percentile >= 60:
            return "良好"
        elif percentile >= 40:
            return "中等"
        elif percentile >= 20:
            return "一般"
        else:
            return "较差"

    ratings = {
        "roe": get_rating(industry_comparison["roe"]["percentile"] if industry_comparison["roe"] else None),
        "roa": get_rating(industry_comparison["roa"]["percentile"] if industry_comparison["roa"] else None),
        "gross_margin": get_rating(industry_comparison["gross_margin"]["percentile"] if industry_comparison["gross_margin"] else None),
        "net_margin": get_rating(industry_comparison["net_margin"]["percentile"] if industry_comparison["net_margin"] else None),
        "debt_ratio": get_rating(100 - industry_comparison["debt_ratio"]["percentile"] if industry_comparison["debt_ratio"] and industry_comparison["debt_ratio"]["percentile"] else None),  # 负债率越低越好
    }

    # 5. 查询历史趋势数据（最近4个季度）
    history = execute_query(
        "SELECT report_date, roe, roa, gross_margin, net_margin, debt_ratio, revenue, net_profit "
        "FROM trade_stock_financial "
        "WHERE stock_code = %s "
        "ORDER BY report_date DESC LIMIT 4",
        (stock_code,),
    )

    # 6. 返回结果
    return {
        "stock": {
            "code": stock["stock_code"],
            "name": stock["stock_name"],
            "sector_1": stock["sector_1"],
            "sector_2": stock["sector_2"],
            "sector_3": stock["sector_3"],
            "report_date": str(stock["report_date"]) if stock["report_date"] else None,
        },
        "fundamentals": {
            "roe": float(stock["roe"]) if stock["roe"] else None,
            "roa": float(stock["roa"]) if stock["roa"] else None,
            "gross_margin": float(stock["gross_margin"]) if stock["gross_margin"] else None,
            "net_margin": float(stock["net_margin"]) if stock["net_margin"] else None,
            "debt_ratio": float(stock["debt_ratio"]) if stock["debt_ratio"] else None,
            "current_ratio": float(stock["current_ratio"]) if stock["current_ratio"] else None,
            "eps": float(stock["eps"]) if stock["eps"] else None,
            "revenue": float(stock["revenue"]) if stock["revenue"] else None,
            "net_profit": float(stock["net_profit"]) if stock["net_profit"] else None,
        },
        "industry_comparison": industry_comparison,
        "ratings": ratings,
        "history": [
            {
                "report_date": str(row["report_date"]) if row["report_date"] else None,
                "roe": float(row["roe"]) if row["roe"] else None,
                "roa": float(row["roa"]) if row["roa"] else None,
                "gross_margin": float(row["gross_margin"]) if row["gross_margin"] else None,
                "net_margin": float(row["net_margin"]) if row["net_margin"] else None,
                "debt_ratio": float(row["debt_ratio"]) if row["debt_ratio"] else None,
                "revenue": float(row["revenue"]) if row["revenue"] else None,
                "net_profit": float(row["net_profit"]) if row["net_profit"] else None,
            }
            for row in history
        ],
        "industry_peers": [
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "roe": float(row["roe"]) if row["roe"] else None,
                "roa": float(row["roa"]) if row["roa"] else None,
                "gross_margin": float(row["gross_margin"]) if row["gross_margin"] else None,
                "net_margin": float(row["net_margin"]) if row["net_margin"] else None,
                "revenue": float(row["revenue"]) if row["revenue"] else None,
            }
            for row in industry_data[:20]  # 只返回前20个同行
        ],
    }
