# QuantMind 量化交易系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Secret Scan](https://img.shields.io/github/actions/workflow/status/pf1234321/QuantMind/secret-scan.yml?label=secret-scan)](.github/workflows/secret-scan.yml)
[![Python CI](https://img.shields.io/github/actions/workflow/status/pf1234321/QuantMind/python-ci.yml?label=python-ci)](.github/workflows/python-ci.yml)

基于 **FastAPI + MySQL** 的 A 股量化交易数据访问、同步、情绪分析与回测一体化平台。
建表 SQL 与同步业务代码迁移自《AI 量化交易训练营》02 / 11 周课程，并在此基础上扩展了个股诊断、缠论信号、组合风控、Qlib 因子研究等模块。

---

## 📑 目录

- [项目简介](#-项目简介)
- [✨ 核心特性](#-核心特性)
- [🚀 快速开始](#-快速开始)
- [🛠 部署指南](#-部署指南)
- [📂 目录结构](#-目录结构)
- [⚙️ 配置说明](#-配置说明)
- [🔐 凭证与安全](#-凭证与安全)
- [⏰ 定时任务](#-定时任务)
- [📡 API 概览](#-api-概览)
- [🗄 数据库](#-数据库)
- [📊 数据来源与同步业务逻辑](#-数据来源与同步业务逻辑)
- [🧪 ATR 跟踪止损参数回测](#-atr-跟踪止损参数回测)
- [⚠️ 注意事项](#-注意事项)
- [📄 License](#-license)

---

## 📖 项目简介

QuantMind 是一个面向 A 股市场的量化研究后端服务。它把零散的数据源（akshare / baostock / 东方财富 / 巨潮 cninfo / 通义千问）汇总进 MySQL，再向上提供统一的 REST API；同时内置 **14 个定时任务**自动维护数据新鲜度，配合前端（`frontend/`）可作为本地化量化工作台。

适用场景：

- 📈 个股 / 板块行情、新闻、研报、公告的数据中台
- 🧠 个股诊断、缠论信号、多空辩论的智能体框架
- 🛡 投资组合风控（ATR 止损、仓位建议、回撤告警）
- 🔬 Qlib 因子研究、时间切分、预测回测

---

## ✨ 核心特性

### 1. 数据采集与同步

- **行情**：日 K 线（baostock 跨平台）、申万行业分类、板块合成指数
- **资讯**：东财个股新闻、研报一致预期、宏观指标、国债收益率、财经日历
- **公告**：东财全市场增量 + 巨潮个股追踪，重要公告自动打标
- **AI 增强**：通义千问 `qwen-max` 做财经催化剂与情感分析

### 2. 市场情绪与事件

- 新闻情感分析（LLM 优先，无 Key 时降级为关键词规则）
- 个股恐惧贪婪指数 + 全市场恐慌指数（VIX/OVX/GVZ/美债10Y 加权）
- 重大事件识别（回购、减持、业绩预增、立案等）与交易信号映射

### 3. 个股诊断（智能体框架）

- 多 Agent 协作：基本面、量化、新闻政策、研究报告
- 多空辩论 + 共识汇总 + 一键调度
- 支持自选股、定时诊断、通知推送

### 4. 缠论信号 & 组合风控

- 缠论买卖点信号入库（`chan_signals`），可被回测调用
- 投资组合快照、ATR 止损决策、风控告警
- 支持自定义风控规则版本与回测关联

### 5. Qlib 因子研究

- 时间切分（TimeSplit）训练/验证/测试划分
- 因子预测运行日志、预测结果、运行记录全流程入库
- 与下游策略解耦，单独跑批

### 6. 工程化

- FastAPI 自动生成 Swagger 文档（`/docs`）
- APScheduler 调度器可独立部署（`python -m app.scheduler`）
- 所有同步任务执行情况自动写入 `sync_task_log`，便于运维追溯
- 前端 `frontend/`（Vue3 + Vite）+ 后端开箱即用：`./start.sh start | stop | restart | status`
- GitHub Actions：**secret-scan** 自动拦截硬编码凭证 / **python-ci** 编译与导入冒烟

---

## 🚀 快速开始

> 完整部署见 [DEPLOYMENT.md](DEPLOYMENT.md)。这里是最小可用版本。

```bash
# 1. 克隆并进入项目
git clone https://github.com/pf1234321/QuantMind.git && cd QuantMind

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 准备配置（密钥占位符请见 .env.example）
cp .env.example .env
# 编辑 .env，至少填写 WUCAI_SQL_PASSWORD

# 5. 初始化数据库（幂等，可重复执行）
python scripts/init_db.py

# 6. 启动 API（默认 http://localhost:8000）
python run.py
# 浏览器打开 http://localhost:8000/docs 查看 Swagger 接口文档
```

需要前端一起跑？

```bash
cd frontend && npm install && cd ..
./start.sh start      # 同时拉起调度器 + API + 前端
```

---

## 🛠 部署指南

请阅读 [DEPLOYMENT.md](DEPLOYMENT.md)，包含：

- 生产环境（Linux / Docker / systemd）部署步骤
- MySQL 数据库初始化（含完整建表脚本）
- 前后端进程管理（`start.sh` 使用说明）
- 反向代理、HTTPS、CORS 等可选配置

---

## 📂 目录结构

```
QuantMind/
├── app/
│   ├── main.py                  # FastAPI 入口（路由 + CORS + 健康检查 + 启动调度器）
│   ├── config.py                # .env 配置加载
│   ├── database.py              # PyMySQL 连接 + execute_query/update/many
│   ├── scheduler.py             # APScheduler 定时调度（任务注册 + 执行日志入库）
│   ├── request_context.py       # 请求上下文与追踪 ID
│   ├── logging_config.py        # 日志配置（含敏感字段脱敏）
│   ├── signals.py               # 缠论信号表
│   ├── trade_plans.py           # 交易计划表
│   ├── api/                     # 对外接口层（REST 路由）
│   │   ├── stocks.py            #   股票行情/财务/新闻/研报/因子/列表
│   │   ├── market.py            #   宏观/利率/日历/板块
│   │   ├── sentiment.py         #   情绪聚合/明细/恐慌指数
│   │   ├── sync.py              #   数据同步触发 + 任务管理
│   │   ├── chat.py              #   AI 对话（DashScope）
│   │   ├── diagnoses.py         #   个股诊断
│   │   ├── backtest.py          #   回测
│   │   ├── risk_control.py      #   组合风控
│   │   ├── qlib.py / qlib_research.py  # Qlib 因子研究
│   │   ├── polymarket.py        #   Polymarket 信号
│   │   └── ...                  #   还有 morning / opportunities / technical 等
│   ├── services/                # 业务层（迁移自课程代码 + 自研）
│   │   ├── kline_sync.py        #   K线同步（baostock）
│   │   ├── financial_sync.py    #   财务同步（akshare）
│   │   ├── macro_sync.py        #   宏观 + 利率
│   │   ├── news_sync.py         #   新闻
│   │   ├── report_sync.py       #   研报
│   │   ├── calendar_sync.py     #   财经日历
│   │   ├── catalyst_sync.py     #   催化剂（Qwen Max）
│   │   ├── industry_sync.py     #   申万行业 + 股本
│   │   ├── sector_sync.py       #   板块聚合/合成指数
│   │   ├── sentiment_sync.py    #   情感分析 + 恐慌指数
│   │   ├── announcement_sync.py #   公告全市场 + 巨潮追踪
│   │   ├── stock_diagnosis.py   #   个股诊断智能体
│   │   ├── qlib_research.py     #   Qlib 因子研究
│   │   ├── rag_vector.py        #   公告 RAG 向量库
│   │   └── llm_client.py        #   DashScope 统一 LLM 客户端
│   ├── backtest/                # 回测引擎（ATR 参数扫描、组合回测）
│   ├── strategy/                # 缠论策略适配
│   └── sql/
│       ├── schema.sql           # 全部建表语句（幂等）
│       ├── technical_indicators.sql
│       ├── technical_trades.sql
│       └── migrations/          # 历史迁移脚本
├── chan.py/                     # 缠论库 vendored 源码
├── scripts/
│   ├── init_db.py               # 建表脚本
│   ├── initialize_database.py   # 一键建库 + 建表 + 中文注释 + 股票基础数据导入
│   ├── sync_all.py              # 全量同步入口
│   ├── backup_database.py       # mysqldump 备份
│   └── ...
├── skills/                      # Claude 量化技能集
├── frontend/                    # Vue3 + Vite 前端
├── tests/                       # 单元测试 / 同步脚本
├── docs/                        # 设计文档 / 临时记录
├── .github/
│   ├── workflows/
│   │   ├── secret-scan.yml      # GitHub Actions：凭证扫描
│   │   └── python-ci.yml        # GitHub Actions：Python 编译 + 冒烟
│   ├── ISSUE_TEMPLATE/          # Issue 模板
│   └── PULL_REQUEST_TEMPLATE.md # PR 模板
├── run.py                       # 后端启动入口
├── start.sh                     # 前后端一键启停
├── requirements.txt
├── .env.example                 # 配置模板（已脱敏）
├── DEPLOYMENT.md                # 部署指南
├── SECURITY.md                  # 凭证与安全策略
├── LICENSE                      # MIT 许可证
└── .gitignore
```

---

## ⚙️ 配置说明

所有配置通过根目录的 `.env` 加载（启动时会自动 `load_dotenv`）。完整模板见 [`.env.example`](.env.example)。

| 分组 | 关键变量 | 说明 |
|---|---|---|
| 数据库 | `WUCAI_SQL_HOST/PORT/USERNAME/PASSWORD/DB` | MySQL 连接信息 |
| 服务 | `API_HOST/API_PORT` | FastAPI 监听地址 |
| 行情 | `EASTMONEY_COOKIE`、`TUSHARE_TOKEN`、`KLINE_*` | 行情 / K 线源 |
| 申万 | `SW_INIT_START_DATE`、`SW_*` | 申万行业同步参数 |
| 调度 | `SCHEDULER_ENABLED` | 是否启用内嵌 APScheduler |
| AI | `DASHSCOPE_API_KEY`、`QWEN_MODEL`、`LLM_MODEL` | 阿里云百炼 LLM |
| 代理 | `HTTP_PROXY` / `HTTPS_PROXY` | 访问海外数据源（Yahoo） |

---

## 🔐 凭证与安全

> 完整策略见 [SECURITY.md](SECURITY.md)。

**核心原则**：**所有密钥只放在本机 `.env`，永远不要进 Git 仓库。**

- `.env` 已加入 `.gitignore`，请勿用 `git add -f .env` 强行添加
- `.env.example` 永远是脱敏模板，提交前检查 `git diff .env.example` 不应包含真实值
- 项目历史中曾存在过 2 个真实凭证：
  - **DASHSCOPE_API_KEY**（阿里云百炼 `sk-...`）
  - **TUSHARE_TOKEN**（Tushare Pro）
  - 已在代码层全部替换为占位符，但相关账号仍**建议立刻去对应厂商控制台轮换（rotate）**
- GitHub Actions [`secret-scan.yml`](.github/workflows/secret-scan.yml) 会在每次 PR / push 时自动扫描硬编码凭证

---

## ⏰ 定时任务

服务启动后（`SCHEDULER_ENABLED=true`）自动加载后台调度器，按交易日收盘后错峰同步，**每次执行情况自动写入 `sync_task_log` 表**。

| 任务 | 说明 | 调度时间（cron） |
|---|---|---|
| `industry` | 申万行业分类+股本 | 每周一 06:30 |
| `kline` | K线日线（baostock） | 交易日 16:30 |
| `sectors` | 板块等权合成指数 | 交易日 17:30 |
| `news` | 个股新闻 | 每日 18:00 |
| `report` | 研报一致预期 | 每日 18:30 |
| `macro` | 宏观+利率 | 每日 19:00 |
| `calendar` | 财经日历 | 每日 06:30 |
| `catalyst` | AI催化剂（需 API key） | 每日 20:00 |
| `sentiment` | 新闻情感分析+情绪聚合（无 API key 自动规则降级） | 交易日 19:30 |
| `events` | 市场事件识别（依赖 sentiment 数据） | 交易日 21:00 |
| `fear_index` | 市场恐慌/贪婪指数（VIX+情绪聚合） | 交易日 21:30 |
| `financial` | 财务（akshare 跨平台） | 每日 20:30 |
| `announcement` | 东财全市场公告增量（回看 3 天） | 每日 22:00 |
| `ann_track` | 巨潮 cninfo 股票池公告追踪 | 交易日 22:30 |

可通过 `.env` 的 `SCHEDULER_ENABLED=false` 关闭；任务时间在 `app/scheduler.py` 的 `TASKS` 中调整。

---

## 📡 API 概览（前缀 `/api/v1`）

| 分组 | 方法 | 路径 | 说明 |
|---|---|---|---|
| 系统 | GET | `/health` | 健康检查（含数据库表数） |
| 股票 | GET | `/stocks/daily?code=600519` | 日 K 线 |
| 股票 | GET | `/stocks/financial?code=` | 财务数据 |
| 股票 | GET | `/stocks/news?code=` | 个股新闻 |
| 股票 | GET | `/stocks/consensus?code=` | 研报一致预期 |
| 股票 | GET | `/stocks/factors?code=` | 研报因子 |
| 股票 | GET | `/stocks/list?keyword=` | 股票基础信息 |
| 市场 | GET | `/market/macro` | 月度宏观指标 |
| 市场 | GET | `/market/rates` | 国债收益率 |
| 市场 | GET | `/market/calendar` | 财经日历 |
| 市场 | GET | `/market/sectors` | 板块日线（合成指数） |
| 情绪 | GET | `/sentiment/aggregate` | 情绪聚合 |
| 情绪 | GET | `/sentiment/detail` | 新闻情绪明细 |
| 情绪 | GET | `/sentiment/fear-index` | 恐慌指数 |
| 同步 | POST | `/sync/kline` | 同步 K 线（baostock） |
| 同步 | POST | `/sync/financial` | 同步财务（akshare） |
| 同步 | POST | `/sync/macro` | 同步宏观+利率 |
| 同步 | POST | `/sync/news` | 同步新闻 |
| 同步 | POST | `/sync/report` | 同步研报 |
| 同步 | POST | `/sync/calendar` | 同步日历 |
| 同步 | POST | `/sync/industry` | 同步申万行业 |
| 同步 | POST | `/sync/sectors` | 板块聚合重算 |
| 同步 | POST | `/sync/catalyst` | 催化剂（Qwen Max） |
| 同步 | POST | `/sync/sentiment` | 新闻情感分析+情绪聚合 |
| 同步 | POST | `/sync/events` | 市场事件识别 |
| 同步 | POST | `/sync/fear-index` | 恐慌/贪婪指数 |
| 同步 | POST | `/sync/announcement` | 东财全市场公告增量 |
| 同步 | POST | `/sync/announcement/track` | 巨潮 cninfo 股票池追踪 |
| 同步 | POST | `/sync/all` | 全量同步 |
| 任务 | GET | `/sync/tasks` | 查看所有定时任务 |
| 任务 | GET | `/sync/logs` | 查询任务执行日志 |
| 任务 | GET | `/sync/logs/summary` | 每个任务最近执行概况 |
| 任务 | POST | `/sync/run/{task}` | 手动触发某个定时任务 |

完整接口（含诊断 / 风控 / 回测 / Qlib / Polymarket / RAG 等）请访问 `http://localhost:8000/docs`。

---

## 🗄 数据库

数据库名固定 `wucai_trade`。完整建表脚本：

- 主脚本：[`app/sql/schema.sql`](app/sql/schema.sql)（约 1000 行，幂等 `CREATE TABLE IF NOT EXISTS`）
- 技术指标：[`app/sql/technical_indicators.sql`](app/sql/technical_indicators.sql)
- 技术交易：[`app/sql/technical_trades.sql`](app/sql/technical_trades.sql)
- 历史迁移：[`app/sql/migrations/`](app/sql/migrations/)

| 表名 | 说明 |
|---|---|
| `trade_stock_daily` | 股票日 K 线 |
| `trade_stock_news` | 股票新闻事件 |
| `trade_stock_financial` | 股票季度财务 |
| `trade_macro_indicator` | 月度宏观指标（宽表） |
| `trade_rate_daily` | 日频国债收益率 |
| `trade_report_consensus` | 研报一致性预期 |
| `trade_calendar_event` | 财经日历事件 |
| `trade_stock_status` | 股票状态/申万分类/股本 |
| `trade_sector_daily` | 板块每日聚合+合成指数 |
| `trade_factor_consensus` | 研报一致性预测因子 |
| `sentiment_detail` | 新闻情绪明细 |
| `sentiment_aggregate` | 个股情绪聚合（恐惧贪婪指数） |
| `market_events` | 市场事件+交易信号 |
| `fear_index_history` | 市场恐慌/贪婪指数历史 |
| `trade_sector_daily_copy1` | 板块副本表 |
| `trade_stock_announcement` | 上市公司公告（东财全市场+巨潮个股，含重要标记） |
| `sync_task_log` | 同步任务执行日志（定时任务/手动触发） |
| `chan_signals` | 缠论买卖点信号 |
| `trade_plan` | 交易计划 |
| `risk_portfolio_snapshot` / `risk_decision` / `risk_alert` | 组合风控 |
| `stock_diagnosis_task` / `diagnosis_*` | 个股诊断多 Agent 结果 |
| `qlib_research_*` | Qlib 因子研究运行 / 预测 / 日志 |
| `polymarket_signal` | Polymarket 信号 |
| `research_report_chunk` | 公告 RAG 文本分块 |

> 行数随同步进度变化；首次部署可参考 [DEPLOYMENT.md](DEPLOYMENT.md) 的"预期数据量"小节。

---

## 📊 数据来源与同步业务逻辑

数据整体分为三类：**外部采集**（akshare / baostock / LLM 联网）、**内部派生**（基于已入库数据计算）、**运维记录**（任务日志）。同步入口统一在 `app/scheduler.py` 的 `TASKS` 注册，由 APScheduler 定时触发，每次执行自动写 `sync_task_log`。

### 一、外部数据源采集

| 表 | 数据源 | 同步服务 | 调度时间 | 业务逻辑 |
|---|---|---|---|---|
| `trade_stock_daily` | baostock | `kline_sync.py` | 交易日 16:30 | 按股票代码逐个拉取日 K 线（开高低收、成交量、成交额、换手率），默认取 `trade_stock_status` 全市场股票，前复权，macOS / Windows / Linux 均可用 |
| `trade_stock_news` | akshare 东财个股新闻 | `news_sync.py` | 每日 18:00 | 默认取 `trade_stock_status` 前 200 只股票，每只拉最新 50 条新闻 |
| `trade_stock_financial` | akshare 东财业绩报表 + 财务摘要 | `financial_sync.py` | 每日 20:30 | 跨平台（macOS 可用），主路径按报告期全市场批量拉取业绩报表 |
| `trade_macro_indicator` | akshare 宏观经济接口 | `macro_sync.py` | 每日 19:00 | 月度宏观指标宽表（CPI/PPI/PMI 等） |
| `trade_rate_daily` | akshare（`bond_zh_us_rate`） | `macro_sync.py` | 每日 19:00 | 中美国债收益率日频数据 |
| `trade_report_consensus` | akshare 东财机构评级 + 同花顺盈利预测 | `report_sync.py` | 每日 18:30 | 逐股拉取机构评级明细 + EPS/净利润/主营收入预测 |
| `trade_calendar_event` | akshare 百度财经日历 + Qwen Max 联网搜索 | `calendar_sync.py` / `catalyst_sync.py` | 每日 06:30 / 每日 20:00 | ① 最近 30 天至未来 7 天的经济数据事件；② Qwen Max 搜索未来 180 天重大催化剂 |
| `trade_stock_status` | akshare 申万行业 + baostock 股本 | `industry_sync.py` | 每周一 06:30 | 拉取申万行业成分股映射 + 股本 |
| `trade_stock_announcement` | akshare 东财公告 + 巨潮官方 | `announcement_sync.py` | 每日 22:00 / 交易日 22:30 | ① 东财全市场增量；② 巨潮股票池追踪；按关键词自动标记重要公告 |

### 二、内部派生数据

| 表 | 数据上游 | 同步服务 | 调度时间 | 业务逻辑 |
|---|---|---|---|---|
| `trade_sector_daily` | `trade_stock_status` + `trade_stock_daily` | `sector_sync.py` | 交易日 17:30 | 按申万板块聚合成分股日线 + 累乘合成等权指数 |
| `trade_factor_consensus` | `trade_report_consensus` 派生 | 外部课程脚本 | — | 目标价均值 / 评级动量 / EPS 预测分歧度等因子 |
| `sentiment_detail` | `trade_stock_news` | `sentiment_sync.py` | 交易日 19:30 | 新闻情感分析（LLM 优先 / 规则降级） |
| `sentiment_aggregate` | `sentiment_detail` | `sentiment_sync.py` | 交易日 19:30 | 按股票聚合近 N 天情感明细，计算 0-100 恐惧贪婪指数 |
| `market_events` | `sentiment_detail` | `sentiment_sync.py` | 交易日 21:00 | 从高强度新闻识别重大事件 + 交易信号 |
| `fear_index_history` | akshare VIX/OVX/GVZ/美债10Y + `sentiment_aggregate` | `sentiment_sync.py` | 交易日 21:30 | VIX 归一化 0-100，与情绪聚合 fgi 按 4:6 加权合成 |

### 三、运维记录

| 表 | 来源 | 写入逻辑 |
|---|---|---|
| `sync_task_log` | 每次同步执行（定时触发 / API 手动触发） | `task_log_service.py` 在任务开始/结束时记录任务名、触发方式、状态、写入行数、耗时与错误信息 |

### 数据流总览

```
外部数据源                        落库                           派生数据
─────────────                    ─────                          ─────
akshare ── K线 ──────────────────> trade_stock_daily ──┐
akshare ── 新闻 ─────────────────> trade_stock_news  ──┤
akshare ── 研报 ─────────────────> trade_report_consensus ─> trade_factor_consensus(外部脚本)
akshare ── 宏观/利率 ─────────────> trade_macro_indicator / trade_rate_daily
akshare/baostock ── 申万行业/股本 ─> trade_stock_status ──┤
akshare ── 财务 ──────────────> trade_stock_financial
akshare ── 财经日历 ──────────────> trade_calendar_event
Qwen Max 联网 ── 催化剂 ──────────> trade_calendar_event(qwen_search)
akshare东财 ── 公告全市场 ─────────> trade_stock_announcement（is_important 标记）
巨潮cninfo ── 公告股票池追踪 ──────> trade_stock_announcement
                                                  │
                                                  ├─> sentiment_detail ─> sentiment_aggregate ─> fear_index_history
                                                  │       └─> market_events
                                                  └─> trade_sector_daily（板块合成指数）
```

> 注意：`trade_factor_consensus` 与 `trade_stock_status` 初始股票列表目前由课程脚本/建库脚本生成，未包含在本服务定时任务中。

---

## 🧪 ATR 跟踪止损参数回测

参数扫描模块位于 `app/backtest/`，不会修改课程策略入口。它要求通过 `--course-module` 显式提供课程适配模块，该模块必须实现 `run_parameter_backtest(df, atr_exit_mult, config)` 并返回 `BacktestResult`，避免缺少缠论依赖时静默替换策略。

```bash
python scripts/scan_atr_exit_mult.py \
  --course-module /path/to/course_adapter.py \
  --stock-code 300750 \
  --start-date 2020-01-01 \
  --end-date 2025-12-31 \
  --output-dir data/backtest/atr_scan
```

默认扫描 `1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0, 4.5`；也可用 `--range-start`、`--range-end`、`--step` 自定义范围。输出汇总、交易明细、资金曲线和 JSON 报告。当前完整历史缠论信号适配会明确标记前视偏差风险，结果不可直接视为实盘结论。

---

## ⚠️ 注意事项

- **K 线数据**（`sync/kline`）使用 baostock 跨平台源（macOS / Windows / Linux 均可用），无需安装 QMT 客户端；**财务数据**（`sync/financial`）使用 akshare 跨平台源，同样无需任何 Windows 客户端。
- **催化剂同步**（`sync/catalyst`）需要设置环境变量 `DASHSCOPE_API_KEY`；无 Key 时 sentiment 自动降级为规则分析。
- 数据同步均为长任务，直接 POST 会阻塞；正式环境建议接入任务队列 + SSE 进度推送（见《量化交易系统-架构设计.md》）。
- 本项目仅供学习研究，不构成任何投资建议。

---

## 📄 License

[MIT](LICENSE) © 2024-2026 QuantMind Contributors