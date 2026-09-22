# 技术分析功能使用指南

## 功能概览

QuantMind 技术分析模块提供以下核心功能：

1. **多周期技术指标计算**：支持日线、周线、月线
2. **技术形态识别**：头肩顶、双底、三角形等经典形态
3. **策略回测验证**：7种技术指标策略历史回测
4. **LLM 智能分析**：基于技术数据生成专业分析报告

---

## 快速开始

### 1. 初始化数据库表

```bash
# 执行建表脚本
mysql -u root -p wucai_trade < app/sql/technical_indicators.sql
```

### 2. 计算技术指标

```bash
# 方式1: API 触发
curl -X POST "http://localhost:8000/api/v1/technical/sync/indicators?codes=600519&period=daily"

# 方式2: Python 调用
python tests/test_technical_analysis.py
```

### 3. 查询技术指标

```bash
# 查询最新指标
curl "http://localhost:8000/api/v1/technical/indicators/latest?code=600519"

# 查询历史指标
curl "http://localhost:8000/api/v1/technical/indicators?code=600519&limit=30"
```

---

## 核心功能详解

### 一、技术指标计算

#### 支持的指标

**趋势指标**
- MA5, MA20, MA60：移动平均线

**动量指标**
- RSI14：相对强弱指数
- MACD DIF, DEA, BAR：平滑异同移动平均线

**摆动指标**
- KDJ K, D, J：随机指标

**波动率**
- ATR14：平均真实波幅

**成交量**
- volume_ratio：量比

#### 多周期支持

```bash
# 日线指标
POST /api/v1/technical/sync/indicators?period=daily&codes=600519

# 周线指标
POST /api/v1/technical/sync/indicators?period=weekly&codes=600519

# 月线指标
POST /api/v1/technical/sync/indicators?period=monthly&codes=600519
```

#### Python 示例

```python
from app.services.technical_indicators import sync_technical_indicators

# 计算日线指标
result = sync_technical_indicators(
    stock_codes=["600519", "000001"],
    period="daily",
    force_refresh=False
)

print(f"写入 {result['written']} 条记录")
```

---

### 二、技术形态识别

#### 支持的形态

| 形态类型 | 英文名称 | 方向 | 说明 |
|---------|---------|------|------|
| 头肩顶 | head_shoulders_top | 看跌 | 三个波峰，中间最高 |
| 双底 | double_bottom | 看涨 | W底形态 |
| 双顶 | double_top | 看跌 | M顶形态 |
| 上升三角形 | ascending_triangle | 看涨 | 上边水平，下边上倾 |
| 下降三角形 | descending_triangle | 看跌 | 下边水平，上边下倾 |

#### 识别形态

```bash
# API 触发
POST /api/v1/technical/sync/patterns?codes=600519,000001

# 查询已识别的形态
GET /api/v1/technical/patterns?code=600519&pattern_status=confirmed
```

#### Python 示例

```python
from app.services.technical_patterns import sync_pattern_detection, get_confirmed_patterns

# 识别形态
result = sync_pattern_detection(
    stock_codes=["600519"],
    lookback_days=120
)

# 查询确认的形态
patterns = get_confirmed_patterns(stock_code="600519")

for p in patterns:
    print(f"{p['pattern_type']}: 目标价 {p['target_price']}, 止损 {p['stop_loss']}")
```

#### 形态示例

**双底（W底）形态**
```
价格
 ^
 |     峰
 |    / \
 |   /   \    颈线突破 ← 确认信号
 |  /     \  /
 | /  底1  \/  底2
 |/
 +-------------------> 时间

目标价 = 颈线价格 + (颈线价格 - 底部价格)
```

---

### 三、策略回测

#### 支持的策略类型

| 策略类型 | 说明 | 入场信号 | 出场信号 |
|---------|------|---------|---------|
| ma_cross | 均线交叉 | MA5上穿MA20 | MA5下穿MA20 或止损止盈 |
| macd | MACD金叉死叉 | DIF上穿DEA | DIF下穿DEA 或止损止盈 |
| rsi | RSI超买超卖 | RSI < 30 | RSI > 70 或止损止盈 |
| kdj | KDJ超买超卖 | J < 20 | J > 80 或止损止盈 |
| boll | 布林带突破 | 价格突破下轨 | 价格突破上轨 或止损止盈 |
| ma_macd_combined | 均线+MACD组合 | 多头排列+MACD金叉 | 均线死叉或MACD死叉 |
| triple_combined | 三重组合 | MA金叉+MACD金叉+RSI不超买 | 任一指标卖出信号 |

#### 批量回测

```bash
# 测试多个策略
POST /api/v1/technical/backtest/batch?codes=600519,000001&strategies=ma_cross,macd,triple_combined&start_date=2022-01-01&end_date=2024-12-31

# 返回示例
{
  "total_tested": 6,
  "top_strategies": [
    {
      "stock_code": "600519",
      "strategy_type": "ma_macd_combined",
      "annualized_return": 0.28,
      "sharpe_ratio": 1.85,
      "max_drawdown": -0.15,
      "win_rate": 0.62,
      "trade_count": 15
    }
  ],
  "summary": {
    "best_strategy": "ma_macd_combined",
    "best_stock": "600519",
    "best_return": 0.28
  }
}
```

#### 查询最佳策略

```bash
# 查询历史表现最好的策略
GET /api/v1/technical/backtest/best?min_sharpe=1.5&min_trades=10

# 对比单只股票的策略
GET /api/v1/technical/backtest/compare?code=600519
```

#### Python 示例

```python
from app.services.technical_backtest import batch_backtest_strategies, compare_strategies_for_stock

# 批量回测
results = batch_backtest_strategies(
    stock_codes=["600519"],
    strategy_types=["ma_cross", "macd", "rsi", "ma_macd_combined"],
    start_date="2022-01-01",
    end_date="2024-12-31"
)

# 按年化收益排序
sorted_results = sorted(results, key=lambda x: x['metrics']['annualized_return'], reverse=True)

for r in sorted_results:
    print(f"{r['strategy_type']}: 年化 {r['metrics']['annualized_return']:.2%}, "
          f"夏普 {r['metrics']['sharpe_ratio']:.2f}")

# 策略对比
comparison = compare_strategies_for_stock("600519")
print(f"最佳策略: {comparison['best_strategy']}, 收益: {comparison['best_return']:.2%}")
```

---

### 四、LLM 技术分析报告

#### 生成报告

```bash
# API 生成报告
POST /api/v1/technical/report/generate?code=600519&llm_model=gpt-3.5-turbo

# 查询最新报告
GET /api/v1/technical/report/latest?code=600519

# 批量生成（多只股票）
POST /api/v1/technical/report/batch?codes=600519,000001,000002
```

#### 报告内容结构

```json
{
  "report_id": "abc123",
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "report_date": "2024-12-20",
  "technical_score": 75,
  "trend_direction": "bullish",
  "signal_strength": "medium",
  "sections": {
    "trend_analysis": "当前处于上升趋势，MA5 > MA20 > MA60 多头排列...",
    "pattern_analysis": "识别到上升三角形形态，突破阻力位后目标价...",
    "indicator_analysis": "RSI为65，处于强势区间但未超买；MACD金叉...",
    "volume_analysis": "量比1.2，成交量温和放大，价量配合良好...",
    "support_resistance": "支撑位: 1800元（MA60），阻力位: 1950元（前高）...",
    "trading_suggestion": "建议：逢低买入，仓位30%，止损1780，目标2000...",
    "risk_warning": "风险：若跌破MA60需观察是否趋势转变..."
  },
  "full_report": "完整文本报告..."
}
```

#### Python 示例

```python
from app.services.technical_reports import generate_technical_report, batch_generate_reports

# 生成单只股票报告
report = generate_technical_report(
    stock_code="600519",
    stock_name="贵州茅台",
    period="daily",
    llm_model="gpt-4"
)

print(f"技术评分: {report['technical_score']}/100")
print(f"趋势方向: {report['trend_direction']}")
print(f"\n{report['full_report']}")

# 批量生成
result = batch_generate_reports(
    stock_codes=["600519", "000001", "000002"],
    period="daily",
    llm_model="gpt-3.5-turbo"
)

print(f"成功: {result['success']}/{result['total']}")
```

---

## 定时任务

技术分析模块已集成到定时调度器，每日自动执行。

### 调度时间

| 任务 | 时间 | 说明 |
|-----|------|------|
| K线同步 | 16:30 | 收盘后同步日线数据 |
| 技术指标计算 | 18:15 | K线同步后计算指标 |
| 技术形态识别 | 18:45 | 指标计算后识别形态 |

### 配置方式

在 `app/scheduler.py` 中：

```python
TASKS = {
    "technical_indicators": {
        "description": "技术指标计算（交易日 18:15）",
        "func": lambda **kw: _technical_indicators_task(**kw),
        "cron": "15 18 * * 1-5",
        "enabled": True,  # 修改为 False 可关闭
    }
}
```

---

## 使用场景示例

### 场景1：选股 - 找出技术面最好的股票

```python
# 1. 批量计算技术指标
sync_technical_indicators(stock_codes=None)  # 全量

# 2. 查询技术评分最高的股票
top_stocks = execute_query("""
    SELECT stock_code, technical_score, trend_direction
    FROM trade_technical_reports
    WHERE technical_score >= 80
    ORDER BY technical_score DESC
    LIMIT 20
""")
```

### 场景2：验证策略 - 找出最适合的技术指标

```python
# 1. 对目标股票回测所有策略
results = batch_backtest_strategies(
    stock_codes=["600519"],
    strategy_types=["ma_cross", "macd", "rsi", "kdj", "ma_macd_combined", "triple_combined"],
    start_date="2020-01-01",
    end_date="2024-12-31"
)

# 2. 找出表现最好的策略
best = max(results, key=lambda x: x['metrics']['annualized_return'])
print(f"最佳策略: {best['strategy_type']}, 年化: {best['metrics']['annualized_return']:.2%}")

# 3. 使用该策略实盘
# ...
```

### 场景3：形态交易 - 捕捉双底突破

```python
# 1. 识别双底形态
sync_pattern_detection(lookback_days=120)

# 2. 查询已确认的双底
double_bottoms = execute_query("""
    SELECT stock_code, target_price, stop_loss, confidence
    FROM trade_technical_patterns
    WHERE pattern_type='double_bottom' AND pattern_status='confirmed'
    ORDER BY confidence DESC
""")

# 3. 按目标价和置信度筛选
for p in double_bottoms:
    if p['confidence'] >= 0.8:
        print(f"{p['stock_code']}: 目标价 {p['target_price']}, 止损 {p['stop_loss']}")
```

### 场景4：多周期分析 - 日线+周线双重确认

```python
# 1. 计算日线和周线指标
sync_technical_indicators(stock_codes=["600519"], period="daily")
sync_technical_indicators(stock_codes=["600519"], period="weekly")

# 2. 查询日线和周线趋势
daily = execute_query("SELECT ma5, ma20, ma60 FROM trade_technical_summary WHERE stock_code='600519' AND period='daily' ORDER BY trade_date DESC LIMIT 1")[0]
weekly = execute_query("SELECT ma5, ma20, ma60 FROM trade_technical_summary WHERE stock_code='600519' AND period='weekly' ORDER BY trade_date DESC LIMIT 1")[0]

# 3. 判断多周期共振
if daily['ma5'] > daily['ma20'] > daily['ma60'] and weekly['ma5'] > weekly['ma20']:
    print("日线周线共振，多头趋势强劲")
```

---

## 性能优化建议

### 1. 按需计算，避免全量

```python
# ❌ 不推荐：一次性计算所有股票
sync_technical_indicators(stock_codes=None)

# ✅ 推荐：只计算关注的股票
sync_technical_indicators(stock_codes=["600519", "000001"])
```

### 2. 利用增量更新

```python
# 自动增量：只计算最新数据
sync_technical_indicators(force_refresh=False)
```

### 3. 回测使用合理的日期范围

```python
# ❌ 时间太长，计算慢
batch_backtest_strategies(start_date="2010-01-01", end_date="2024-12-31")

# ✅ 2-3年足够
batch_backtest_strategies(start_date="2022-01-01", end_date="2024-12-31")
```

---

## 常见问题

### Q1: 技术指标数据为空？

**A:** 需要先同步K线数据，然后计算指标。

```bash
# 1. 同步K线
POST /api/v1/sync/kline?codes=600519

# 2. 计算指标
POST /api/v1/technical/sync/indicators?codes=600519
```

### Q2: LLM 报告生成失败？

**A:** 需要配置 OpenAI API Key。

```bash
# .env 文件中添加
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选
```

### Q3: 回测结果不理想？

**A:** 这很正常。技术指标策略的历史表现差异很大：

- 某些股票适合某种策略，某些不适合
- 回测是为了**验证**指标价值，不是所有指标都有效
- 建议测试多只股票，找出普遍有效的策略

### Q4: 如何提高形态识别准确率？

**A:** 形态识别是启发式算法，建议：

- 结合多个形态共同判断
- 关注 `confidence` 字段，只采用高置信度的形态
- 形态确认后再交易，不要在 `forming` 阶段就入场

---

## API 接口速查

### 技术指标

- `POST /api/v1/technical/sync/indicators` - 计算指标
- `GET /api/v1/technical/indicators` - 查询指标历史
- `GET /api/v1/technical/indicators/latest` - 查询最新指标

### 技术形态

- `POST /api/v1/technical/sync/patterns` - 识别形态
- `GET /api/v1/technical/patterns` - 查询形态

### 策略回测

- `POST /api/v1/technical/backtest/batch` - 批量回测
- `GET /api/v1/technical/backtest/best` - 最佳策略
- `GET /api/v1/technical/backtest/compare` - 策略对比

### LLM 报告

- `POST /api/v1/technical/report/generate` - 生成报告
- `GET /api/v1/technical/report/latest` - 查询报告
- `POST /api/v1/technical/report/batch` - 批量生成

---

## 下一步优化方向

1. **实时指标计算**：WebSocket 推送实时技术指标
2. **更多形态**：圆弧顶底、旗形、楔形等
3. **AI选股**：基于LLM的技术面选股引擎
4. **策略组合**：多策略加权、动态切换
5. **可视化**：K线图 + 指标叠加展示

---

完整文档见项目 `/docs` 目录。
