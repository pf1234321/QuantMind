# QuantMind 部署指南

> 本文面向 **运维 / 部署** 场景：把 QuantMind 部署到一台 Linux 服务器（或 macOS / Windows 本机）并接入生产级 MySQL。
> 如果你只是想在本地快速跑通，参考 [README.md](README.md) 的「快速开始」即可。

---

## 📑 目录

- [一、环境要求](#一环境要求)
- [二、获取代码](#二获取代码)
- [三、配置 `.env`](#三配置-env)
- [四、数据库部署](#四数据库部署)
- [五、Python 环境与依赖](#五python-环境与依赖)
- [六、前端构建](#六前端构建)
- [七、启动服务](#七启动服务)
- [八、生产级部署（推荐）](#八生产级部署推荐)
- [九、运维与备份](#九运维与备份)
- [十、常见问题](#十常见问题)

---

## 一、环境要求

| 组件 | 最低版本 | 推荐版本 | 说明 |
|---|---|---|---|
| OS | macOS 12 / Ubuntu 20.04 / Windows 10 | Ubuntu 22.04 LTS | 任意可跑 Python 3.10 的系统 |
| Python | 3.10 | 3.11 | 用于 FastAPI / APScheduler |
| Node.js | 18 | 20 LTS | 前端构建（可选用纯 API 模式则不需要） |
| MySQL | 5.7 | 8.0 | 数据库服务器 |
| 磁盘 | 5 GB | 20 GB+ | K 线（515 万行）+ 公告 RAG 向量占空间 |

外部依赖（运行时按需访问）：

- akshare / baostock：默认即可访问
- 东方财富行情：可能被限流，需要 `EASTMONEY_COOKIE`
- Tushare Pro：注册 [tushare.pro](https://tushare.pro/) 获取 `TUSHARE_TOKEN`
- 阿里云百炼 DashScope：注册 [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) 获取 `DASHSCOPE_API_KEY`
- （可选）Clash 等代理：访问 Yahoo Finance 时使用

---

## 二、获取代码

```bash
git clone <your-repo-url> QuantMind
cd QuantMind
```

> 默认分支：`main`。生产环境建议固定 tag：`git checkout v1.x.y`。

---

## 三、配置 `.env`

```bash
cp .env.example .env
vim .env   # 或使用你喜欢的编辑器
```

至少修改以下 4 项（其余保持默认即可）：

```dotenv
WUCAI_SQL_HOST=127.0.0.1
WUCAI_SQL_PORT=3306
WUCAI_SQL_USERNAME=quantmind
WUCAI_SQL_PASSWORD=<your_mysql_password>
WUCAI_SQL_DB=wucai_trade

DASHSCOPE_API_KEY=<your_dashscope_api_key>
TUSHARE_TOKEN=<your_tushare_token>
```

> ⚠️ `.env` 已加入 `.gitignore`，**永远不要提交**。  
> 详细字段含义见 [`.env.example`](.env.example) 与 [README.md](README.md#-配置说明)。

---

## 四、数据库部署

### 4.1 创建数据库与用户（MySQL 8.0）

以 root 登录 MySQL 控制台：

```sql
CREATE DATABASE wucai_trade DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'quantmind'@'%' IDENTIFIED BY '<your_mysql_password>';
GRANT ALL PRIVILEGES ON wucai_trade.* TO 'quantmind'@'%';
FLUSH PRIVILEGES;
```

> 也可以让脚本自动建库（见 4.3 一键初始化），但**用户必须先在 MySQL 里建好**。

### 4.2 建表脚本

SQL 脚本随仓库一起发布，位于 `app/sql/`：

| 脚本 | 说明 | 是否必跑 |
|---|---|---|
| `app/sql/schema.sql` | 主建表脚本（约 1000 行，22+ 张表，幂等） | ✅ 必跑 |
| `app/sql/technical_indicators.sql` | 技术指标表 | ⚠️ 启用技术分析时跑 |
| `app/sql/technical_trades.sql` | 技术交易表 | ⚠️ 启用技术分析时跑 |
| `app/sql/migrations/001_add_unique_key_to_trades.sql` | 历史迁移示例 | 看 README 历史 |

直接执行主脚本：

```bash
mysql -uquantmind -p wucai_trade < app/sql/schema.sql
```

或者用项目自带的 Python 初始化脚本（**推荐**，会自动跳过已存在的表）：

```bash
python scripts/init_db.py
```

### 4.3 一键初始化（推荐）

`scripts/initialize_database.py` 会一次完成：

1. 创建数据库 `wucai_trade`（如不存在）
2. 执行 `schema.sql` 建表
3. 补齐中文注释（表 + 字段）
4. 导入 A 股基础信息（`data/a股全量_基础_申万2021_唯一行业.csv`）
5. （可选）触发 K 线全量同步（传 `--skip-kline` 跳过）

```bash
# 需要先在 .env 中配置好 MySQL 账号
python scripts/initialize_database.py            # 全量初始化（含 K 线）
python scripts/initialize_database.py --skip-kline  # 跳过 K 线
```

### 4.4 预期数据量（首次全量同步后）

| 表 | 估算行数 |
|---|---|
| `trade_stock_daily` | ~515 万 |
| `trade_stock_news` | ~110（默认仅前 200 只 × 50 条） |
| `trade_stock_financial` | ~64 |
| `trade_macro_indicator` | ~121 |
| `trade_rate_daily` | ~799 |
| `trade_report_consensus` | ~4.7 万 |
| `trade_calendar_event` | ~1500 |
| `trade_stock_status` | ~5200 |
| `trade_sector_daily` | ~7.4 万 |
| `trade_factor_consensus` | ~65 万（由外部脚本生成） |
| `trade_stock_announcement` | 视同步次数，持续增长 |

---

## 五、Python 环境与依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` 主要依赖：

```
fastapi
uvicorn[standard]
pymysql
sqlalchemy
python-dotenv
apscheduler
pandas
akshare
baostock
tushare
dashscope
openai
pydantic
...
```

如果只想跑 API 不做同步，可以裁剪依赖；推荐保持完整，方便后续启用 AI 功能。

---

## 六、前端构建

前端位于 `frontend/`，是 Vue3 + Vite 项目。

### 6.1 开发模式（带热更新）

```bash
cd frontend
npm install
npm run dev      # 默认 http://localhost:5173
```

### 6.2 生产构建

```bash
cd frontend
npm install
npm run build
# 产物在 frontend/dist/
```

生产构建后用 Nginx 反向代理 `frontend/dist` 的静态资源即可（见第八节）。

---

## 七、启动服务

仓库自带 `start.sh`，一键管理调度器 + API + 前端：

```bash
chmod +x start.sh
./start.sh start      # 启动全部
./start.sh stop       # 停止全部
./start.sh restart    # 重启
./start.sh status     # 查看状态
```

启动后会输出：

```
========== QuantMind 启动 ==========
[调度器] 启动成功 (PID xxxx)
[API服务] 启动成功 (PID xxxx)
[前端服务] 启动成功 (PID xxxx)
==================================
前端页面: http://localhost:5173
API 文档: http://localhost:8000/docs
健康检查: http://localhost:8000/health
```

> `start.sh` 的 `start_api` 会自动设置 `SCHEDULER_ENABLED=false`，避免调度器重复执行（已由独立进程 `python -m app.scheduler` 承担）。

### 手动启动（不依赖 `start.sh`）

```bash
# 后端 API
python run.py                                     # 启用内嵌调度器（开发模式）

# 调度器独立部署（推荐生产）
SCHEDULER_ENABLED=false python -m app.scheduler

# 前端
cd frontend && npm run dev
```

---

## 八、生产级部署（推荐）

### 8.1 systemd 单元（API + 调度器）

`/etc/systemd/system/quantmind-api.service`：

```ini
[Unit]
Description=QuantMind FastAPI
After=network.target mysql.service

[Service]
Type=simple
User=quantmind
WorkingDirectory=/opt/QuantMind
EnvironmentFile=/opt/QuantMind/.env
Environment=SCHEDULER_ENABLED=false
ExecStart=/opt/QuantMind/.venv/bin/python run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/quantmind-scheduler.service`：

```ini
[Unit]
Description=QuantMind Scheduler
After=network.target mysql.service

[Service]
Type=simple
User=quantmind
WorkingDirectory=/opt/QuantMind
EnvironmentFile=/opt/QuantMind/.env
ExecStart=/opt/QuantMind/.venv/bin/python -m app.scheduler
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now quantmind-api quantmind-scheduler
sudo systemctl status quantmind-api quantmind-scheduler
```

### 8.2 Nginx 反向代理

`/etc/nginx/sites-available/quantmind.conf`：

```nginx
server {
    listen 80;
    server_name quantmind.your-domain.com;

    # 前端静态资源
    root /opt/QuantMind/frontend/dist;
    index index.html;

    # API 反代
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;        # 长任务
        proxy_send_timeout 300s;
    }

    # Swagger / 健康检查
    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
    }

    # 其余走前端路由
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

启用 HTTPS（推荐 Let's Encrypt）：

```bash
sudo certbot --nginx -d quantmind.your-domain.com
```

### 8.3 Docker（可选）

仓库未自带 Dockerfile，下面是最小化示例，按需完善：

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "run.py"]
```

```bash
docker build -t quantmind:latest .
docker run -d --name quantmind \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  quantmind:latest
```

---

## 九、运维与备份

### 9.1 备份数据库

仓库自带 `scripts/backup_database.py`（或根目录的 `backup_database.py`），依赖 `mysqldump`：

```bash
python scripts/backup_database.py
# 备份文件输出到 ./backups/wucai_trade_backup_<时间戳>.sql
```

配合 cron 每天凌晨跑：

```cron
0 2 * * * cd /opt/QuantMind && .venv/bin/python scripts/backup_database.py >> /var/log/quantmind-backup.log 2>&1
```

### 9.2 同步任务日志

每次同步（定时或手动）都会写入 `sync_task_log` 表，可通过 API 查询：

```bash
curl http://localhost:8000/api/v1/sync/tasks
curl "http://localhost:8000/api/v1/sync/logs?task=kline&limit=20"
curl http://localhost:8000/api/v1/sync/logs/summary
```

### 9.3 手动触发同步

```bash
curl -X POST http://localhost:8000/api/v1/sync/kline
curl -X POST http://localhost:8000/api/v1/sync/all
curl -X POST http://localhost:8000/api/v1/sync/run/kline    # 模拟定时触发
```

### 9.4 升级

```bash
cd /opt/QuantMind
git pull
source .venv/bin/activate
pip install -r requirements.txt --upgrade
python scripts/init_db.py       # 幂等，自动加新表 / 新列
sudo systemctl restart quantmind-api quantmind-scheduler
```

> 注意每次升级前后查看 [`CHANGELOG`](docs/)（如有）或 `git log` 了解 schema 变化。

---

## 十、常见问题

#### Q1：启动报 `RuntimeError: 缺少环境变量 DASHSCOPE_API_KEY`

说明你触发了依赖 LLM 的接口（如 `/sync/catalyst`）。两种处理：

1. 在 `.env` 中填入 `DASHSCOPE_API_KEY`
2. 不使用 LLM 相关功能（情感分析会自动降级为关键词规则）

#### Q2：MySQL 连接失败 `Can't connect to MySQL server`

- 检查 `WUCAI_SQL_HOST/PORT/USERNAME/PASSWORD/DB`
- `mysql -u<user> -p -h<host> -P<port>` 测试连通性
- 远程 MySQL 检查防火墙 + `bind-address`

#### Q3：K 线同步慢 / 中断

- 调整 `KLINE_MAX_WORKERS`（默认 4）
- `EASTMONEY_COOKIE` 被限流时手工填一个
- akshare 接口偶尔 500，重跑即可（脚本自带 `KLINE_MAX_ATTEMPTS=3` 重试）

#### Q4：`mlruns/` 越来越大

那是你自己跑的 MLflow 实验目录，已加入 `.gitignore`。如不需要可定期清理：

```bash
rm -rf mlruns/
```

#### Q5：能否纯内网部署（不能访问 akshare / 通义千问）？

可以，但只能跑存量数据查询接口。所有 `sync/*` 同步任务需要外网。如确实无外网，需把 akshare / 巨潮数据离线导入到对应表。

---

部署完成后，建议先用以下命令做端到端验证：

```bash
# 1. 健康检查
curl http://localhost:8000/health
# {"status":"ok","database":{...}}

# 2. 取一只股票 K 线
curl "http://localhost:8000/api/v1/stocks/daily?code=600519&limit=5"

# 3. 触发一次 K 线同步（短任务）
curl -X POST http://localhost:8000/api/v1/sync/kline
```

有任何问题，优先看 `data/logs/app.log` 和 `data/logs/runtime.log`，再带着 trace_id 提交 Issue。