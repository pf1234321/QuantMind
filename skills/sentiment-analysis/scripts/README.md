# sentiment-analysis 脚本说明

本目录包含 5 个舆情分析脚本，覆盖微观（个股新闻 + LLM 情感分析 + 事件驱动）和宏观（VIX 恐慌指数 + 国债收益率 + 预测市场）两个维度。

---

## 脚本总览

```
scripts/
├── news_fetcher.py          # ① 新闻抓取：从东方财富/央视获取新闻
├── sentiment_scorer.py      # ② 情感评分：LLM 分析每条新闻的正负面情绪
├── event_detector.py        # ③ 事件识别：识别资产重组/减持等重大事件并生成交易信号
├── market_fear_index.py     # ④ 恐慌指数：VIX + 国债 + OVX/GVZ 综合评分
└── polymarket_monitor.py    # ⑤ 预测市场：Polymarket 地缘政治概率监控
```

**数据流关系**：

```
news_fetcher.py  →  sentiment_scorer.py  →  输出情绪指数
                 →  event_detector.py    →  输出交易信号

market_fear_index.py    →  综合恐慌/贪婪评分
polymarket_monitor.py   →  聪明钱信号 + 资产配置建议
```

---

## ① news_fetcher.py — 新闻抓取器

**功能**：通过 `akshare` 从东方财富获取个股新闻、上市公司公告和央视新闻，支持关键词过滤与时间范围筛选。

**数据源**：
- 东方财富个股新闻（`ak.stock_news_em`）
- 上市公司公告（`ak.stock_notice_report`）
- 央视新闻（`ak.news_cctv`，可选）

**用法**：

```bash
# 获取比亚迪最近 7 天的新闻
python news_fetcher.py --stock 002594 --days 7

# 搜索包含"资产重组"关键词的新闻
python news_fetcher.py --keywords 资产重组 --days 3

# 获取茅台新闻，只保留含"业绩"或"分红"的
python news_fetcher.py --stock 600519 --keywords 业绩,分红 --days 30

# 同时抓取央视新闻
python news_fetcher.py --keywords 降准,降息 --days 5 --include_cctv
```

**输出**：JSON 文件，默认保存到 `data/` 目录（如 `data/002594_news.json`）。

**依赖**：`akshare`, `pandas`

---

## ② sentiment_scorer.py — LLM 情感分析评分器

**功能**：使用通义千问（DashScope）对每条新闻逐条进行情感分析，最后聚合生成 Fear & Greed Index（0-100），类似 CNN 的恐慌贪婪指数。

**每条新闻输出**：

| 字段 | 说明 |
|------|------|
| `sentiment` | 正面 / 负面 / 中性 |
| `strength` | 1-5，情感强度（1=极弱，5=极强） |
| `entities` | 相关公司或人物列表 |
| `keywords` | 核心关键词（最多 5 个） |
| `summary` | 一句话摘要 |
| `market_impact` | 对市场的可能影响 |

**聚合输出**：

| 字段 | 说明 |
|------|------|
| `overall_sentiment` | 贪婪 / 乐观 / 中性 / 谨慎 / 恐慌 |
| `fear_greed_index` | 0-100（0=极度恐慌，50=中性，100=极度贪婪） |
| `positive_count` / `negative_count` / `neutral_count` | 正/负/中性新闻计数 |
| `top_themes` | 最主要的 3 个主题 |
| `risk_alerts` | 需要关注的风险点 |
| `opportunity_hints` | 可能的交易机会 |

**用法**：

```bash
# 对 news_fetcher 的输出做情感分析
python sentiment_scorer.py --news_file data/002594_news.json --output_dir output/

# 使用更强模型，限制分析 20 条
python sentiment_scorer.py --news_file data/资产重组_news.json --model qwen-plus --max_news 20
```

**输出**：
- `output/{文件名}_sentiment.json` — 逐条详细分析
- `output/{文件名}_mood.json` — 聚合情绪指数

**依赖**：`openai`, `DASHSCOPE_API_KEY`（环境变量）

> **注意**：脚本已内置 `dotenv` 自动加载项目根目录 `.env`，请确保 `.env` 中配置了 `DASHSCOPE_API_KEY=sk-xxx`。

---

## ③ event_detector.py — 事件识别与交易信号生成器

**功能**：从新闻中识别重大金融事件，并根据事件类型自动生成交易信号和操作建议。

**两种检测方式**：

| 方式 | 速度 | 准确度 | 说明 |
|------|------|--------|------|
| 关键词匹配 | 极快 | 中等 | 内置 50+ 关键词库，覆盖利好/利空/政策三大类 |
| LLM 精细检测 | 慢 | 高 | 需 `--use_llm`，适合关键词漏掉的事件 |

**事件分类体系**：

| 类别 | 子类型 | 交易信号示例 |
|------|--------|-------------|
| 利好 | 资产重组、回购增持、业绩预增、股权激励、大额订单、分红送转 | 看多 / 强烈关注 |
| 利空 | 业绩预减、违规处罚、股东减持、商誉减值、退市风险、诉讼仲裁 | 看空 / 回避 / 谨慎 |
| 政策 | 货币政策、产业政策、监管政策 | 关注宏观 / 关注板块 / 谨慎观望 |

**用法**：

```bash
# 仅用关键词快速检测（推荐日常使用）
python event_detector.py --news_file data/002594_news.json --output_dir output/

# 启用 LLM 精细检测（更全面但更慢）
python event_detector.py --news_file data/002594_news.json --output_dir output/ --use_llm
```

**输出**：`output/{文件名}_events.json`，包含事件摘要和逐条事件的交易信号。

**依赖**：`openai`, `DASHSCOPE_API_KEY`（仅 `--use_llm` 时需要）

---

## ④ market_fear_index.py — 市场恐慌指数监控

**功能**：获取全球市场恐慌/贪婪相关指标，计算综合风险评分（0-100），为投资决策提供宏观情绪参考。

**监控指标**：

| 指标 | 数据源 | 说明 |
|------|--------|------|
| VIX | akshare / yfinance | 标普 500 隐含波动率，美股恐慌指数 |
| OVX | yfinance | 原油 ETF 波动率，衡量能源供应风险 |
| GVZ | yfinance | 黄金 ETF 波动率，衡量避险情绪 |
| US 10Y | akshare / yfinance | 美国 10 年期国债收益率，全球资产定价之锚 |
| 上证指数 | akshare | 近 10 日涨跌幅（需 `--include_ashare`） |
| 北向资金 | akshare | 外资净流入/流出方向（需 `--include_ashare`） |

**综合评分规则**：

| 指标 | 区间 → 得分贡献 |
|------|-----------------|
| VIX < 15 | +30（极度平静） |
| VIX 15-20 | +15 |
| VIX 20-25 | 0 |
| VIX 25-35 | -15 |
| VIX > 35 | -30（极度恐慌） |
| US10Y < 3.8% | +10（宽松利好） |
| US10Y > 4.8% | -10（高利率压制） |

**风险传导分析**（基于开源证券研报）：

| 模式 | 解读 | 操作 |
|------|------|------|
| OVX ↑ 但 VIX 滞后 | 风险集中在能源端 | 关注能源板块，无需全面避险 |
| OVX ↑ + VIX ↑ 同步 | 全球性流动性危机 | 立即风控，增配黄金和现金 |

**用法**：

```bash
# 只看美股宏观指标
python market_fear_index.py

# 加上 A 股情绪
python market_fear_index.py --include_ashare --output_dir output/
```

**输出**：`output/fear_index_{YYYYMMDD}.json` + 终端打印综合评分和操作建议。

**依赖**：`akshare`, `yfinance`

---

## ⑤ polymarket_monitor.py — Polymarket 预测市场监控

**功能**：通过 Polymarket Gamma API（免费无需认证）获取地缘政治、宏观经济等预测市场数据，分析聪明钱押注方向，为投资决策提供前瞻性信号。

**Polymarket 简介**：全球最大的去中心化预测市场，用户用 USDC 真金白银押注事件概率，所有交易链上透明可追踪。2026 年获洲际交易所（纽交所母公司）投资 20 亿美元。

**核心功能**：

| 功能 | 说明 |
|------|------|
| 事件搜索 | 按关键词搜索活跃预测市场（如 Iran, tariff, China, Fed） |
| 概率解析 | 提取 Yes/No 价格，换算概率百分比 |
| 聪明钱检测 | 高交易量（>3x 平均）+ 高概率倾斜 + 高流动性 |
| 资产配置建议 | 根据事件概率自动映射到具体操作 |

**资产配置映射示例**：

| 事件 | 高概率 → 操作 | 低概率 → 操作 |
|------|-------------|-------------|
| war | 做多黄金/原油，做空科技股 | 平仓避险，买入风险资产 |
| ceasefire | 平仓原油多头，买入被制裁国资产 | 维持避险配置 |
| tariff | 回避出口型企业，关注内需 | 关注出口复苏机会 |
| recession | 增配国债和黄金，减仓周期股 | 增配成长股和周期股 |

**用法**：

```bash
# 默认关键词（Iran, China, tariff, war, ceasefire）
python polymarket_monitor.py

# 指定关键词
python polymarket_monitor.py --keyword "Iran"

# 多个关键词 + 提高交易量门槛
python polymarket_monitor.py --keywords "tariff,China,Fed" --min_volume 1000000

# 指定输出目录
python polymarket_monitor.py --keyword "recession" --output_dir output/
```

**输出**：`output/polymarket_{YYYYMMDD}.json` + 终端打印 Top 市场、聪明钱信号、资产配置建议。

**依赖**：`httpx`（自动安装）

---

## 典型工作流

### 场景 1：个股舆情监控

```bash
# 1. 抓新闻
python news_fetcher.py --stock 002594 --days 7

# 2. 情感分析
python sentiment_scorer.py --news_file data/002594_news.json

# 3. 事件检测（如需深度检测加 --use_llm）
python event_detector.py --news_file data/002594_news.json
```

### 场景 2：主题事件扫描

```bash
# 1. 搜索资产重组新闻
python news_fetcher.py --keywords 资产重组 --days 3

# 2. 识别事件并生成信号
python event_detector.py --news_file data/资产重组_news.json --use_llm
```

### 场景 3：宏观风险评估

```bash
# 恐慌指数 + A 股情绪
python market_fear_index.py --include_ashare

# Polymarket 地缘政治监控
python polymarket_monitor.py --keywords "war,ceasefire,tariff"
```

---

## 环境要求

| 依赖 | 用途 | 安装 |
|------|------|------|
| `akshare` | 新闻抓取、VIX、国债、A股数据 | `pip install akshare` |
| `pandas` | 数据处理 | 随 akshare 安装 |
| `openai` | 调用通义千问 API | `pip install openai` |
| `yfinance` | VIX/OVX/GVZ 备选数据源 | `pip install yfinance` |
| `httpx` | Polymarket API 请求 | 脚本自动安装 |
| `python-dotenv` | 加载 .env 环境变量 | `pip install python-dotenv` |

**API Key**：在项目根目录 `.env` 中配置：

```
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

获取地址：[https://dashscope.console.aliyun.com/apiKey](https://dashscope.console.aliyun.com/apiKey)
