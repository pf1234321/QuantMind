#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 sentiment_detail 表中空 news_source 的记录

策略：
1. 优先从正文内容中识别常见媒体来源
2. 如果无法识别，设置为"未知来源"
"""
from app.database import execute_query, execute_update


# 常见新闻来源列表
NEWS_SOURCES = [
    '东方财富', '东方财富网',
    '证券时报', '证券时报网',
    '澎湃新闻',
    '大河财立方',
    '数据宝',
    '每日经济新闻',
    '新浪财经',
    '界面新闻',
    '财联社',
    '中国证券报',
    '上海证券报',
    '第一财经',
    '经济观察报',
    '21世纪经济报道',
    '财经网',
    '和讯网',
    '金融界',
    '同花顺',
    '雪球',
    '格隆汇',
]


def extract_source_from_text(text: str) -> str:
    """从文本中提取新闻来源"""
    if not text:
        return '未知来源'

    # 检查常见来源
    for source in NEWS_SOURCES:
        if source in text:
            return source

    # 检查是否包含"记者"字样，提取前面的媒体名称
    import re

    # 匹配"【媒体名记者】"或"媒体名记者"
    match = re.search(r'【([^】]+)记者', text)
    if match:
        return match.group(1)

    match = re.search(r'([^\s]{2,6})记者', text)
    if match:
        potential_source = match.group(1)
        # 排除人名（通常2-3个字）
        if len(potential_source) >= 3:
            return potential_source

    return '未知来源'


def fix_empty_sources():
    """修复空来源记录"""

    # 查询所有空来源记录
    empty_rows = execute_query('''
        SELECT id, news_text, news_title
        FROM sentiment_detail
        WHERE news_source IS NULL OR news_source = ''
    ''')

    print(f'发现 {len(empty_rows)} 条空来源记录\n')

    if not empty_rows:
        print('✅ 没有需要修复的记录')
        return

    # 统计来源
    source_stats = {}

    # 批量更新
    fixed = 0
    for row in empty_rows:
        record_id = row['id']
        news_text = row['news_text'] or ''
        news_title = row['news_title'] or ''

        # 尝试从正文或标题中提取来源
        combined_text = news_title + ' ' + news_text[:500]
        source = extract_source_from_text(combined_text)

        # 统计
        source_stats[source] = source_stats.get(source, 0) + 1

        # 更新来源
        execute_update(
            'UPDATE sentiment_detail SET news_source = %s WHERE id = %s',
            (source, record_id)
        )
        fixed += 1

        if fixed % 10 == 0:
            print(f'  已修复 {fixed}/{len(empty_rows)} 条记录...')

    print(f'\n✅ 成功修复 {fixed} 条记录')
    print(f'\n来源分布：')
    for source, count in sorted(source_stats.items(), key=lambda x: x[1], reverse=True):
        print(f'  {source}: {count} 条')


if __name__ == '__main__':
    print('=== 修复空来源记录 ===\n')
    fix_empty_sources()
