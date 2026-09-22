# -*- coding: utf-8 -*-
"""情绪面数据同步（新闻情感分析 / 个股情绪聚合 / 市场事件 / 恐慌指数）

写入表:
  - sentiment_detail      每条新闻的 LLM/规则情感分析结果
  - sentiment_aggregate   个股情绪聚合（fear_greed_index 0-100）
  - market_events         从新闻识别出的重大事件与交易信号
  - fear_index_history    市场整体恐慌/贪婪指数历史

数据上游: trade_stock_news（news 任务抓取的原始新闻）
LLM 依赖: DASHSCOPE_API_KEY（Qwen，与 catalyst 一致）；未配置时自动降级为规则分析
"""
import json
import logging
import os
from datetime import datetime, timedelta

from app.database import execute_many, execute_query, execute_update

logger = logging.getLogger(__name__)

# 简单规则词典（无 API Key 时的降级分析）
POSITIVE_WORDS = [
    "增长", "上涨", "利好", "预增", "中标", "回购", "增持", "签约", "突破",
    "创新高", "涨停", "扭亏", "超预期", "分红", "送转", "获批", "领先", "新高",
]
NEGATIVE_WORDS = [
    "下滑", "下跌", "利空", "预减", "亏损", "减持", "违规", "处罚", "立案",
    "退市", "风险", "质押", "冻结", "诉讼", "仲裁", "商誉减值", "低于预期", "跌停",
]

# 事件子类型关键词 -> (event_type, event_subtype)
EVENT_KEYWORDS = [
    (["回购", "增持"], "利好", "回购增持"),
    (["中标", "签约", "订单"], "利好", "重大合同"),
    (["预增", "扭亏", "超预期"], "利好", "业绩预增"),
    (["分红", "送转"], "利好", "分红送转"),
    (["获批", "审批"], "利好", "项目获批"),
    (["减持"], "利空", "股东减持"),
    (["预减", "亏损", "商誉减值"], "利空", "业绩预减"),
    (["违规", "处罚", "立案"], "利空", "监管处罚"),
    (["退市", "风险警示"], "利空", "退市风险"),
    (["质押", "冻结"], "利空", "股权质押"),
    (["诉讼", "仲裁"], "利空", "诉讼仲裁"),
]

SENTIMENT_CN = {"positive": "正面", "negative": "负面", "neutral": "中性"}


def _has_api_key() -> bool:
    return bool(os.getenv("DASHSCOPE_API_KEY"))


def _call_qwen(prompt: str) -> str:
    """调用 Qwen（OpenAI 兼容模式），解析出 JSON 文本"""
    from openai import OpenAI

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("缺少环境变量 DASHSCOPE_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    completion = client.chat.completions.create(
        model=os.getenv("QWEN_MODEL", "qwen-max"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return completion.choices[0].message.content.strip()


def _extract_json(text: str) -> dict:
    """从 LLM 输出中提取 JSON 对象"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def _rule_sentiment(text: str) -> tuple[str, int]:
    """基于关键词词典的降级情感分析，返回 (sentiment, strength 1-5)"""
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos == neg:
        return "neutral", 1
    if pos > neg:
        strength = min(5, 2 + pos - neg)
        return "positive", strength
    strength = min(5, 2 + neg - pos)
    return "negative", strength


def _rule_analyze(title: str, content: str, source: str) -> dict:
    """规则降级分析：一条新闻 -> sentiment_detail 行数据"""
    text = f"{title} {content or ''}"
    sentiment, strength = _rule_sentiment(text)
    keywords = [w for w in POSITIVE_WORDS + NEGATIVE_WORDS if w in text][:10]
    impact = "positive" if sentiment == "positive" else "negative" if sentiment == "negative" else "neutral"
    return {
        "sentiment": sentiment,
        "strength": strength,
        "entities": [],
        "keywords": keywords,
        "summary": title[:180] if title else "",
        "market_impact": f"{SENTIMENT_CN.get(impact, impact)}影响",
        "news_source": source,
    }


LLM_PROMPT = """你是一位专业的 A 股新闻情感分析专家。请分析下面这条个股新闻，严格输出 JSON（不要输出其他内容）：
{{
  "sentiment": "positive|negative|neutral",
  "strength": 1到5的整数(情感强度，越强越大),
  "entities": ["涉及的公司/人物名称"],
  "keywords": ["3-5个核心关键词"],
  "summary": "一句话摘要(不超过60字)",
  "market_impact": "对该公司股价/基本面的影响分析(不超过100字)"
}}
新闻标题：{title}
新闻正文：{content}
股票代码：{stock_code}"""


def _llm_analyze(stock_code: str, title: str, content: str, source: str) -> dict:
    """LLM 情感分析单条新闻"""
    prompt = LLM_PROMPT.format(
        stock_code=stock_code,
        title=title[:300],
        content=(content or "")[:1500],
    )
    data = _extract_json(_call_qwen(prompt))
    sentiment = str(data.get("sentiment", "neutral"))
    if sentiment not in ("positive", "negative", "neutral"):
        sentiment = "neutral"
    return {
        "sentiment": sentiment,
        "strength": max(1, min(5, int(data.get("strength", 1) or 1))),
        "entities": data.get("entities", []),
        "keywords": data.get("keywords", [])[:10],
        "summary": str(data.get("summary", ""))[:200],
        "market_impact": str(data.get("market_impact", ""))[:500],
        "news_source": source,
    }


def _score_to_sentiment(score: float) -> str:
    if score > 0.2:
        return "positive"
    if score < -0.2:
        return "negative"
    return "neutral"


# 兼容历史数据：库里 sentiment 可能存中文（正面/负面/中性），统一归一为英文
_SENTIMENT_ALIASES = {
    "正面": "positive", "积极": "positive", "利好": "positive", "positive": "positive",
    "负面": "negative", "消极": "negative", "利空": "negative", "negative": "negative",
    "中性": "neutral", "neutral": "neutral", "": "neutral", None: "neutral",
}


def _norm_sentiment(s) -> str:
    """把中文/英文 sentiment 统一归一为英文枚举"""
    return _SENTIMENT_ALIASES.get(s, "neutral")


def _fetch_unanalyzed_news(days: int = 7, limit: int = 200) -> list[dict]:
    """取最近 days 天内未分析（sentiment 为空）的新闻"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return execute_query(
        "SELECT id, stock_code, title, content, source, published_at "
        "FROM trade_stock_news "
        "WHERE (sentiment IS NULL OR sentiment='') AND published_at >= %s "
        "ORDER BY published_at DESC LIMIT %s",
        (since, limit),
    )


def sync_sentiment_detail(days: int = 7, limit: int = 200) -> dict:
    """对未分析新闻做情感分析，写入 sentiment_detail 并回填 trade_stock_news

    优先 LLM（配置 DASHSCOPE_API_KEY），否则规则降级。
    """
    news_list = _fetch_unanalyzed_news(days=days, limit=limit)
    if not news_list:
        return {"source": "llm" if _has_api_key() else "rule", "written": 0, "total": 0}

    detail_rows = []
    update_rows = []
    use_llm = _has_api_key()
    analyzed = 0
    failed = 0

    for n in news_list:
        try:
            if use_llm:
                result = _llm_analyze(n["stock_code"], n["title"], n["content"], n["source"])
            else:
                result = _rule_analyze(n["title"], n["content"], n["source"])
        except Exception:  # noqa: BLE001 LLM 单条失败不阻塞整体
            logger.warning("[情感分析] 单条失败: id=%s", n["id"])
            failed += 1
            continue

        score = 0.0
        if result["sentiment"] == "positive":
            score = round(result["strength"] / 5.0, 2)
        elif result["sentiment"] == "negative":
            score = round(-result["strength"] / 5.0, 2)

        detail_rows.append((
            n["stock_code"], n["title"], n["content"], result["sentiment"],
            result["strength"], json.dumps(result["entities"], ensure_ascii=False),
            json.dumps(result["keywords"], ensure_ascii=False),
            result["summary"], result["market_impact"], result["news_source"],
            n["published_at"].date() if n["published_at"] else None,
        ))
        update_rows.append((result["sentiment"], score, n["id"]))
        analyzed += 1

    if detail_rows:
        execute_many(
            "INSERT INTO sentiment_detail "
            "(stock_code, news_title, news_text, sentiment, strength, entities, keywords, "
            " summary, market_impact, news_source, news_date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            detail_rows,
        )
        execute_many(
            "UPDATE trade_stock_news SET sentiment=%s, sentiment_score=%s WHERE id=%s",
            update_rows,
        )
    logger.info("[情感分析] 来源=%s 分析 %d 条 写入 %d 失败 %d",
                "llm" if use_llm else "rule", analyzed, len(detail_rows), failed)
    return {
        "source": "llm" if use_llm else "rule",
        "analyzed": analyzed,
        "written": len(detail_rows),
        "failed": failed,
        "total": len(news_list),
    }


def _calc_fear_greed(pos: int, neg: int, neutral: int) -> int:
    """由正/负/中计数计算 0-100 恐惧贪婪指数（50 中性）"""
    total = pos + neg + neutral
    if total == 0:
        return 50
    net = (pos - neg) / total  # -1 ~ 1
    return int(round(50 + net * 50))  # 0=极恐慌 100=极贪婪


def _overall_label(fgi: int) -> str:
    if fgi >= 75:
        return "贪婪"
    if fgi >= 60:
        return "乐观"
    if fgi >= 40:
        return "中性"
    if fgi >= 25:
        return "谨慎"
    return "恐慌"


def sync_sentiment_aggregate(days: int = 7) -> dict:
    """按股票聚合 sentiment_detail 成 sentiment_aggregate（每股票当日一条）"""
    # 取最近 days 天内有情感明细的股票
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    stocks = execute_query(
        "SELECT stock_code, COUNT(*) AS cnt "
        "FROM sentiment_detail WHERE news_date >= %s GROUP BY stock_code",
        (since,),
    )
    if not stocks:
        return {"written": 0, "stocks": 0}

    today = datetime.now().replace(microsecond=0)
    rows = []
    for s in stocks:
        code = s["stock_code"]
        stats = execute_query(
            "SELECT sentiment, COUNT(*) AS cnt FROM sentiment_detail "
            "WHERE stock_code=%s AND news_date >= %s GROUP BY sentiment",
            (code, since),
        )
        counter = {"positive": 0, "negative": 0, "neutral": 0}
        for row in stats:
            counter[_norm_sentiment(row["sentiment"])] += row["cnt"]
        pos, neg, neutral = counter["positive"], counter["negative"], counter["neutral"]
        fgi = _calc_fear_greed(pos, neg, neutral)
        top_themes = execute_query(
            "SELECT keywords FROM sentiment_detail "
            "WHERE stock_code=%s AND news_date >= %s AND keywords IS NOT NULL LIMIT 50",
            (code, since),
        )
        words: list[str] = []
        for t in top_themes:
            try:
                words.extend(json.loads(t["keywords"]))
            except (TypeError, json.JSONDecodeError):
                continue
        from collections import Counter as _Counter
        theme_counter = _Counter(words)
        themes = [w for w, _ in theme_counter.most_common(5)]

        risk_alerts = []
        opportunity_hints = []
        if neg >= pos and neg > 0:
            risk_alerts.append(f"负面新闻 {neg} 条，情绪偏空")
        if fgi <= 25:
            risk_alerts.append("恐慌区(<=25)，注意风险释放")
        if pos > neg and pos > 0:
            opportunity_hints.append(f"正面新闻 {pos} 条，情绪偏多")
        if fgi >= 75:
            opportunity_hints.append("贪婪区(>=75)，注意情绪过热回调")

        summary = (
            f"{code} 近{days}天共 {pos + neg + neutral} 条新闻："
            f"正面{pos} / 负面{neg} / 中性{neutral}，恐慌贪婪指数 {fgi}"
        )
        rows.append((
            code, fgi, _overall_label(fgi), pos, neg, neutral,
            json.dumps(themes, ensure_ascii=False),
            json.dumps(risk_alerts, ensure_ascii=False),
            json.dumps(opportunity_hints, ensure_ascii=False),
            summary, pos + neg + neutral, today,
        ))

    if rows:
        execute_many(
            "INSERT INTO sentiment_aggregate "
            "(stock_code, fear_greed_index, overall_sentiment, positive_count, negative_count, "
            " neutral_count, top_themes, risk_alerts, opportunity_hints, summary, news_count, analyzed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "fear_greed_index=VALUES(fear_greed_index), overall_sentiment=VALUES(overall_sentiment), "
            "positive_count=VALUES(positive_count), negative_count=VALUES(negative_count), "
            "neutral_count=VALUES(neutral_count), top_themes=VALUES(top_themes), "
            "risk_alerts=VALUES(risk_alerts), opportunity_hints=VALUES(opportunity_hints), "
            "summary=VALUES(summary), news_count=VALUES(news_count)",
            rows,
        )
    logger.info("[情绪聚合] 聚合 %d 只股票，写入 %d 条", len(stocks), len(rows))
    return {"written": len(rows), "stocks": len(stocks)}


def sync_market_events(days: int = 7) -> dict:
    """从情感明细中识别重大事件，写入 market_events

    规则：strength>=4 且 sentiment != neutral 的新闻视为事件，
    按事件关键词映射 event_type/subtype/signal。
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    candidates = execute_query(
        "SELECT d.stock_code, d.news_title, d.news_text, d.sentiment, d.strength, "
        "       d.summary, d.news_date, d.news_source "
        "FROM sentiment_detail d "
        "WHERE d.news_date >= %s AND d.sentiment NOT IN ('neutral', '中性') AND d.strength >= 4 "
        "ORDER BY d.news_date DESC LIMIT 500",
        (since,),
    )
    if not candidates:
        return {"written": 0, "events": 0}

    rows = []
    for c in candidates:
        sent = _norm_sentiment(c["sentiment"])
        if sent == "neutral":
            continue
        text = f"{c['news_title']} {c['news_text'] or ''} {c['summary'] or ''}"
        event_type, event_subtype, signal = "利好" if sent == "positive" else "利空", None, None
        for words, etype, subtype in EVENT_KEYWORDS:
            if any(w in text for w in words):
                event_type, event_subtype = etype, subtype
                break
        if sent == "positive":
            signal = "关注" if c["strength"] == 4 else "强烈关注"
        else:
            signal = "回避" if c["strength"] == 4 else "坚决回避"
        event_desc = c["summary"] or c["news_title"][:180]
        rows.append((
            c["stock_code"], event_type, event_subtype, event_desc,
            signal, c["news_date"],
        ))

    if rows:
        execute_many(
            "INSERT INTO market_events "
            "(stock_code, event_type, event_subtype, event_desc, `signal`, news_date) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )
    logger.info("[市场事件] 识别 %d 个事件，写入 %d 条", len(candidates), len(rows))
    return {"written": len(rows), "events": len(candidates)}


def _fetch_vix_ovx() -> tuple[float | None, float | None, float | None, float | None]:
    """从 yfinance 获取 VIX/OVX/GVZ/美债10Y；失败返回 (None,None,None,None)

    注意：Yahoo Finance 已封禁中国大陆访问，需要配置代理。
    可通过环境变量设置: HTTP_PROXY 或 HTTPS_PROXY
    """
    vix, ovx, gvz, us10y = None, None, None, None

    try:
        import yfinance as yf

        # 配置代理（如果环境变量中有）
        proxies = {}
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        if proxies:
            logger.debug("[恐慌指数] 使用代理: %s", proxies)

        # 设置 session（yfinance 内部使用）
        import requests
        session = requests.Session()
        if proxies:
            session.proxies.update(proxies)
            session.headers.update({"User-Agent": "Mozilla/5.0"})

        # VIX - 标普500波动率指数
        try:
            vix_ticker = yf.Ticker("^VIX", session=session)
            vix_hist = vix_ticker.history(period="5d")
            if not vix_hist.empty:
                vix = float(vix_hist.iloc[-1]["Close"])
                logger.debug("[VIX] 获取成功: %.2f", vix)
        except Exception as e:
            logger.warning("[VIX] 获取失败: %s", e)

        # OVX - 原油波动率指数
        try:
            ovx_ticker = yf.Ticker("^OVX", session=session)
            ovx_hist = ovx_ticker.history(period="5d")
            if not ovx_hist.empty:
                ovx = float(ovx_hist.iloc[-1]["Close"])
                logger.debug("[OVX] 获取成功: %.2f", ovx)
        except Exception as e:
            logger.warning("[OVX] 获取失败: %s", e)

        # GVZ - 黄金波动率指数
        try:
            gvz_ticker = yf.Ticker("^GVZ", session=session)
            gvz_hist = gvz_ticker.history(period="5d")
            if not gvz_hist.empty:
                gvz = float(gvz_hist.iloc[-1]["Close"])
                logger.debug("[GVZ] 获取成功: %.2f", gvz)
        except Exception as e:
            logger.warning("[GVZ] 获取失败: %s", e)

        # US10Y - 美国10年期国债收益率
        try:
            tnx_ticker = yf.Ticker("^TNX", session=session)
            tnx_hist = tnx_ticker.history(period="5d")
            if not tnx_hist.empty:
                us10y = float(tnx_hist.iloc[-1]["Close"])
                logger.debug("[US10Y] 获取成功: %.3f%%", us10y)
        except Exception as e:
            logger.warning("[US10Y] 获取失败: %s", e)

        return vix, ovx, gvz, us10y

    except ImportError:
        logger.error("[恐慌指数] yfinance 或 requests 未安装")
        return None, None, None, None
    except Exception as e:
        logger.warning("[恐慌指数] yfinance 拉取失败: %s", e, exc_info=True)
        return None, None, None, None


def _load_market_fear_greed(days: int = 3) -> tuple[int, int, int]:
    """基于 sentiment_aggregate 汇总市场整体情绪，返回 (fgi均值, 股票数, 新闻数)"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = execute_query(
        "SELECT COUNT(*) AS stocks, SUM(news_count) AS news, "
        "       ROUND(AVG(fear_greed_index)) AS avg_fgi "
        "FROM sentiment_aggregate WHERE analyzed_at >= %s",
        (since,),
    )
    r = rows[0] if rows else {}
    avg = int(r.get("avg_fgi") or 50)
    stocks = int(r.get("stocks") or 0)
    news = int(r.get("news") or 0)
    return avg, stocks, news


def sync_fear_index(days: int = 3) -> dict:
    """计算市场恐慌/贪婪指数写入 fear_index_history

    综合 VIX(外部) 与个股情绪聚合(内部)：
      composite = vix 归一化(0-100) 与内部 fgi 的加权平均

    数据获取策略（按优先级）：
      1. yfinance + 代理（最准确）
      2. 国内数据源降级（sentiment_sync_fallback）
      3. 纯情绪聚合计算
    """
    # 先尝试主数据源
    vix, ovx, gvz, us10y = _fetch_vix_ovx()

    # 如果主数据源失败，尝试降级方案
    if vix is None and ovx is None and gvz is None and us10y is None:
        try:
            from app.services.sentiment_sync_fallback import fetch_vix_ovx_with_fallback
            vix, ovx, gvz, us10y = fetch_vix_ovx_with_fallback()
            if vix is not None or us10y is not None:
                logger.info("[恐慌指数] 使用降级数据源成功")
        except ImportError:
            logger.debug("[恐慌指数] 降级模块未启用")
        except Exception as e:
            logger.warning("[恐慌指数] 降级数据源失败: %s", e)

    fgi, stocks, news = _load_market_fear_greed(days=days)

    # VIX 映射：20 以下偏贪婪(>50)，40 以上偏恐慌(<20)  [vix -> 100 分制]
    vix_fgi = None
    if vix is not None:
        vix_fgi = max(0, min(100, int(round(100 - (vix - 12) * 3.5))))

    if vix_fgi is not None and stocks > 0:
        composite = int(round(vix_fgi * 0.4 + fgi * 0.6))
    elif vix_fgi is not None:
        composite = vix_fgi
    else:
        composite = fgi

    risk_level = _overall_label(composite)
    suggestion = (
        "极端恐慌区域，历史统计上接近情绪底部，可关注错杀机会，但需结合基本面确认。"
        if composite <= 25 else
        "恐慌偏谨慎区域，注意控制仓位，等待情绪企稳信号。"
        if composite < 40 else
        "情绪中性，按常规策略执行，关注结构行情。"
        if composite <= 60 else
        "乐观区域，持股为主，注意高位个股回调风险。"
        if composite < 75 else
        "贪婪过热区域，历史统计上接近情绪顶部，注意兑现收益、防范回调。"
    )

    execute_update(
        "INSERT INTO fear_index_history "
        "(vix, ovx, gvz, us10y, composite_score, risk_level, suggestion) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (vix, ovx, gvz, us10y, composite, risk_level, suggestion),
    )
    logger.info("[恐慌指数] composite=%d risk_level=%s (vix=%s fgi=%d stocks=%d)",
                composite, risk_level, vix, fgi, stocks)
    return {
        "vix": vix, "ovx": ovx, "gvz": gvz, "us10y": us10y,
        "composite_score": composite, "risk_level": risk_level,
        "market_fgi": fgi, "stocks": stocks, "news_count": news,
    }
