# 市场恐慌指数为空问题修复报告

## 问题现象

舆情分析师模块中，以下市场指标均显示为空（NULL）：
- VIX（标普500波动率指数）
- OVX（原油波动率指数）
- GVZ（黄金波动率指数）
- 美债10Y（美国10年期国债收益率）

## 根本原因分析

### 原因 1：akshare 接口已废弃

`app/services/sentiment_sync.py` 中的 `_fetch_vix_ovx()` 函数使用了 **已废弃的 akshare 接口**：

```python
# ❌ 这些接口已经失效
df_vix = ak.index_vix_cboe()
df_ovx = ak.index_ovx()
df_gvz = ak.index_gvz()
```

### 原因 2：Yahoo Finance 封禁中国大陆

项目中 `skills/sentiment-analysis/scripts/market_fear_index.py` 已经改用 `yfinance`，但遇到：

- **Yahoo Finance 从 2021年11月起封禁中国大陆访问**
- 返回 HTTP 429（Too Many Requests）
- 返回提示页面："Yahoo's suite of services will no longer be accessible from mainland China"

---

## 修复方案

### 已完成的修改

#### 1. 更新数据获取接口

**文件：** `app/services/sentiment_sync.py`

将 `_fetch_vix_ovx()` 从废弃的 akshare 接口改为 yfinance + 代理支持：

```python
def _fetch_vix_ovx():
    """从 yfinance 获取 VIX/OVX/GVZ/美债10Y
    
    支持通过环境变量配置代理：HTTP_PROXY 或 HTTPS_PROXY
    """
    # 读取代理配置
    proxies = {}
    if os.getenv("HTTP_PROXY"):
        proxies["http"] = os.getenv("HTTP_PROXY")
    if os.getenv("HTTPS_PROXY"):
        proxies["https"] = os.getenv("HTTPS_PROXY")
    
    # 使用代理访问 yfinance
    session = requests.Session()
    session.proxies.update(proxies)
    
    vix_ticker = yf.Ticker("^VIX", session=session)
    # ... 获取各项指标
```

#### 2. 创建降级方案

**文件：** `app/services/sentiment_sync_fallback.py`（新建）

当 Yahoo Finance 不可用时的降级策略：

```python
def fetch_vix_ovx_with_fallback():
    """多级降级方案
    
    1. yfinance + 代理（最准确）
    2. 国内数据源拼凑：
       - VIX: 东方财富全球指数
       - US10Y: 新浪财经接口
       - VIX估算: 基于上证指数波动率
    3. 纯情绪聚合计算（无外部指标）
    """
```

#### 3. 集成降级逻辑

**文件：** `app/services/sentiment_sync.py`

在 `sync_fear_index()` 中集成降级方案：

```python
def sync_fear_index(days=3):
    # 主数据源
    vix, ovx, gvz, us10y = _fetch_vix_ovx()
    
    # 降级数据源
    if vix is None and ovx is None:
        vix, ovx, gvz, us10y = fetch_vix_ovx_with_fallback()
    
    # 计算综合指数...
```

---

## 使用方法

### 方法 1：配置代理（推荐）

如果你有可用的代理服务器，在 `.env` 文件中添加：

```bash
# HTTP/HTTPS 代理
HTTP_PROXY=http://proxy-server:port
HTTPS_PROXY=http://proxy-server:port

# 如果需要认证
HTTP_PROXY=http://username:password@proxy-server:port
HTTPS_PROXY=http://username:password@proxy-server:port
```

重启服务后，系统会自动通过代理访问 Yahoo Finance。

### 方法 2：使用降级方案（无需代理）

降级方案会自动启用，优先级：

1. **新浪财经** - 获取美债10Y收益率
2. **东方财富** - 获取 VIX 指数（可能不稳定）
3. **A股估算** - 基于上证指数波动率估算 VIX
4. **纯情绪聚合** - 完全基于个股情绪计算综合指数

### 方法 3：手动填充数据（临时）

如果需要立即查看效果，可以手动插入测试数据：

```sql
INSERT INTO fear_index_history 
  (vix, ovx, gvz, us10y, composite_score, risk_level, suggestion) 
VALUES 
  (15.2, 28.5, 16.8, 4.45, 48, '中性', '情绪中性，按常规策略执行');
```

---

## 验证测试

### 测试 1：测试数据获取

```bash
python3 -c "
from app.services.sentiment_sync import sync_fear_index
result = sync_fear_index(days=3)
print(result)
"
```

**预期结果：**
- 如果配置了代理：`vix`, `ovx`, `gvz`, `us10y` 有数值
- 如果使用降级：部分字段有数值（如 `us10y`）
- 最坏情况：`composite_score` 基于情绪聚合计算（50左右）

### 测试 2：查看数据库

```bash
python3 -c "
from app.database import execute_query
rows = execute_query('SELECT * FROM fear_index_history ORDER BY recorded_at DESC LIMIT 3')
for r in rows:
    print(f'VIX: {r[\"vix\"]}, US10Y: {r[\"us10y\"]}, 综合评分: {r[\"composite_score\"]}')
"
```

### 测试 3：测试独立脚本

```bash
# 测试市场恐慌指数独立脚本（需要代理）
python3 skills/sentiment-analysis/scripts/market_fear_index.py
```

---

## 当前状态

### ✅ 已完成

1. 替换废弃的 akshare 接口为 yfinance
2. 添加代理支持
3. 创建多级降级方案
4. 集成降级逻辑到主同步流程
5. 创建配置文档

### ⚠️ 当前限制

1. **无代理情况下**：VIX/OVX/GVZ 无法获取（Yahoo Finance 封禁）
2. **降级方案**：新浪财经接口可能不稳定
3. **纯情绪聚合**：缺少宏观波动率指标，综合评分准确度降低

### 📋 后续优化建议

1. **申请 Tushare API**（推荐）
   - 注册并获取 token：https://tushare.pro/register
   - 可稳定获取全球市场指标

2. **搭建数据中转服务**
   - 在海外服务器定时抓取数据
   - 通过内部 API 提供给国内服务

3. **完善降级逻辑**
   - 增加更多国内可用数据源
   - 优化 VIX 估算算法

---

## 相关文件

- `app/services/sentiment_sync.py` - 主同步逻辑
- `app/services/sentiment_sync_fallback.py` - 降级方案
- `skills/sentiment-analysis/scripts/market_fear_index.py` - 独立脚本
- `docs/market_fear_index_setup.md` - 配置说明文档
- `app/api/sentiment.py` - API 接口
- `app/services/sentiment_research_report.py` - 报告生成

---

## 技术细节

### 数据表结构

```sql
CREATE TABLE fear_index_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    vix DECIMAL(10,2),           -- VIX 波动率指数
    ovx DECIMAL(10,2),           -- 原油波动率
    gvz DECIMAL(10,2),           -- 黄金波动率
    us10y DECIMAL(10,3),         -- 美债10年收益率
    composite_score INT,          -- 综合评分 0-100
    risk_level VARCHAR(20),       -- 风险等级
    suggestion TEXT,              -- 操作建议
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 综合评分计算逻辑

```python
# VIX 映射到 0-100 分制
vix_fgi = max(0, min(100, int(round(100 - (vix - 12) * 3.5))))

# 综合评分 = VIX权重40% + 情绪聚合60%
if vix_fgi and market_fgi:
    composite = int(round(vix_fgi * 0.4 + market_fgi * 0.6))
```

### API 接口

```
GET /api/sentiment/fear-index
GET /api/sentiment/fear-index/history?days=30
```

---

## 常见问题

**Q: 为什么不继续用 akshare？**  
A: akshare 的 `index_vix_cboe()` / `index_ovx()` / `index_gvz()` 接口已经废弃，返回空数据或报错。

**Q: 必须配置代理吗？**  
A: 不是必须。降级方案会尝试从国内数据源获取，但准确性和覆盖度会降低。

**Q: 没有 VIX 数据会影响什么？**  
A: 综合评分会完全基于个股情绪聚合，缺少宏观市场波动率视角，可能在极端行情下反应滞后。

**Q: 如何确认代理配置生效？**  
A: 日志中会输出 `[恐慌指数] 使用代理: {'http': '...', 'https': '...'}`

**Q: 能否完全去掉这些宏观指标？**  
A: 可以，但建议至少保留一个（VIX 或 US10Y），否则系统变为纯舆情分析，缺少宏观风险视角。

---

**修复完成时间：** 2026-09-20  
**影响范围：** 舆情分析模块、市场恐慌指数、综合舆情报告  
**修复状态：** ✅ 已修复（需配置代理或使用降级方案）
