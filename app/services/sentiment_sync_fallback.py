# -*- coding: utf-8 -*-
"""恐慌指数数据获取备选方案（国内可用）

当 Yahoo Finance 不可访问时的降级策略：
1. 优先使用代理访问 yfinance
2. 降级使用国内数据源（东方财富、新浪财经等）
3. 最终降级：基于 A 股情绪聚合计算
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_vix_from_eastmoney() -> Optional[float]:
    """从东方财富获取 VIX（通过全球指数接口）"""
    try:
        import akshare as ak
        # 东方财富全球指数
        df = ak.index_investing_global(country="美国", symbol="标普500波动率", period="每日")
        if df is not None and not df.empty:
            # 获取最新收盘价
            latest = df.iloc[-1]
            vix_value = float(latest["收盘"])
            logger.info("[VIX-东方财富] 获取成功: %.2f", vix_value)
            return vix_value
    except Exception as e:
        logger.debug("[VIX-东方财富] 获取失败: %s", e)
    return None


def fetch_us10y_from_sina() -> Optional[float]:
    """从新浪财经获取美国10年期国债收益率"""
    try:
        import requests
        # 新浪财经接口
        url = "https://hq.sinajs.cn/list=gb_$tnx"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()

        # 解析返回数据：gb_$tnx="name,current,..."
        content = resp.text.strip()
        if 'gb_$tnx="' in content:
            data = content.split('"')[1].split(',')
            if len(data) > 1:
                us10y_value = float(data[1])  # 当前价格即收益率
                logger.info("[US10Y-新浪] 获取成功: %.3f%%", us10y_value)
                return us10y_value
    except Exception as e:
        logger.debug("[US10Y-新浪] 获取失败: %s", e)
    return None


def fetch_vix_ovx_with_fallback() -> tuple[float | None, float | None, float | None, float | None]:
    """带降级的恐慌指数获取

    优先级：
    1. yfinance + 代理（最准确）
    2. 国内数据源拼凑（VIX 东方财富 + US10Y 新浪）
    3. 返回 None（由调用方基于情绪聚合计算）

    Returns:
        (vix, ovx, gvz, us10y)
    """
    vix, ovx, gvz, us10y = None, None, None, None

    # 尝试 1：yfinance（如果配置了代理）
    if os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY"):
        try:
            from app.services.sentiment_sync import _fetch_vix_ovx
            vix, ovx, gvz, us10y = _fetch_vix_ovx()
            if vix is not None:
                logger.info("[恐慌指数] yfinance 获取成功")
                return vix, ovx, gvz, us10y
        except Exception as e:
            logger.warning("[恐慌指数] yfinance 失败，尝试降级: %s", e)

    # 尝试 2：国内数据源拼凑
    logger.info("[恐慌指数] 使用国内数据源降级方案")

    # VIX - 尝试东方财富
    vix = fetch_vix_from_eastmoney()

    # US10Y - 尝试新浪财经
    us10y = fetch_us10y_from_sina()

    # OVX/GVZ 国内暂无稳定数据源，保持 None
    if vix is None and us10y is None:
        logger.warning("[恐慌指数] 所有数据源均失败，将基于情绪聚合计算")
    else:
        logger.info("[恐慌指数] 国内源获取: VIX=%s, US10Y=%s", vix, us10y)

    return vix, ovx, gvz, us10y


def estimate_vix_from_ashare() -> Optional[float]:
    """从 A 股波动率估算 VIX（极端降级方案）

    逻辑：
    - 计算上证指数近 30 日收益率标准差
    - 年化后映射到 VIX 量级（10-40 区间）
    """
    try:
        import akshare as ak
        import pandas as pd

        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return None

        # 取最近 30 个交易日
        recent = df.tail(30)
        if len(recent) < 10:
            return None

        # 计算收益率标准差
        recent["return"] = recent["close"].pct_change()
        volatility = recent["return"].std()

        # 年化波动率（假设 252 个交易日）
        annual_vol = volatility * (252 ** 0.5) * 100

        # 映射到 VIX 量级：A 股波动率通常高于美股，缩放系数 0.7
        estimated_vix = annual_vol * 0.7
        estimated_vix = max(10, min(50, estimated_vix))  # 限制在合理区间

        logger.info("[VIX-估算] 基于上证波动率估算: %.2f", estimated_vix)
        return float(estimated_vix)
    except Exception as e:
        logger.debug("[VIX-估算] 失败: %s", e)
    return None
