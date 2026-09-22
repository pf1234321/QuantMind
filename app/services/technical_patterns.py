# -*- coding: utf-8 -*-
"""技术形态识别服务（头肩顶、双底、三角形等）"""
import logging
from datetime import date
from typing import Optional
import json

import pandas as pd
import numpy as np

from app.database import execute_query, execute_update, execute_many

logger = logging.getLogger(__name__)


class PatternDetector:
    """技术形态识别器"""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.peaks = []
        self.troughs = []
        self._find_extremes()

    def _find_extremes(self, window=5):
        """识别波峰和波谷"""
        highs = self.df['high'].values
        lows = self.df['low'].values

        for i in range(window, len(self.df) - window):
            # 波峰：周围最高点
            if highs[i] == max(highs[i-window:i+window+1]):
                self.peaks.append({
                    'index': i,
                    'date': self.df.index[i],
                    'price': highs[i]
                })

            # 波谷：周围最低点
            if lows[i] == min(lows[i-window:i+window+1]):
                self.troughs.append({
                    'index': i,
                    'date': self.df.index[i],
                    'price': lows[i]
                })

    def detect_head_shoulders_top(self) -> Optional[dict]:
        """识别头肩顶形态

        特征：
        1. 三个波峰，中间最高（头），两侧较低（肩）
        2. 左肩和右肩高度接近
        3. 颈线连接两个波谷
        """
        if len(self.peaks) < 3:
            return None

        # 检查最近的三个波峰
        recent_peaks = self.peaks[-3:]

        left_shoulder = recent_peaks[0]
        head = recent_peaks[1]
        right_shoulder = recent_peaks[2]

        # 判断条件
        # 1. 头部最高
        if not (head['price'] > left_shoulder['price'] and head['price'] > right_shoulder['price']):
            return None

        # 2. 左右肩高度接近（容忍度10%）
        shoulder_diff = abs(left_shoulder['price'] - right_shoulder['price']) / left_shoulder['price']
        if shoulder_diff > 0.10:
            return None

        # 3. 找到颈线（两个波谷之间的连线）
        troughs_between = [t for t in self.troughs
                          if left_shoulder['index'] < t['index'] < right_shoulder['index']]

        if len(troughs_between) < 2:
            return None

        neckline_left = troughs_between[0]
        neckline_right = troughs_between[-1]
        neckline_price = (neckline_left['price'] + neckline_right['price']) / 2

        # 计算目标价位（头部到颈线的距离）
        height = head['price'] - neckline_price
        target_price = neckline_price - height

        # 当前价格是否跌破颈线
        current_price = self.df['close'].iloc[-1]
        pattern_status = 'confirmed' if current_price < neckline_price else 'forming'

        return {
            'pattern_type': 'head_shoulders_top',
            'pattern_status': pattern_status,
            'start_date': left_shoulder['date'],
            'confirm_date': self.df.index[-1] if pattern_status == 'confirmed' else None,
            'target_price': float(target_price),
            'stop_loss': float(head['price']),
            'confidence': 0.75,
            'key_points': {
                'left_shoulder': {'date': str(left_shoulder['date']), 'price': float(left_shoulder['price'])},
                'head': {'date': str(head['date']), 'price': float(head['price'])},
                'right_shoulder': {'date': str(right_shoulder['date']), 'price': float(right_shoulder['price'])},
                'neckline': float(neckline_price)
            }
        }

    def detect_double_bottom(self) -> Optional[dict]:
        """识别双底形态（W底）

        特征：
        1. 两个波谷，高度接近
        2. 中间有一个波峰
        3. 突破中间波峰价格确认形态
        """
        if len(self.troughs) < 2:
            return None

        # 检查最近的两个波谷
        recent_troughs = self.troughs[-2:]

        first_bottom = recent_troughs[0]
        second_bottom = recent_troughs[1]

        # 1. 两个底部高度接近（容忍度5%）
        bottom_diff = abs(first_bottom['price'] - second_bottom['price']) / first_bottom['price']
        if bottom_diff > 0.05:
            return None

        # 2. 找到中间的波峰
        peaks_between = [p for p in self.peaks
                        if first_bottom['index'] < p['index'] < second_bottom['index']]

        if not peaks_between:
            return None

        middle_peak = peaks_between[0]
        neckline_price = middle_peak['price']

        # 计算目标价位（底部到颈线的距离）
        bottom_avg = (first_bottom['price'] + second_bottom['price']) / 2
        height = neckline_price - bottom_avg
        target_price = neckline_price + height

        # 当前价格是否突破颈线
        current_price = self.df['close'].iloc[-1]
        pattern_status = 'confirmed' if current_price > neckline_price else 'forming'

        return {
            'pattern_type': 'double_bottom',
            'pattern_status': pattern_status,
            'start_date': first_bottom['date'],
            'confirm_date': self.df.index[-1] if pattern_status == 'confirmed' else None,
            'target_price': float(target_price),
            'stop_loss': float(bottom_avg),
            'confidence': 0.80,
            'key_points': {
                'first_bottom': {'date': str(first_bottom['date']), 'price': float(first_bottom['price'])},
                'second_bottom': {'date': str(second_bottom['date']), 'price': float(second_bottom['price'])},
                'middle_peak': {'date': str(middle_peak['date']), 'price': float(middle_peak['price'])},
                'neckline': float(neckline_price)
            }
        }

    def detect_double_top(self) -> Optional[dict]:
        """识别双顶形态（M顶）"""
        if len(self.peaks) < 2:
            return None

        recent_peaks = self.peaks[-2:]
        first_top = recent_peaks[0]
        second_top = recent_peaks[1]

        # 两个顶部高度接近
        top_diff = abs(first_top['price'] - second_top['price']) / first_top['price']
        if top_diff > 0.05:
            return None

        # 找到中间的波谷
        troughs_between = [t for t in self.troughs
                          if first_top['index'] < t['index'] < second_top['index']]

        if not troughs_between:
            return None

        middle_trough = troughs_between[0]
        neckline_price = middle_trough['price']

        top_avg = (first_top['price'] + second_top['price']) / 2
        height = top_avg - neckline_price
        target_price = neckline_price - height

        current_price = self.df['close'].iloc[-1]
        pattern_status = 'confirmed' if current_price < neckline_price else 'forming'

        return {
            'pattern_type': 'double_top',
            'pattern_status': pattern_status,
            'start_date': first_top['date'],
            'confirm_date': self.df.index[-1] if pattern_status == 'confirmed' else None,
            'target_price': float(target_price),
            'stop_loss': float(top_avg),
            'confidence': 0.80,
            'key_points': {
                'first_top': {'date': str(first_top['date']), 'price': float(first_top['price'])},
                'second_top': {'date': str(second_top['date']), 'price': float(second_top['price'])},
                'middle_trough': {'date': str(middle_trough['date']), 'price': float(middle_trough['price'])},
                'neckline': float(neckline_price)
            }
        }

    def detect_ascending_triangle(self) -> Optional[dict]:
        """识别上升三角形

        特征：
        1. 上边界水平（多个波峰价格接近）
        2. 下边界上倾（波谷逐步抬高）
        3. 突破上边界确认形态
        """
        if len(self.peaks) < 3 or len(self.troughs) < 2:
            return None

        recent_peaks = self.peaks[-3:]
        recent_troughs = self.troughs[-2:]

        # 1. 检查波峰是否水平（容忍度3%）
        peak_prices = [p['price'] for p in recent_peaks]
        peak_std = np.std(peak_prices) / np.mean(peak_prices)
        if peak_std > 0.03:
            return None

        # 2. 检查波谷是否上升
        trough_prices = [t['price'] for t in recent_troughs]
        if not all(trough_prices[i] < trough_prices[i+1] for i in range(len(trough_prices)-1)):
            return None

        resistance = np.mean(peak_prices)
        current_price = self.df['close'].iloc[-1]
        pattern_status = 'confirmed' if current_price > resistance else 'forming'

        # 目标价位：三角形高度
        triangle_height = resistance - recent_troughs[0]['price']
        target_price = resistance + triangle_height

        return {
            'pattern_type': 'ascending_triangle',
            'pattern_status': pattern_status,
            'start_date': recent_troughs[0]['date'],
            'confirm_date': self.df.index[-1] if pattern_status == 'confirmed' else None,
            'target_price': float(target_price),
            'stop_loss': float(recent_troughs[-1]['price']),
            'confidence': 0.70,
            'key_points': {
                'resistance': float(resistance),
                'support_trend': [{'date': str(t['date']), 'price': float(t['price'])} for t in recent_troughs]
            }
        }

    def detect_descending_triangle(self) -> Optional[dict]:
        """识别下降三角形"""
        if len(self.peaks) < 2 or len(self.troughs) < 3:
            return None

        recent_peaks = self.peaks[-2:]
        recent_troughs = self.troughs[-3:]

        # 1. 检查波谷是否水平
        trough_prices = [t['price'] for t in recent_troughs]
        trough_std = np.std(trough_prices) / np.mean(trough_prices)
        if trough_std > 0.03:
            return None

        # 2. 检查波峰是否下降
        peak_prices = [p['price'] for p in recent_peaks]
        if not all(peak_prices[i] > peak_prices[i+1] for i in range(len(peak_prices)-1)):
            return None

        support = np.mean(trough_prices)
        current_price = self.df['close'].iloc[-1]
        pattern_status = 'confirmed' if current_price < support else 'forming'

        triangle_height = recent_peaks[0]['price'] - support
        target_price = support - triangle_height

        return {
            'pattern_type': 'descending_triangle',
            'pattern_status': pattern_status,
            'start_date': recent_peaks[0]['date'],
            'confirm_date': self.df.index[-1] if pattern_status == 'confirmed' else None,
            'target_price': float(target_price),
            'stop_loss': float(recent_peaks[-1]['price']),
            'confidence': 0.70,
            'key_points': {
                'support': float(support),
                'resistance_trend': [{'date': str(p['date']), 'price': float(p['price'])} for p in recent_peaks]
            }
        }

    def detect_all_patterns(self) -> list[dict]:
        """检测所有形态"""
        patterns = []

        # 头肩顶
        hst = self.detect_head_shoulders_top()
        if hst:
            patterns.append(hst)

        # 双底
        db = self.detect_double_bottom()
        if db:
            patterns.append(db)

        # 双顶
        dt = self.detect_double_top()
        if dt:
            patterns.append(dt)

        # 上升三角形
        at = self.detect_ascending_triangle()
        if at:
            patterns.append(at)

        # 下降三角形
        dt_tri = self.detect_descending_triangle()
        if dt_tri:
            patterns.append(dt_tri)

        return patterns


def sync_pattern_detection(
    stock_codes: Optional[list] = None,
    lookback_days: int = 120,
    period: str = "daily"
) -> dict:
    """同步技术形态识别"""

    if stock_codes is None:
        stock_codes = [r["stock_code"] for r in execute_query(
            "SELECT DISTINCT stock_code FROM trade_stock_status LIMIT 100"
        )]

    total_patterns = 0
    failed_stocks = []

    for code in stock_codes:
        try:
            # 获取K线数据
            end_date = date.today().strftime("%Y%m%d")
            start_date = (pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")

            klines = execute_query(
                """
                SELECT trade_date, open_price, high_price, low_price, close_price, volume
                FROM trade_stock_daily
                WHERE stock_code=%s AND trade_date>=%s AND trade_date<=%s
                ORDER BY trade_date ASC
                """,
                (code, start_date, end_date)
            )

            if not klines or len(klines) < 60:
                continue

            df = pd.DataFrame(klines)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date')
            df = df.rename(columns={
                'open_price': 'open',
                'high_price': 'high',
                'low_price': 'low',
                'close_price': 'close'
            })

            # 检测形态
            detector = PatternDetector(df)
            patterns = detector.detect_all_patterns()

            if not patterns:
                continue

            # 写入数据库
            for pattern in patterns:
                execute_update(
                    """
                    INSERT INTO trade_technical_patterns
                    (stock_code, pattern_type, pattern_status, start_date, confirm_date,
                     target_price, stop_loss, confidence, key_points_json, period)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    pattern_status=VALUES(pattern_status), confirm_date=VALUES(confirm_date),
                    target_price=VALUES(target_price), stop_loss=VALUES(stop_loss),
                    confidence=VALUES(confidence), key_points_json=VALUES(key_points_json)
                    """,
                    (
                        code,
                        pattern['pattern_type'],
                        pattern['pattern_status'],
                        pattern['start_date'],
                        pattern.get('confirm_date'),
                        pattern.get('target_price'),
                        pattern.get('stop_loss'),
                        pattern.get('confidence'),
                        json.dumps(pattern.get('key_points', {}), ensure_ascii=False),
                        period
                    )
                )
                total_patterns += 1

            logger.info(f"股票 {code} 识别到 {len(patterns)} 个形态")

        except Exception as exc:
            failed_stocks.append({"stock_code": code, "error": str(exc)})
            logger.exception(f"股票 {code} 形态识别失败")

    return {
        "total_patterns": total_patterns,
        "failed": len(failed_stocks),
        "total": len(stock_codes),
        "failed_stocks": failed_stocks
    }


def get_confirmed_patterns(
    stock_code: Optional[str] = None,
    pattern_type: Optional[str] = None,
    limit: int = 50
) -> list[dict]:
    """查询已确认的技术形态"""
    sql = "SELECT * FROM trade_technical_patterns WHERE pattern_status='confirmed'"
    params = []

    if stock_code:
        sql += " AND stock_code=%s"
        params.append(stock_code)

    if pattern_type:
        sql += " AND pattern_type=%s"
        params.append(pattern_type)

    sql += " ORDER BY confirm_date DESC LIMIT %s"
    params.append(limit)

    return execute_query(sql, params)
