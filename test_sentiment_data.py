#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试舆情分析师数据问题"""

from app.database import execute_query

def test_sentiment_data():
    print("=" * 60)
    print("诊断：舆情分析师数据缺失问题")
    print("=" * 60)

    # 1. 检查 sentiment_detail 表
    print("\n【1】sentiment_detail 表检查")
    print("-" * 60)

    detail_count = execute_query("SELECT COUNT(*) as cnt FROM sentiment_detail", ())
    print(f"总记录数: {detail_count[0]['cnt']}")

    # 按股票代码统计
    detail_by_stock = execute_query(
        "SELECT stock_code, COUNT(*) as cnt FROM sentiment_detail GROUP BY stock_code ORDER BY cnt DESC",
        ()
    )
    print(f"\n按股票代码统计 (共 {len(detail_by_stock)} 只股票):")
    for row in detail_by_stock[:10]:
        print(f"  {row['stock_code']}: {row['cnt']} 条")

    # 测试查询 600519
    print(f"\n测试查询 600519:")
    detail_600519 = execute_query(
        "SELECT stock_code, news_title, sentiment, strength, news_source, news_date, analyzed_at "
        "FROM sentiment_detail WHERE stock_code='600519' ORDER BY analyzed_at DESC LIMIT 5",
        ()
    )
    print(f"  找到 {len(detail_600519)} 条记录")
    for row in detail_600519:
        print(f"    - {row['news_date']}: {row['news_title'][:30] if row['news_title'] else '(空标题)'} | {row['sentiment']}")

    # 2. 检查 market_events 表
    print("\n【2】market_events 表检查")
    print("-" * 60)

    events_count = execute_query("SELECT COUNT(*) as cnt FROM market_events", ())
    print(f"总记录数: {events_count[0]['cnt']}")

    # 按股票代码统计
    events_by_stock = execute_query(
        "SELECT stock_code, COUNT(*) as cnt FROM market_events GROUP BY stock_code ORDER BY cnt DESC",
        ()
    )
    print(f"\n按股票代码统计 (共 {len(events_by_stock)} 只股票):")
    for row in events_by_stock[:10]:
        print(f"  {row['stock_code']}: {row['cnt']} 条")

    # 测试查询 600519
    print(f"\n测试查询 600519:")
    events_600519 = execute_query(
        "SELECT stock_code, event_type, event_subtype, event_desc, signal, news_date, created_at "
        "FROM market_events WHERE stock_code='600519' ORDER BY created_at DESC LIMIT 5",
        ()
    )
    print(f"  找到 {len(events_600519)} 条记录")
    for row in events_600519:
        print(f"    - {row['news_date']}: [{row['event_type']}] {row['event_desc'][:40] if row['event_desc'] else '(空描述)'}")

    # 3. 检查 sentiment_aggregate 表
    print("\n【3】sentiment_aggregate 表检查")
    print("-" * 60)

    agg_count = execute_query("SELECT COUNT(*) as cnt FROM sentiment_aggregate", ())
    print(f"总记录数: {agg_count[0]['cnt']}")

    agg_600519 = execute_query(
        "SELECT stock_code, fear_greed_index, overall_sentiment, news_count, analyzed_at "
        "FROM sentiment_aggregate WHERE stock_code='600519' ORDER BY analyzed_at DESC LIMIT 3",
        ()
    )
    print(f"\n600519 聚合数据: {len(agg_600519)} 条")
    for row in agg_600519:
        print(f"  - {row['analyzed_at']}: FGI={row['fear_greed_index']}, 情绪={row['overall_sentiment']}, 新闻数={row['news_count']}")

    # 4. 总结
    print("\n" + "=" * 60)
    print("【诊断结论】")
    print("=" * 60)

    if detail_count[0]['cnt'] == 0:
        print("❌ sentiment_detail 表为空 - 需要执行 sentiment 同步任务")
    elif len(detail_600519) == 0:
        print(f"⚠️  sentiment_detail 表有数据，但 600519 无记录")
        print(f"   可用股票代码: {[r['stock_code'] for r in detail_by_stock[:5]]}")
    else:
        print(f"✅ sentiment_detail 表正常，600519 有 {len(detail_600519)} 条记录")

    if events_count[0]['cnt'] == 0:
        print("❌ market_events 表为空 - 需要执行 events 同步任务")
    elif len(events_600519) == 0:
        print(f"⚠️  market_events 表有数据，但 600519 无记录")
        print(f"   可用股票代码: {[r['stock_code'] for r in events_by_stock[:5]]}")
    else:
        print(f"✅ market_events 表正常，600519 有 {len(events_600519)} 条记录")

if __name__ == "__main__":
    test_sentiment_data()
