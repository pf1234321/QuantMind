# -*- coding: utf-8 -*-
"""技术分析相关 API 接口"""
import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.services.technical_backtest import ensure_kline_data_updated

router = APIRouter(prefix="/technical", tags=["技术分析"])
logger = logging.getLogger(__name__)


# ==================== 技术指标查询 ====================

@router.get("/indicators", summary="查询技术指标")
async def get_technical_indicators(
    code: str = Query(..., description="股票代码，如 600519"),
    period: str = Query("daily", description="周期：daily/weekly/monthly"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录条数上限"),
    skip_compute: bool = Query(False, description="如果没有预计算数据，直接返回空（不实时计算）"),
):
    """查询股票的技术指标数据。

    **支持的指标**：
    - 趋势：ma5, ma20, ma60
    - 动量：rsi14, macd_dif, macd_dea, macd_bar
    - KDJ：kdj_k, kdj_d, kdj_j
    - 波动率：atr14
    - 成交量：volume_ratio

    **支持多周期**：
    - daily：日线
    - weekly：周线
    - monthly：月线

    **示例**：`GET /technical/indicators?code=600519&period=daily&limit=30`
    """
    from app.database import execute_query
    from app.services.technical_indicators import (
        calculate_ma, calculate_macd, calculate_rsi,
        calculate_kdj, calculate_boll, resample_to_period
    )
    from app.backtest.data import load_daily_bars

    code = code.split(".")[0]

    # 查询接口不应该触发数据同步，改为仅提示用户
    # 如需更新数据，请调用 POST /api/v1/sync/kline 接口

    sql = """
        SELECT * FROM trade_technical_summary
        WHERE stock_code=%s AND period=%s
    """
    params = [code, period]

    if start_date:
        sql += " AND trade_date>=%s"
        params.append(start_date)
    if end_date:
        sql += " AND trade_date<=%s"
        params.append(end_date)

    sql += " ORDER BY trade_date DESC LIMIT %s"
    params.append(limit)

    rows = execute_query(sql, params)

    # 如果数据库中没有技术指标数据，从K线实时计算
    if not rows and skip_compute:
        logger.info(f"数据库中无 {code} 的技术指标数据，跳过实时计算")
        return {"code": code, "period": period, "count": 0, "data": [], "message": "无预计算数据，请先调用 POST /technical/sync/indicators 同步"}

    if not rows:
        logger.info(f"数据库中无 {code} 的技术指标数据，从K线实时计算")

        try:
            # 加载K线数据（只取最近2年数据，提升性能）
            if not start_date:
                start_date = (date.today().replace(year=date.today().year - 2)).strftime('%Y-%m-%d')

            frame = load_daily_bars(
                code,
                start_date,
                end_date or date.today().strftime('%Y-%m-%d'),
                execute_query
            )

            if frame.empty:
                raise HTTPException(404, f"未找到 {code} 的K线数据")

            # 转换周期
            if period != "daily":
                frame = resample_to_period(frame, period)

            # 计算技术指标
            frame = calculate_ma(frame, [5, 20, 60])
            frame = calculate_macd(frame)
            frame = calculate_rsi(frame)
            frame = calculate_kdj(frame)

            # 转换为API返回格式
            frame = frame.tail(limit).iloc[::-1]  # 取最新的limit条，倒序
            rows = []
            for idx, row in frame.iterrows():
                rows.append({
                    'stock_code': code,
                    'trade_date': idx.strftime('%Y-%m-%d'),
                    'period': period,
                    'ma5': float(row.get('ma5', 0)) if 'ma5' in row else None,
                    'ma20': float(row.get('ma20', 0)) if 'ma20' in row else None,
                    'ma60': float(row.get('ma60', 0)) if 'ma60' in row else None,
                    'rsi14': float(row.get('rsi', 0)) if 'rsi' in row else None,
                    'macd_dif': float(row.get('macd_dif', 0)) if 'macd_dif' in row else None,
                    'macd_dea': float(row.get('macd_dea', 0)) if 'macd_dea' in row else None,
                    'macd_bar': float(row.get('macd_bar', 0)) if 'macd_bar' in row else None,
                    'kdj_k': float(row.get('kdj_k', 0)) if 'kdj_k' in row else None,
                    'kdj_d': float(row.get('kdj_d', 0)) if 'kdj_d' in row else None,
                    'kdj_j': float(row.get('kdj_j', 0)) if 'kdj_j' in row else None,
                    'close_price': float(row.get('close', 0)),
                })

        except Exception as e:
            logger.error(f"实时计算技术指标失败: {e}")
            raise HTTPException(500, f"技术指标计算失败: {str(e)}")

    return {"code": code, "period": period, "count": len(rows), "data": rows}


@router.get("/indicators/latest", summary="查询最新技术指标")
def get_latest_indicators(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="周期"),
):
    """查询股票最新的技术指标（单条记录）。

    **示例**：`GET /technical/indicators/latest?code=600519`
    """
    from app.services.technical_indicators import get_latest_indicators

    code = code.split(".")[0]
    indicators = get_latest_indicators(code, period, limit=1)

    if not indicators:
        raise HTTPException(404, f"未找到 {code} 的技术指标数据")

    return {"code": code, "period": period, "data": indicators[0]}


# ==================== 技术形态识别 ====================

@router.get("/patterns", summary="查询技术形态")
def get_technical_patterns(
    code: str | None = Query(None, description="股票代码（不传则查询全部）"),
    pattern_type: str | None = Query(
        None,
        description="形态类型：head_shoulders_top/double_bottom/double_top/ascending_triangle/descending_triangle"
    ),
    pattern_status: str | None = Query(None, description="形态状态：forming/confirmed/broken"),
    limit: int = Query(50, ge=1, le=200),
):
    """查询已识别的技术形态。

    **支持的形态类型**：
    - head_shoulders_top：头肩顶（看跌）
    - double_bottom：双底/W底（看涨）
    - double_top：双顶/M顶（看跌）
    - ascending_triangle：上升三角形（看涨）
    - descending_triangle：下降三角形（看跌）

    **形态状态**：
    - forming：形成中
    - confirmed：已确认
    - broken：已破坏

    **示例**：`GET /technical/patterns?code=600519&pattern_status=confirmed`
    """
    from app.database import execute_query

    sql = "SELECT * FROM trade_technical_patterns WHERE 1=1"
    params = []

    if code:
        sql += " AND stock_code=%s"
        params.append(code.split(".")[0])

    if pattern_type:
        sql += " AND pattern_type=%s"
        params.append(pattern_type)

    if pattern_status:
        sql += " AND pattern_status=%s"
        params.append(pattern_status)

    sql += " ORDER BY updated_at DESC LIMIT %s"
    params.append(limit)

    rows = execute_query(sql, params)

    return {"count": len(rows), "data": rows}


# ==================== 策略回测 ====================

@router.post("/backtest/batch", summary="批量回测技术指标策略")
def backtest_technical_strategies(
    codes: str = Query(..., description="股票代码列表，逗号分隔，如 600519,000001"),
    strategies: str = Query(
        "ma_cross,macd,rsi",
        description="策略类型，逗号分隔：ma_cross/macd/rsi/kdj/boll/ma_macd_combined/triple_combined"
    ),
    start_date: str = Query("2020-01-01", description="回测起始日期 YYYY-MM-DD"),
    end_date: str = Query("2024-12-31", description="回测结束日期 YYYY-MM-DD"),
    period: str = Query("daily", description="回测周期：daily/weekly/monthly"),
    top_n: int = Query(10, description="返回收益最好的前 N 个结果"),
):
    """批量回测多个技术指标策略，找出历史收益最好的指标组合。

    **支持的策略类型**：
    - ma_cross：均线交叉策略（5日线与20日线金叉死叉）
    - macd：MACD 金叉死叉策略
    - rsi：RSI 超买超卖策略（<30买入，>70卖出）
    - kdj：KDJ 超买超卖策略（J值<20买入，>80卖出）
    - boll：布林带突破策略
    - ma_macd_combined：均线+MACD组合策略（多头排列+MACD金叉）
    - triple_combined：三重组合策略（均线+MACD+RSI）

    **回测说明**：
    - 自动计算年化收益、夏普比率、最大回撤、胜率等指标
    - 支持多周期回测（日线/周线/月线）
    - 结果自动保存到数据库

    **示例**：
    ```
    POST /technical/backtest/batch?codes=600519,000001&strategies=ma_cross,macd,triple_combined
    ```

    **返回**：按年化收益率排序的策略回测结果
    """
    from app.services.technical_backtest import batch_backtest_strategies

    stock_codes = [c.strip() for c in codes.split(",")]
    strategy_types = [s.strip() for s in strategies.split(",")]

    # 验证策略类型
    valid_strategies = {"ma_cross", "macd", "rsi", "kdj", "boll", "ma_macd_combined", "triple_combined"}
    invalid = set(strategy_types) - valid_strategies
    if invalid:
        raise HTTPException(400, f"不支持的策略类型: {', '.join(invalid)}")

    results = batch_backtest_strategies(
        stock_codes=stock_codes,
        strategy_types=strategy_types,
        start_date=start_date,
        end_date=end_date,
        period=period,
        save_to_db=True
    )

    if not results:
        raise HTTPException(404, "回测失败，请检查股票代码和日期范围")

    # 按年化收益排序，取前 N
    sorted_results = sorted(
        results,
        key=lambda x: x['metrics'].get('annualized_return', -999),
        reverse=True
    )[:top_n]

    # 格式化返回
    formatted = []
    for r in sorted_results:
        formatted.append({
            'backtest_id': r['backtest_id'],
            'stock_code': r['stock_code'],
            'strategy_type': r['strategy_type'],
            'period': r['period'],
            'annualized_return': r['metrics'].get('annualized_return'),
            'sharpe_ratio': r['metrics'].get('sharpe_ratio'),
            'max_drawdown': r['metrics'].get('max_drawdown'),
            'win_rate': r['metrics'].get('win_rate'),
            'trade_count': r['metrics'].get('trade_count'),
            'buy_hold_return': r['buy_hold_return']
        })

    return {
        "total_tested": len(results),
        "top_strategies": formatted,
        "summary": {
            "best_strategy": formatted[0]['strategy_type'] if formatted else None,
            "best_stock": formatted[0]['stock_code'] if formatted else None,
            "best_return": formatted[0]['annualized_return'] if formatted else None
        }
    }


@router.get("/backtest/best", summary="查询最佳策略")
def get_best_strategies(
    code: str | None = Query(None, description="股票代码（不传则查询全部）"),
    min_sharpe: float = Query(1.0, description="最低夏普比率要求"),
    min_trades: int = Query(10, description="最少交易次数要求"),
    limit: int = Query(20, ge=1, le=100),
):
    """查询历史回测中表现最好的策略（按年化收益排序）。

    **示例**：`GET /technical/backtest/best?code=600519&min_sharpe=1.5`
    """
    from app.services.technical_backtest import get_best_strategies

    code = code.split(".")[0] if code else None
    results = get_best_strategies(code, min_sharpe, min_trades, limit)

    return {"count": len(results), "data": results}


@router.get("/backtest/compare", summary="对比单只股票的策略表现")
def compare_strategies(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="周期"),
):
    """对比单只股票上所有策略的历史表现。

    **示例**：`GET /technical/backtest/compare?code=600519`
    """
    from app.services.technical_backtest import compare_strategies_for_stock

    code = code.split(".")[0]
    result = compare_strategies_for_stock(code, period)

    if not result.get('strategies'):
        raise HTTPException(404, f"未找到 {code} 的回测数据，请先执行回测")

    return result


@router.get("/backtest/trades", summary="查询交易明细")
def get_backtest_trades(
    backtest_id: str = Query(..., description="回测批次ID"),
    code: str = Query(..., description="股票代码"),
    strategy: str = Query(..., description="策略类型"),
    period: str = Query("daily", description="周期"),
):
    """获取某次回测的所有交易明细，用于图形化展示。

    **示例**：`GET /technical/backtest/trades?backtest_id=xxx&code=600519&strategy=ma_cross`
    """
    from app.services.technical_backtest import get_trade_details

    code = code.split(".")[0]
    trades = get_trade_details(backtest_id, code, strategy, period)

    return {
        "backtest_id": backtest_id,
        "stock_code": code,
        "strategy_type": strategy,
        "period": period,
        "trade_count": len(trades),
        "trades": trades
    }


# ==================== LLM 技术分析报告 ====================

@router.post("/report/generate", summary="生成技术分析报告（LLM）")
def generate_technical_report(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="分析周期"),
    llm_model: str = Query("gpt-4", description="LLM模型：gpt-4/gpt-3.5-turbo"),
):
    """基于技术指标、形态、回测数据，调用 LLM 生成专业的技术分析报告。

    **报告内容包括**：
    1. 趋势分析（基于均线排列）
    2. 形态分析（识别到的技术形态）
    3. 指标分析（RSI、MACD、KDJ 综合）
    4. 成交量分析
    5. 支撑与阻力位
    6. 交易建议（买入/卖出/观望，仓位、止损位）
    7. 风险提示
    8. 技术面评分（0-100分）

    **前置条件**：
    - 需要先执行技术指标计算
    - 需要配置 OPENAI_API_KEY 环境变量

    **示例**：`POST /technical/report/generate?code=600519`
    """
    from app.services.technical_reports import generate_technical_report

    code = code.split(".")[0]

    try:
        report = generate_technical_report(code, period=period, llm_model=llm_model)
        return report
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"报告生成失败: {str(e)}")


@router.get("/report/latest", summary="查询最新技术分析报告")
def get_latest_report(
    code: str = Query(..., description="股票代码"),
    period: str = Query("daily", description="周期"),
):
    """查询股票最新的技术分析报告。

    **示例**：`GET /technical/report/latest?code=600519`
    """
    from app.services.technical_reports import get_latest_report

    code = code.split(".")[0]
    report = get_latest_report(code, period)

    if not report:
        raise HTTPException(404, f"未找到 {code} 的技术分析报告，请先生成报告")

    return report


@router.post("/report/batch", summary="批量生成技术分析报告")
def batch_generate_reports(
    codes: str = Query(..., description="股票代码列表，逗号分隔"),
    period: str = Query("daily", description="周期"),
    llm_model: str = Query("gpt-3.5-turbo", description="LLM模型（批量建议用3.5降低成本）"),
):
    """批量生成多只股票的技术分析报告。

    **注意**：
    - 批量生成会调用多次 LLM API，建议使用 gpt-3.5-turbo 降低成本
    - 每个报告生成大约需要 3-5 秒

    **示例**：`POST /technical/report/batch?codes=600519,000001,000002`
    """
    from app.services.technical_reports import batch_generate_reports

    stock_codes = [c.strip().split(".")[0] for c in codes.split(",")]

    result = batch_generate_reports(stock_codes, period, llm_model)

    return result


# ==================== 数据同步触发 ====================

@router.post("/sync/indicators", summary="同步技术指标计算")
def sync_technical_indicators(
    codes: str | None = Query(None, description="股票代码列表，逗号分隔（不传则全量）"),
    period: str = Query("daily", description="周期：daily/weekly/monthly"),
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    force_refresh: bool = Query(False, description="是否强制重算"),
):
    """触发技术指标计算与同步。

    **说明**：基于 trade_stock_daily K线数据计算技术指标并写入数据库

    **示例**：`POST /technical/sync/indicators?codes=600519&period=daily`
    """
    from app.services.technical_indicators import sync_technical_indicators

    stock_codes = [c.strip() for c in codes.split(",")] if codes else None

    result = sync_technical_indicators(
        stock_codes=stock_codes,
        start_date=start_date,
        end_date=end_date,
        period=period,
        force_refresh=force_refresh
    )

    return result


@router.post("/sync/patterns", summary="同步技术形态识别")
def sync_pattern_detection(
    codes: str | None = Query(None, description="股票代码列表，逗号分隔（不传则全量）"),
    lookback_days: int = Query(120, description="回看天数"),
    period: str = Query("daily", description="周期"),
):
    """触发技术形态识别。

    **说明**：识别头肩顶、双底、三角形等技术形态

    **示例**：`POST /technical/sync/patterns?codes=600519`
    """
    from app.services.technical_patterns import sync_pattern_detection

    stock_codes = [c.strip() for c in codes.split(",")] if codes else None

    result = sync_pattern_detection(
        stock_codes=stock_codes,
        lookback_days=lookback_days,
        period=period
    )

    return result
