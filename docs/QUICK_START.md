# QuantMind 技术分析功能 - 快速启动指南

## 🚀 快速启动（5分钟上手）

### 第一步：初始化数据库

```bash
# 在项目根目录执行
mysql -u root -p wucai_trade < app/sql/technical_indicators.sql
```

### 第二步：启动后端服务

```bash
# 确保后端服务运行
python run.py
```

访问 http://localhost:8000/docs 确认服务正常。

### 第三步：启动前端

```bash
cd frontend
npm install  # 首次运行需要安装依赖
npm run dev
```

访问 http://localhost:5173

### 第四步：使用技术分析功能

1. 点击左侧菜单 **"技术分析师"**
2. 输入股票代码（如：600519）
3. 点击 **"计算指标"** 按钮
4. 查看技术指标图表

---

## 📋 完整功能测试清单

### ✅ 测试技术指标计算

```bash
# 1. 同步K线数据（如果还没有）
curl -X POST "http://localhost:8000/api/v1/sync/kline?codes=600519"

# 2. 计算技术指标
curl -X POST "http://localhost:8000/api/v1/technical/sync/indicators?codes=600519&period=daily"

# 3. 查询指标数据
curl "http://localhost:8000/api/v1/technical/indicators?code=600519&limit=10"
```

**前端测试**：
- 输入 `600519`
- 点击"计算指标"
- 查看最新指标卡片和图表

---

### ✅ 测试技术形态识别

```bash
# 识别形态
curl -X POST "http://localhost:8000/api/v1/technical/sync/patterns?codes=600519"

# 查询形态
curl "http://localhost:8000/api/v1/technical/patterns?code=600519"
```

**前端测试**：
- 点击"识别形态"
- 查看"技术形态"Tab
- 查看识别到的形态列表

---

### ✅ 测试策略回测

```bash
# 批量回测
curl -X POST "http://localhost:8000/api/v1/technical/backtest/batch?codes=600519&strategies=ma_cross,macd,rsi&start_date=2022-01-01&end_date=2024-12-31"
```

**前端测试**：
- 点击"策略回测"
- 等待回测完成（约10-30秒）
- 查看回测结果弹窗
- 切换到"策略回测"Tab 查看详情

---

### ✅ 测试LLM报告（需要API Key）

```bash
# 配置环境变量
export OPENAI_API_KEY=sk-xxx

# 生成报告
curl -X POST "http://localhost:8000/api/v1/technical/report/generate?code=600519"
```

**前端测试**：
- 点击"生成报告"
- 等待报告生成（约10-20秒）
- 查看完整的技术分析报告

---

## 🎯 页面功能导览

### 顶部工具栏

```
┌────────────────────────────────────────────────────────────────────┐
│ [搜索: 600519▼] [周期: 日线▼]  [计算指标] [识别形态] [策略回测] [生成报告] │
└────────────────────────────────────────────────────────────────────┘
```

### Tab 切换

- **技术指标**：查看指标数值和图表
- **技术形态**：查看形态识别结果
- **策略回测**：查看策略历史表现

---

## 📊 数据说明

### 最新指标卡片

| 指标 | 含义 | 参考值 |
|------|------|--------|
| MA5/MA20/MA60 | 移动平均线 | 多头排列看涨 |
| RSI14 | 相对强弱 | <30超卖，>70超买 |
| MACD | 趋势动量 | 金叉看涨，死叉看跌 |
| KDJ-J | 随机指标 | <20超卖，>80超买 |
| ATR14 | 波动率 | 数值越大波动越大 |
| 量比 | 成交量对比 | >1表示放量 |

### 图表说明

**均线走势图**
- 蓝线：MA5（短期）
- 绿线：MA20（中期）
- 黄线：MA60（长期）

**MACD图**
- DIF上穿DEA = 金叉（买入）
- DIF下穿DEA = 死叉（卖出）

**RSI & KDJ图**
- 虚线标注超买超卖区域
- 注意背离信号

---

## 🔧 常见问题快速解决

### Q1: 前端启动报错

```bash
# 删除依赖重新安装
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Q2: 计算指标返回404

```bash
# 先同步K线数据
curl -X POST "http://localhost:8000/api/v1/sync/kline?codes=600519"

# 再计算指标
curl -X POST "http://localhost:8000/api/v1/technical/sync/indicators?codes=600519"
```

### Q3: 生成报告失败

```bash
# 检查环境变量
echo $OPENAI_API_KEY

# 或在 .env 文件中添加
OPENAI_API_KEY=sk-xxx
```

### Q4: 图表不显示

- 刷新页面（Ctrl+R）
- 检查浏览器控制台是否有错误
- 确保数据已加载成功

---

## 📈 使用示例

### 示例1：快速看盘

```bash
# 1. 输入股票代码
600519

# 2. 点击"计算指标"
等待3-5秒

# 3. 查看指标卡片
- RSI: 65（正常区域）
- MACD: 金叉（看涨信号）
- MA: 多头排列（上升趋势）

# 4. 结论
技术面偏多，可以关注
```

### 示例2：形态交易

```bash
# 1. 点击"识别形态"

# 2. 查看形态Tab
发现：双底形态，已确认，置信度82%

# 3. 查看目标价和止损
- 目标价：95.5
- 止损位：85.0

# 4. 制定交易计划
在85-87区间买入，止损85，目标95
```

### 示例3：策略选择

```bash
# 1. 点击"策略回测"

# 2. 查看回测结果
- 均线+MACD组合：年化28%，夏普1.85
- RSI超买超卖：年化15%，夏普1.2

# 3. 选择策略
选择"均线+MACD组合"策略实盘

# 4. 执行
按照该策略的信号进行交易
```

---

## 🎓 学习路径

### 新手（0-1周）
1. 熟悉技术指标的含义
2. 学会看图表
3. 理解超买超卖概念

### 进阶（1-2周）
1. 学习技术形态
2. 理解多周期分析
3. 尝试策略回测

### 高级（2周+）
1. 组合多个指标
2. 多周期共振
3. 策略优化

---

## 📚 相关文档

- **完整功能文档**: `docs/TECHNICAL_ANALYSIS.md`
- **前端使用指南**: `docs/TECHNICAL_ANALYSIS_FRONTEND.md`
- **API 接口文档**: http://localhost:8000/docs
- **系统总结**: `docs/TECHNICAL_ANALYSIS_SUMMARY.md`

---

## 💡 最佳实践

### ✅ DO（推荐）

- 先计算指标再查看图表
- 多周期验证（日线+周线）
- 结合成交量分析
- 参考回测数据选择策略
- 设置止损位

### ❌ DON'T（不推荐）

- 只看单一指标
- 忽略成交量
- 不设止损
- 盲目追高
- 逆势操作

---

## 🎉 开始使用

现在你已经准备好了！

1. 打开浏览器：http://localhost:5173
2. 点击"技术分析师"
3. 输入股票代码开始分析

祝你投资顺利！🚀

---

**有问题？**
- 查看文档：`docs/` 目录
- 查看日志：后端控制台 / 浏览器F12
- 运行测试：`python tests/test_technical_analysis.py`
