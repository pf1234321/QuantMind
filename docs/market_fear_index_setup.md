# 市场恐慌指数配置说明

## 问题现象

舆情分析师模块中 VIX、OVX、GVZ、美债10Y 等指标显示为空。

## 根本原因

Yahoo Finance 从 2021年11月起封禁了中国大陆的访问，返回 429 错误。

---

## 解决方案

### 方案 1：使用代理（推荐）

在 `.env` 文件中配置 HTTP/HTTPS 代理：

```bash
# 添加到 .env 文件
HTTP_PROXY=http://your-proxy-server:port
HTTPS_PROXY=http://your-proxy-server:port

# 如果代理需要认证
HTTP_PROXY=http://username:password@your-proxy-server:port
HTTPS_PROXY=http://username:password@your-proxy-server:port
```

重启服务后生效。

---

### 方案 2：使用国内数据源（备选）

如果无法使用代理，可以改用国内可访问的数据源。

#### 2.1 使用 Tushare（需要注册获取 token）

```python
# 安装 tushare
pip install tushare

# 在 .env 中配置
TUSHARE_TOKEN=your_tushare_token
```

#### 2.2 使用东方财富 API

东方财富有公开的恐慌指数接口，无需认证。

---

### 方案 3：定时爬取并缓存

如果有海外服务器，可以在海外定时抓取数据，存入数据库供国内服务使用。

---

## 测试验证

运行以下命令测试数据获取：

```bash
# 测试 sentiment_sync 模块
python3 -c "
from app.services.sentiment_sync import _fetch_vix_ovx
vix, ovx, gvz, us10y = _fetch_vix_ovx()
print(f'VIX: {vix}, OVX: {ovx}, GVZ: {gvz}, US10Y: {us10y}')
"

# 测试独立脚本（使用 yfinance）
python3 skills/sentiment-analysis/scripts/market_fear_index.py
```

如果成功，应该能看到具体的数值而不是 None。

---

## 手动同步数据

临时解决方案：手动插入测试数据

```sql
INSERT INTO fear_index_history 
  (vix, ovx, gvz, us10y, composite_score, risk_level, suggestion) 
VALUES 
  (15.2, 28.5, 16.8, 4.45, 48, '中性', '情绪中性，按常规策略执行');
```

---

## 相关文件

- `app/services/sentiment_sync.py:398` - 数据获取函数
- `skills/sentiment-analysis/scripts/market_fear_index.py` - 独立脚本
- `app/api/sentiment.py` - API 接口
- `app/services/sentiment_research_report.py` - 报告生成

---

## 常见问题

**Q: 为什么不用 akshare？**  
A: akshare 的 VIX/OVX/GVZ 接口已废弃或不稳定，经常返回空数据。

**Q: yfinance 需要翻墙吗？**  
A: 是的，Yahoo Finance 已封禁中国大陆访问，必须使用代理或备选方案。

**Q: 能否完全去掉这些指标？**  
A: 可以，但会影响综合风险评分的准确性。建议至少保留 VIX 指标。
