#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 sentiment_detail 表中空标题的记录

使用正文前50字作为标题
"""
from app.database import execute_query, execute_update


def fix_empty_titles():
    """修复空标题记录"""

    # 查询所有空标题记录
    empty_rows = execute_query('''
        SELECT id, news_text, summary
        FROM sentiment_detail
        WHERE news_title IS NULL OR news_title = '' OR news_title = '[]'
    ''')

    print(f'发现 {len(empty_rows)} 条空标题记录\n')

    if not empty_rows:
        print('✅ 没有需要修复的记录')
        return

    # 批量更新
    fixed = 0
    for row in empty_rows:
        record_id = row['id']
        news_text = row['news_text'] or ''
        summary = row['summary'] or ''

        # 优先使用 summary，否则使用 news_text 前50字
        if summary and summary.strip():
            new_title = summary.strip()[:100]
        elif news_text and news_text.strip():
            new_title = news_text.strip()[:50] + '...' if len(news_text) > 50 else news_text.strip()
        else:
            new_title = '[无标题]'

        # 更新标题
        execute_update(
            'UPDATE sentiment_detail SET news_title = %s WHERE id = %s',
            (new_title, record_id)
        )
        fixed += 1

        if fixed % 10 == 0:
            print(f'  已修复 {fixed}/{len(empty_rows)} 条记录...')

    print(f'\n✅ 成功修复 {fixed} 条记录')


if __name__ == '__main__':
    print('=== 修复空标题记录 ===\n')
    fix_empty_titles()
