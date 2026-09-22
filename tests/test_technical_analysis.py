#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""技术分析功能测试脚本"""
import sys
import logging
from datetime import date, timedelta

# 添加项目路径
sys.path.insert(0, '/Users/code/python/QuantMind')

from app.database import execute_query
from app.services.technical_indicators import sync_technical_indicators
from app.services.technical_patterns import sync_pattern_detection
from app.services.technical_backtest import batch_backtest_strategies, compare_strategies_for_stock
from app.services.technical_reports import generate_technical_report

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_technical_indicators():
    """测试技术指标计算"""
    logger.info("=" * 60)
    logger.info("测试 1: 技术指标计算（日线）")
    logger.info("=" * 60)

    # 测试股票：贵州茅台
    test_codes = ["600519"]

    result = sync_technical_indicators(
        stock_codes=test_codes,
        period="daily",
        force_refresh=False
    )

    logger.info(f"计算结果: {result}")

    # 查询结果
    indicators = execute_query(
        """
        SELECT * FROM trade_technical_summary
        WHERE stock_code='600519' AND period='daily'
        ORDER BY trade_date DESC
        LIMIT 5
        """)

    logger.info(f"最近5日指标数据:")
    for ind in indicators:
        logger.info(f"  日期: {ind['trade_date']}, MA5: {ind['ma5']}, RSI14: {ind['rsi14']}, MACD: {ind['macd_dif']}")

    return result['written'] > 0


def test_weekly_monthly_indicators():
    """测试周线、月线指标计算"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 2: 周线和月线指标计算")
    logger.info("=" * 60)

    test_codes = ["600519"]

    # 周线
    result_weekly = sync_technical_indicators(
        stock_codes=test_codes,
        period="weekly",
        force_refresh=False
    )
    logger.info(f"周线计算结果: {result_weekly}")

    # 月线
    result_monthly = sync_technical_indicators(
        stock_codes=test_codes,
        period="monthly",
        force_refresh=False
    )
    logger.info(f"月线计算结果: {result_monthly}")

    return result_weekly['written'] > 0 and result_monthly['written'] > 0


def test_pattern_detection():
    """测试技术形态识别"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 3: 技术形态识别")
    logger.info("=" * 60)

    test_codes = ["600519", "000001", "000002"]

    result = sync_pattern_detection(
        stock_codes=test_codes,
        lookback_days=120,
        period="daily"
    )

    logger.info(f"形态识别结果: {result}")

    # 查询识别到的形态
    patterns = execute_query(
        """
        SELECT stock_code, pattern_type, pattern_status, target_price, confidence
        FROM trade_technical_patterns
        WHERE stock_code IN ('600519', '000001', '000002')
        ORDER BY updated_at DESC
        LIMIT 10
        """
    )

    logger.info(f"识别到的形态:")
    for p in patterns:
        logger.info(f"  {p['stock_code']}: {p['pattern_type']} ({p['pattern_status']}) - 目标价: {p['target_price']}, 置信度: {p['confidence']}")

    return result['total_patterns'] >= 0


def test_strategy_backtest():
    """测试策略回测"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 4: 技术指标策略回测")
    logger.info("=" * 60)

    test_codes = ["600519"]
    strategies = ["ma_cross", "macd", "rsi", "ma_macd_combined"]

    end_date = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")  # 2年

    logger.info(f"回测区间: {start_date} ~ {end_date}")
    logger.info(f"测试策略: {strategies}")

    results = batch_backtest_strategies(
        stock_codes=test_codes,
        strategy_types=strategies,
        start_date=start_date,
        end_date=end_date,
        period="daily",
        save_to_db=True
    )

    logger.info(f"\n回测结果 ({len(results)} 个):")
    for r in results:
        metrics = r['metrics']
        logger.info(f"\n  策略: {r['strategy_type']}")
        logger.info(f"    年化收益: {metrics['annualized_return']:.2%}")
        logger.info(f"    夏普比率: {metrics.get('sharpe_ratio', 0):.2f}")
        logger.info(f"    最大回撤: {metrics['max_drawdown']:.2%}")
        logger.info(f"    胜率: {metrics.get('win_rate', 0):.2%}")
        logger.info(f"    交易次数: {metrics['trade_count']}")
        logger.info(f"    买入持有: {r['buy_hold_return']:.2%}")

    # 对比策略
    logger.info("\n策略对比:")
    comparison = compare_strategies_for_stock("600519", "daily")
    logger.info(f"  最佳策略: {comparison['best_strategy']}")
    logger.info(f"  最佳收益: {comparison['best_return']:.2%}")

    return len(results) > 0


def test_llm_report():
    """测试 LLM 技术分析报告生成"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 5: LLM 技术分析报告生成")
    logger.info("=" * 60)

    try:
        report = generate_technical_report(
            stock_code="600519",
            stock_name="贵州茅台",
            period="daily",
            llm_model="gpt-3.5-turbo"
        )

        logger.info(f"\n报告生成成功:")
        logger.info(f"  报告ID: {report['report_id']}")
        logger.info(f"  股票: {report['stock_name']} ({report['stock_code']})")
        logger.info(f"  日期: {report['report_date']}")
        logger.info(f"  技术评分: {report['technical_score']}/100")
        logger.info(f"  趋势方向: {report['trend_direction']}")
        logger.info(f"  信号强度: {report['signal_strength']}")

        logger.info(f"\n完整报告:")
        logger.info("-" * 60)
        logger.info(report['full_report'])
        logger.info("-" * 60)

        return True

    except Exception as e:
        logger.warning(f"LLM 报告生成失败（需要配置 OPENAI_API_KEY）: {e}")
        return False


def run_all_tests():
    """运行所有测试"""
    logger.info("\n" + "=" * 80)
    logger.info("QuantMind 技术分析功能测试")
    logger.info("=" * 80)

    tests = [
        ("技术指标计算（日线）", test_technical_indicators),
        ("周线月线指标计算", test_weekly_monthly_indicators),
        ("技术形态识别", test_pattern_detection),
        ("策略回测", test_strategy_backtest),
        ("LLM 分析报告", test_llm_report),
    ]

    results = {}
    for test_name, test_func in tests:
        try:
            success = test_func()
            results[test_name] = "✓ 通过" if success else "✗ 失败"
        except Exception as e:
            logger.exception(f"{test_name} 执行异常")
            results[test_name] = f"✗ 异常: {str(e)}"

    # 汇总结果
    logger.info("\n" + "=" * 80)
    logger.info("测试结果汇总")
    logger.info("=" * 80)
    for test_name, result in results.items():
        logger.info(f"  {test_name}: {result}")

    passed = sum(1 for r in results.values() if "✓" in r)
    total = len(results)
    logger.info(f"\n总计: {passed}/{total} 通过")


if __name__ == "__main__":
    run_all_tests()
