# Security Policy

> QuantMind 把**凭证隔离**作为第一原则：任何 API Key / Token / Cookie **只放在本机 `.env`**，**永远不进 Git 仓库**。

---

## 支持的版本

| 分支 | 是否接收安全更新 |
|---|---|
| `main`（最新发布） | ✅ |
| 历史 tag | 视情况 |

---

## 🔐 凭证存放位置（应 / 不应）

### ✅ 应该放在

- 本机 `/path/to/QuantMind/.env`（**已加入 `.gitignore`**）
- 服务器 systemd 单元的 `EnvironmentFile=/opt/QuantMind/.env`
- CI / 部署平台的 Secret 变量（如 GitHub Actions Secrets、Vault）

### ❌ 不应该放在

- 仓库根目录的 `*.py` / `*.json` / `*.yml` 任何代码文件
- `.env.example`（这是脱敏模板，**永远是占位符**）
- Commit message / PR 描述 / Issue / Wiki
- Docker 镜像层（用 `--env-file` 注入而不是 `ENV`）

---

## 📋 当前已识别的敏感字段

| 环境变量 | 厂商 | 备注 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼（DashScope） | 用于 `qwen-max` 催化剂 / 情感分析 / RAG |
| `TUSHARE_TOKEN` | Tushare Pro | K 线全量拉取（baostock 失败时降级） |
| `EASTMONEY_COOKIE` | 东方财富 | K 线同步限流时手工填入 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 本机 Clash | 通常是 `127.0.0.1:7890`，不视为高危 |
| `WUCAI_SQL_PASSWORD` | MySQL | 数据库密码，按内部规范管理 |

---

## ⚠️ 历史泄露说明（请尽快轮换）

仓库历史中曾有 2 个真实凭证被硬编码 / 写入 `.env`：

1. **DASHSCOPE_API_KEY**（`sk-...` 开头）
2. **TUSHARE_TOKEN**（Tushare Pro 个人 Token）

代码层已经全部替换为占位符，但相关账号仍**强烈建议立刻去对应厂商控制台轮换**：

- 阿里云百炼：https://bailian.console.aliyun.com/ → API-Key 管理 → **禁用旧 Key → 签发新 Key**
- Tushare Pro：https://tushare.pro/user/token → **重置 Token**

轮换后只需更新本机 `.env` 中对应字段，无需改代码。

---

## 🚨 误提交了凭证怎么办？

按以下顺序处理（**先堵漏，再清理**）：

### 1. 立即轮换凭证

去对应厂商控制台**撤销 / 重置**该凭证，拿到新值。

### 2. 更新本地 `.env`

```bash
# .env
DASHSCOPE_API_KEY=<new_key>
TUSHARE_TOKEN=<new_token>
```

### 3. 从 Git 历史中抹除（如果已经 push）

使用 [`git-filter-repo`](https://github.com/newren/git-filter-repo) 或 `BFG Repo-Cleaner` 重写历史，**然后 force-push**：

```bash
# 例：用 git-filter-repo 把 .env 从所有历史 commit 中删掉
pip install git-filter-repo
git filter-repo --invert-paths --path .env
git remote add origin <your-repo-url>
git push origin --force --all
```

> ⚠️ force-push 会让所有 fork / clone 失效；如果你已经在 issue / PR 中贴过该凭证，也需要一并清理。

### 4. 通知协作者

让所有协作者重新 clone（而不是 pull），因为旧的 commit 对象仍然存在于他们的本地仓库。

---

## 🛡 提交前自检清单

每次 `git add` 前，请运行：

```bash
git diff --staged | grep -iE "(sk-[a-z0-9]{16,}|tushare|cookie|password|secret|token)" || echo "OK"
```

CI / PR 检查也可以加一条同样的 grep 防止意外泄露。

---

## 📬 报告漏洞

发现可被利用的安全问题，请**私下**联系维护者：

- GitHub Issue（标记 `security` 但**不要贴具体漏洞细节**）
- 邮件：`security@quantmind.local`（示例地址，按实际替换）

请避免在公开 issue 中直接贴出可复现的 PoC。

---

## 📚 相关阅读

- [`.env.example`](.env.example)：脱敏配置模板
- [`.gitignore`](.gitignore)：`.env` 已被忽略
- [GitHub 官方指南：Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)