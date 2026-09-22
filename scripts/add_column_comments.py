import pymysql

DB = {
    "host": "localhost",
    "port": 3309,
    "user": "root",
    "password": "root",
    "database": "wucai_trade",
    "charset": "utf8mb4",
}

TABLE_COMMENTS = {
    "fear_index_history": "恐慌指数历史表",
    "market_events": "市场事件表",
    "sentiment_aggregate": "情绪聚合分析表",
    "sentiment_detail": "情绪明细分析表",
    "chan_signals": "缠论交易信号表",
    "diagnosis_agent_result": "个股诊断智能体分析结果表",
    "diagnosis_backtest_link": "个股诊断回测关联配置表",
    "diagnosis_consensus": "个股诊断共识结果表",
    "diagnosis_debate": "个股诊断多空辩论结果表",
    "diagnosis_event": "个股诊断事件与催化剂表",
    "diagnosis_notification": "个股诊断通知记录表",
    "diagnosis_quant_result": "个股诊断量化结果表",
    "diagnosis_research_evidence": "个股诊断研究报告证据表",
    "diagnosis_research_report": "个股诊断研究报告表",
    "diagnosis_schedule": "个股诊断定时任务表",
    "diagnosis_watchlist": "个股诊断自选股列表表",
    "diagnosis_watchlist_item": "个股诊断自选股明细表",
    "qlib_research_log": "Qlib因子研究运行日志表",
    "qlib_research_prediction": "Qlib因子研究预测结果表",
    "qlib_research_run": "Qlib因子研究运行记录表",
    "risk_alert": "组合风控告警表",
    "risk_decision": "组合风控决策表",
    "risk_portfolio_snapshot": "投资组合风控快照表",
    "stock_diagnosis_task": "个股诊断任务表",
    "trade_plan": "交易计划表",
}

COMMON_FIELD_COMMENTS = {
    "id": "自增主键", "stock_code": "股票代码", "stock_name": "股票简称",
    "sector_name": "板块名称", "sector_level": "板块层级", "trade_date": "交易日期",
    "created_at": "创建时间", "updated_at": "更新时间", "started_at": "开始时间",
    "finished_at": "完成时间", "status": "状态", "progress": "执行进度",
    "message": "消息内容", "error_message": "错误信息", "result_json": "结果JSON",
    "config_json": "配置JSON", "snapshot_json": "快照JSON", "payload_json": "完整数据JSON",
    "report_json": "报告JSON", "evaluation_json": "评估结果JSON", "rule_results_json": "风控规则结果JSON",
    "input_fingerprint": "输入数据指纹", "data_as_of": "数据截止日期", "run_id": "运行编号",
    "diagnosis_id": "诊断编号", "user_id": "用户编号", "name": "名称", "action": "交易动作",
    "reason": "原因说明", "note": "备注", "sort_order": "排序序号", "title": "标题",
    "agent_type": "智能体类型", "module": "量化模块", "stage": "执行阶段", "level": "日志级别",
    "current_stage": "当前阶段", "error_text": "错误信息", "instrument": "标的代码",
    "prediction": "预测值", "stock_rank": "股票排名", "model_name": "模型名称",
    "prompt_version": "提示词版本", "algorithm_version": "算法版本", "split_version": "时间切分版本",
    "rule_version": "规则版本", "report_version": "报告版本", "source_type": "来源类型",
    "source_id": "来源编号", "source": "数据来源", "publish_date": "发布日期", "page_no": "页码",
    "chunk_id": "文本分块编号", "quote_text": "引用文本", "retrieval_method": "检索方式",
    "relevance_score": "相关性得分", "lookahead_check": "未来函数检查结果", "content_markdown": "Markdown报告内容",
    "content_html": "HTML报告内容", "validation_json": "校验结果JSON", "event_id": "事件编号",
    "event_type": "事件类型", "impact_direction": "影响方向", "impact_strength": "影响强度",
    "impact_horizon": "影响周期", "event_time": "事件发生时间", "publish_time": "发布时间",
    "summary": "摘要", "key_variables": "关键变量JSON", "transmission_path": "传导路径JSON",
    "confidence": "置信度", "invalid_conditions": "失效条件JSON", "evidence_ids": "证据编号JSON",
    "channel": "通知渠道", "recipient": "通知接收方", "trigger_name": "触发器名称",
    "idempotency_key": "幂等键", "attempts": "尝试次数", "last_error": "最近一次错误",
    "watchlist_id": "自选股列表编号", "signal_id": "信号编号", "signal_date": "信号日期",
    "signal_type": "信号类型", "signal_level": "信号级别", "strategy_name": "策略名称",
    "engine": "信号引擎", "chan_type": "缠论类型", "signal_price": "信号价格",
    "confirmed_date": "确认日期", "pivot_date": "枢纽日期", "signal_status": "信号状态",
    "lookahead_risk": "是否存在未来函数风险", "portfolio_id": "投资组合编号", "alert_key": "告警唯一键",
    "alert_type": "告警类型", "severity": "告警严重程度", "value_json": "告警数值JSON",
    "acknowledged_at": "确认时间", "decision_key": "决策唯一键", "decision": "决策结果",
    "risk_level": "风险等级", "suggested_max_weight": "建议最大仓位权重", "risk_decision": "风控决策",
    "total_assets": "总资产", "cash": "现金余额", "holdings_value": "持仓市值",
    "total_weight": "总仓位权重", "daily_pnl": "当日盈亏", "daily_pnl_ratio": "当日盈亏比例",
    "drawdown": "回撤比例", "snapshot_at": "快照时间", "target_json": "任务目标JSON",
    "cron_expr": "定时任务表达式", "timezone": "时区", "agent_types": "智能体类型JSON",
    "retry_limit": "重试次数上限", "trigger_status": "触发状态", "risk_snapshot_json": "风控快照JSON",
    "event_fingerprint": "事件指纹", "news_fingerprint": "新闻指纹", "extraction_method": "提取方式",
    "extraction_status": "提取状态", "analysis_id": "分析编号", "source_news_id": "来源新闻编号",
    "analyzed_at": "分析时间", "cost": "交易成本", "slippage": "滑点",
}

FIELD_COMMENTS = {
    "fear_index_history": {
        "id": "自增主键", "vix": "VIX恐慌指数", "ovx": "OVX原油波动率指数",
        "gvz": "GVZ黄金波动率指数", "us10y": "美国10年期国债收益率",
        "composite_score": "综合恐慌评分", "risk_level": "风险等级",
        "suggestion": "风险建议", "recorded_at": "记录时间",
    },
    "market_events": {
        "id": "自增主键", "stock_code": "股票代码", "event_type": "事件类型",
        "event_subtype": "事件子类型", "event_desc": "事件描述", "signal": "交易信号",
        "news_date": "新闻日期", "created_at": "创建时间",
    },
    "sentiment_aggregate": {
        "id": "自增主键", "stock_code": "股票代码", "fear_greed_index": "恐惧贪婪指数",
        "overall_sentiment": "整体情绪", "positive_count": "正面新闻数量",
        "negative_count": "负面新闻数量", "neutral_count": "中性新闻数量",
        "top_themes": "主要主题", "risk_alerts": "风险提示",
        "opportunity_hints": "机会提示", "summary": "情绪汇总",
        "news_count": "新闻总数", "analyzed_at": "分析时间",
    },
    "sentiment_detail": {
        "id": "自增主键", "stock_code": "股票代码", "news_title": "新闻标题",
        "news_text": "新闻正文", "sentiment": "情绪类型", "strength": "情绪强度",
        "entities": "识别实体", "keywords": "关键词", "summary": "新闻摘要",
        "market_impact": "市场影响", "news_source": "新闻来源", "news_date": "新闻日期",
        "analyzed_at": "分析时间",
    },
}

def qi(value):
    return "`" + value.replace("`", "``") + "`"

def literal(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"

def column_definition(row):
    _, _, column_type, nullable, default, extra = row
    result = column_type + (" NOT NULL" if nullable == "NO" else " NULL")
    if default is not None:
        if str(default).startswith("CURRENT_TIMESTAMP"):
            result += " DEFAULT " + str(default)
        else:
            result += " DEFAULT " + literal(default)
    if "auto_increment" in (extra or ""):
        result += " AUTO_INCREMENT"
    if "on update" in (extra or ""):
        result += " ON UPDATE CURRENT_TIMESTAMP"
    return result

conn = pymysql.connect(**DB)
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() "
            "AND (COLUMN_COMMENT='' OR COLUMN_COMMENT IS NULL) ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
        rows = cur.fetchall()
        statements = []
        for row in rows:
            table, column = row[0], row[1]
            comment = FIELD_COMMENTS.get(table, {}).get(column, COMMON_FIELD_COMMENTS.get(column, "字段：" + column))
            statements.append(
                "ALTER TABLE " + qi(table) + " MODIFY COLUMN " + qi(column) + " "
                + column_definition(row) + " COMMENT " + literal(comment)
            )
        for table, comment in TABLE_COMMENTS.items():
            statements.append("ALTER TABLE " + qi(table) + " COMMENT " + literal(comment))
        for statement in statements:
            cur.execute(statement)
        conn.commit()
        with open("app/sql/schema.sql", "a", encoding="utf-8") as schema:
            schema.write("\n-- 历史表及缺失字段中文注释迁移\n")
            schema.write("\n".join(statement + ";" for statement in statements))
            schema.write("\n")
        print("executed", len(statements), "statements")
finally:
    conn.close()
