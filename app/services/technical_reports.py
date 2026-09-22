# -*- coding: utf-8 -*-
"""LLM 技术分析报告生成服务"""
import logging
import json
from datetime import date, timedelta
from typing import Optional
import hashlib

from app.database import execute_query, execute_update
from app.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


TECHNICAL_ANALYSIS_PROMPT = """你是一位专业的技术分析师，请基于以下数据为股票 {stock_name}({stock_code}) 生成一份技术分析报告。

# 当前价格与指标数据
交易日期: {trade_date}
收盘价: {close_price}
涨跌幅: {change_pct}%

## 趋势指标
- MA5: {ma5} (5日均线)
- MA20: {ma20} (20日均线)
- MA60: {ma60} (60日均线)
- 均线排列: {ma_alignment}

## 动量指标
- RSI(14): {rsi14}
- MACD DIF: {macd_dif}
- MACD DEA: {macd_dea}
- MACD 柱: {macd_bar}

## KDJ指标
- K值: {kdj_k}
- D值: {kdj_d}
- J值: {kdj_j}

## 波动率
- ATR(14): {atr14}
- 量比: {volume_ratio}

# 识别到的技术形态
{patterns_info}

# 历史回测数据（最佳策略）
{backtest_info}

---

请按以下结构生成报告（使用中文，专业严谨）：

## 1. 趋势分析
分析当前趋势方向（上升/下降/横盘），基于均线排列、价格走势给出判断。

## 2. 形态分析
分析识别到的技术形态，说明形态的意义、目标价位、风险点。

## 3. 指标分析
综合分析 RSI、MACD、KDJ 的信号，判断是否超买/超卖，动能强弱。

## 4. 成交量分析
分析量比、成交量与价格的配合情况。

## 5. 支撑与阻力
基于均线和技术形态，指出关键的支撑位和阻力位。

## 6. 交易建议
给出具体的操作建议：买入/卖出/观望，以及建议的仓位、止损位、目标位。

## 7. 风险提示
指出当前技术面的主要风险点。

## 8. 技术面评分
给出 0-100 的技术面评分，以及信号强度（强/中/弱）。

请保持客观中立，基于数据分析，不做主观臆断。
"""


def generate_technical_report(
    stock_code: str,
    stock_name: Optional[str] = None,
    period: str = "daily",
    llm_model: str = "gpt-4"
) -> dict:
    """生成技术分析报告"""

    # 1. 获取股票基本信息
    if not stock_name:
        stock_info = execute_query(
            "SELECT stock_name FROM trade_stock_status WHERE stock_code=%s",
            (stock_code,)
        )
        stock_name = stock_info[0]['stock_name'] if stock_info else stock_code

    # 2. 获取最新技术指标
    indicators = execute_query(
        """
        SELECT * FROM trade_technical_summary
        WHERE stock_code=%s AND period=%s
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (stock_code, period)
    )

    if not indicators:
        raise ValueError(f"未找到股票 {stock_code} 的技术指标数据，请先执行指标计算")

    latest = indicators[0]

    # 3. 获取最新K线价格
    kline = execute_query(
        """
        SELECT trade_date, close_price, open_price
        FROM trade_stock_daily
        WHERE stock_code=%s
        ORDER BY trade_date DESC
        LIMIT 2
        """,
        (stock_code,)
    )

    if not kline or len(kline) < 2:
        raise ValueError(f"未找到股票 {stock_code} 的K线数据")

    current = kline[0]
    previous = kline[1]
    change_pct = (current['close_price'] - previous['close_price']) / previous['close_price'] * 100

    # 4. 判断均线排列
    ma5 = latest.get('ma5')
    ma20 = latest.get('ma20')
    ma60 = latest.get('ma60')

    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            ma_alignment = "多头排列（看涨）"
        elif ma5 < ma20 < ma60:
            ma_alignment = "空头排列（看跌）"
        else:
            ma_alignment = "交叉震荡"
    else:
        ma_alignment = "数据不足"

    # 5. 获取技术形态
    patterns = execute_query(
        """
        SELECT pattern_type, pattern_status, target_price, stop_loss, confidence
        FROM trade_technical_patterns
        WHERE stock_code=%s AND pattern_status IN ('forming', 'confirmed')
        ORDER BY updated_at DESC
        LIMIT 5
        """,
        (stock_code,)
    )

    if patterns:
        patterns_info = "\n".join([
            f"- {p['pattern_type']} ({p['pattern_status']}): "
            f"目标价 {p['target_price']}, 止损 {p['stop_loss']}, 置信度 {p['confidence']}"
            for p in patterns
        ])
    else:
        patterns_info = "暂无明显技术形态"

    # 6. 获取最佳回测策略
    backtest = execute_query(
        """
        SELECT strategy_type, annualized_return, sharpe_ratio, max_drawdown, win_rate
        FROM trade_technical_backtest
        WHERE stock_code=%s AND period=%s
        ORDER BY annualized_return DESC
        LIMIT 1
        """,
        (stock_code, period)
    )

    if backtest:
        bt = backtest[0]
        backtest_info = (
            f"最佳策略: {bt['strategy_type']}\n"
            f"年化收益: {bt['annualized_return']:.2%}\n"
            f"夏普比率: {bt['sharpe_ratio']:.2f}\n"
            f"最大回撤: {bt['max_drawdown']:.2%}\n"
            f"胜率: {bt['win_rate']:.2%}"
        )
    else:
        backtest_info = "暂无历史回测数据"

    # 7. 构建 prompt
    prompt = TECHNICAL_ANALYSIS_PROMPT.format(
        stock_name=stock_name,
        stock_code=stock_code,
        trade_date=current['trade_date'],
        close_price=current['close_price'],
        change_pct=f"{change_pct:+.2f}",
        ma5=ma5 or "N/A",
        ma20=ma20 or "N/A",
        ma60=ma60 or "N/A",
        ma_alignment=ma_alignment,
        rsi14=latest.get('rsi14') or "N/A",
        macd_dif=latest.get('macd_dif') or "N/A",
        macd_dea=latest.get('macd_dea') or "N/A",
        macd_bar=latest.get('macd_bar') or "N/A",
        kdj_k=latest.get('kdj_k') or "N/A",
        kdj_d=latest.get('kdj_d') or "N/A",
        kdj_j=latest.get('kdj_j') or "N/A",
        atr14=latest.get('atr14') or "N/A",
        volume_ratio=latest.get('volume_ratio') or "N/A",
        patterns_info=patterns_info,
        backtest_info=backtest_info
    )

    # 8. 调用 LLM 生成报告
    try:
        client = get_llm_client()
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "你是一位专业的股票技术分析师，擅长技术指标和形态分析。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        report_text = response.choices[0].message.content

        # 9. 解析报告内容（简单分段）
        sections = _parse_report_sections(report_text)

        # 10. 提取评分和信号强度
        technical_score, trend_direction, signal_strength = _extract_scoring(report_text)

        # 11. 保存到数据库
        report_id = hashlib.md5(
            f"{stock_code}_{current['trade_date']}_{period}".encode()
        ).hexdigest()[:16]

        indicators_snapshot = {
            'trade_date': str(current['trade_date']),
            'close_price': float(current['close_price']),
            'ma5': float(ma5) if ma5 else None,
            'ma20': float(ma20) if ma20 else None,
            'ma60': float(ma60) if ma60 else None,
            'rsi14': float(latest.get('rsi14')) if latest.get('rsi14') else None,
            'macd_dif': float(latest.get('macd_dif')) if latest.get('macd_dif') else None,
            'kdj_j': float(latest.get('kdj_j')) if latest.get('kdj_j') else None,
        }

        execute_update(
            """
            INSERT INTO trade_technical_reports
            (report_id, stock_code, stock_name, report_date, period,
             trend_analysis, pattern_analysis, indicator_analysis, volume_analysis,
             support_resistance, trading_suggestion, risk_warning,
             technical_score, trend_direction, signal_strength,
             indicators_snapshot_json, patterns_snapshot_json, llm_model)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            trend_analysis=VALUES(trend_analysis), pattern_analysis=VALUES(pattern_analysis),
            indicator_analysis=VALUES(indicator_analysis), volume_analysis=VALUES(volume_analysis),
            support_resistance=VALUES(support_resistance), trading_suggestion=VALUES(trading_suggestion),
            risk_warning=VALUES(risk_warning), technical_score=VALUES(technical_score),
            trend_direction=VALUES(trend_direction), signal_strength=VALUES(signal_strength),
            indicators_snapshot_json=VALUES(indicators_snapshot_json),
            patterns_snapshot_json=VALUES(patterns_snapshot_json)
            """,
            (
                report_id,
                stock_code,
                stock_name,
                current['trade_date'],
                period,
                sections.get('trend_analysis'),
                sections.get('pattern_analysis'),
                sections.get('indicator_analysis'),
                sections.get('volume_analysis'),
                sections.get('support_resistance'),
                sections.get('trading_suggestion'),
                sections.get('risk_warning'),
                technical_score,
                trend_direction,
                signal_strength,
                json.dumps(indicators_snapshot, ensure_ascii=False),
                json.dumps([dict(p) for p in patterns], ensure_ascii=False, default=str),
                llm_model
            )
        )

        logger.info(f"技术分析报告生成完成: {stock_code} {stock_name}")

        return {
            'report_id': report_id,
            'stock_code': stock_code,
            'stock_name': stock_name,
            'report_date': str(current['trade_date']),
            'full_report': report_text,
            'sections': sections,
            'technical_score': technical_score,
            'trend_direction': trend_direction,
            'signal_strength': signal_strength,
            'indicators': indicators_snapshot,
            'patterns': patterns
        }

    except Exception as e:
        logger.exception(f"LLM 调用失败: {stock_code}")
        raise


def _parse_report_sections(report_text: str) -> dict:
    """解析报告的各个章节"""
    sections = {}

    section_markers = {
        'trend_analysis': ['## 1. 趋势分析', '##1.趋势分析', '## 趋势分析'],
        'pattern_analysis': ['## 2. 形态分析', '##2.形态分析', '## 形态分析'],
        'indicator_analysis': ['## 3. 指标分析', '##3.指标分析', '## 指标分析'],
        'volume_analysis': ['## 4. 成交量分析', '##4.成交量分析', '## 成交量分析'],
        'support_resistance': ['## 5. 支撑与阻力', '##5.支撑与阻力', '## 支撑与阻力'],
        'trading_suggestion': ['## 6. 交易建议', '##6.交易建议', '## 交易建议'],
        'risk_warning': ['## 7. 风险提示', '##7.风险提示', '## 风险提示'],
    }

    lines = report_text.split('\n')
    current_section = None
    section_content = []

    for line in lines:
        # 检查是否是新章节
        is_new_section = False
        for section_key, markers in section_markers.items():
            if any(marker in line for marker in markers):
                # 保存上一章节
                if current_section and section_content:
                    sections[current_section] = '\n'.join(section_content).strip()

                current_section = section_key
                section_content = []
                is_new_section = True
                break

        if not is_new_section and current_section:
            # 排除章节标题行和空行
            if line.strip() and not line.startswith('##'):
                section_content.append(line)

    # 保存最后一个章节
    if current_section and section_content:
        sections[current_section] = '\n'.join(section_content).strip()

    return sections


def _extract_scoring(report_text: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """从报告中提取评分和信号强度"""
    import re

    # 提取技术面评分
    score_match = re.search(r'技术面评分[：:]\s*(\d+)', report_text)
    technical_score = int(score_match.group(1)) if score_match else None

    # 提取趋势方向
    trend_direction = None
    if '上升趋势' in report_text or '看涨' in report_text or '多头' in report_text:
        trend_direction = 'bullish'
    elif '下降趋势' in report_text or '看跌' in report_text or '空头' in report_text:
        trend_direction = 'bearish'
    else:
        trend_direction = 'neutral'

    # 提取信号强度
    signal_strength = None
    if '强烈' in report_text or '信号强' in report_text:
        signal_strength = 'strong'
    elif '较弱' in report_text or '信号弱' in report_text:
        signal_strength = 'weak'
    else:
        signal_strength = 'medium'

    return technical_score, trend_direction, signal_strength


def get_latest_report(stock_code: str, period: str = "daily") -> Optional[dict]:
    """获取最新的技术分析报告"""
    reports = execute_query(
        """
        SELECT * FROM trade_technical_reports
        WHERE stock_code=%s AND period=%s
        ORDER BY report_date DESC
        LIMIT 1
        """,
        (stock_code, period)
    )

    return reports[0] if reports else None


def batch_generate_reports(
    stock_codes: list[str],
    period: str = "daily",
    llm_model: str = "gpt-4"
) -> dict:
    """批量生成技术分析报告"""

    success = []
    failed = []

    for code in stock_codes:
        try:
            report = generate_technical_report(code, period=period, llm_model=llm_model)
            success.append(report['report_id'])
            logger.info(f"报告生成成功: {code}")
        except Exception as e:
            failed.append({'stock_code': code, 'error': str(e)})
            logger.exception(f"报告生成失败: {code}")

    return {
        'total': len(stock_codes),
        'success': len(success),
        'failed': len(failed),
        'success_list': success,
        'failed_list': failed
    }
