# 🚀 部署指南

本文档介绍如何将 A股自选股智能分析系统部署到服务器。

如需部署完成后的日常运维命令速查，可参考 [服务器运维手册](server-ops.md)。

## 📋 部署方案对比

| 方案 | 优点 | 缺点 | 推荐场景 |
|------|------|------|----------|
| **Docker Compose** ⭐ | 一键部署、环境隔离、易迁移、易升级 | 需要安装 Docker | **推荐**：大多数场景 |
| **直接部署** | 简单直接、无额外依赖 | 环境依赖、迁移麻烦 | 临时测试 |
| **Systemd 服务** | 系统级管理、开机自启 | 配置繁琐 | 长期稳定运行 |
| **Supervisor** | 进程管理、自动重启 | 需要额外安装 | 多进程管理 |

**结论：推荐使用 Docker Compose，迁移最快最方便！**

---

## 🐳 方案一：Docker Compose 部署（推荐）

### 1. 安装 Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# CentOS
sudo yum install -y docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

### 2. 准备配置文件

```bash
# 克隆代码（或上传代码到服务器）
git clone <your-repo-url> /opt/stock-analyzer
cd /opt/stock-analyzer

# 复制并编辑配置文件
cp .env.example .env
vim .env  # 填入真实的 API Key 等配置
```

### 3. 一键启动

```bash
# 构建并启动
docker-compose -f ./docker/docker-compose.yml up -d

# 查看日志
docker-compose -f ./docker/docker-compose.yml logs -f

# 查看运行状态
docker-compose -f ./docker/docker-compose.yml ps
```

### 4. 常用管理命令

```bash
# 停止服务
docker-compose -f ./docker/docker-compose.yml down

# 重启服务
docker-compose -f ./docker/docker-compose.yml restart

# 更新代码后重新部署
git pull
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d

# 进入容器调试
docker-compose -f ./docker/docker-compose.yml exec stock-analyzer bash

# 手动执行一次分析
docker-compose -f ./docker/docker-compose.yml exec stock-analyzer python main.py --no-notify
```

### 5. 数据持久化

数据自动保存在宿主机目录：
- `./data/` - 数据库文件
- `./logs/` - 日志文件
- `./reports/` - 分析报告

---

## 🖥️ 方案二：直接部署

### 1. 安装 Python 环境

```bash
# 安装 Python 3.10+
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# 创建虚拟环境
python3 -m venv /opt/stock-analyzer/venv
source /opt/stock-analyzer/venv/bin/activate
```

### 2. 安装依赖

```bash
cd /opt/stock-analyzer
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置环境变量

```bash
cp .env.example .env
vim .env  # 填入配置
```

### 4. 运行

```bash
# 单次运行
python main.py

# 定时任务模式（前台运行）
python main.py --schedule

# 后台运行（使用 nohup）
nohup python main.py --schedule > /dev/null 2>&1 &
```

### Ubuntu 24.04 一键初始化（推荐）

如果你希望在 Ubuntu 24.04 上先把系统依赖、独立 Python 环境所需组件，以及 `codex` CLI 一次准备好，可以使用：

```bash
cd /opt/stock-analyzer
chmod +x ./scripts/bootstrap-server-ubuntu.sh
sudo APP_USER=stock ./scripts/bootstrap-server-ubuntu.sh
```

这个脚本会：
- 安装系统默认 `python3`、`python3-venv`、`pip`
- 安装 Node.js 和 `npm`
- 通过 `npm install -g @openai/codex` 安装 `codex` CLI
- 创建 `data/`、`logs/`、`reports/`
- 如果传入 `APP_USER=stock`，会顺手把项目目录属主修正为 `stock:stock`

完成后继续：

```bash
codex login --device-auth
./scripts/start-server-ubuntu.sh --llm-smoke-test
./scripts/start-server-ubuntu.sh
```

> 建议把“系统依赖安装”和“服务启动”分开。不要让 `systemd` 每次重启服务时都顺手执行 `apt` 或 `npm install`，这样更稳定，也更不容易影响服务器上其他业务。

---

## 🔧 方案三：Systemd 服务

创建 systemd 服务文件实现开机自启和自动重启：

如果你希望先在 Ubuntu 24.04 上使用**独立虚拟环境**启动后端，可优先使用仓库脚本：

```bash
cd /opt/stock-analyzer
chmod +x ./scripts/start-server-ubuntu.sh
./scripts/start-server-ubuntu.sh
```

说明：
- 默认在仓库内创建独立环境：`/opt/stock-analyzer/.server-venv`
- 默认启动命令：`python main.py --serve-only --host 0.0.0.0 --port 8000`
- 不会修改系统 Python 包，适合与其他服务共存
- 启动脚本会自动安装/更新仓库 Python 依赖到 `.server-venv`，但不会执行 `apt` 或安装 `codex` CLI
- 如果 `data/`、`logs/`、`reports/` 或 `.server-venv` 不可写，启动脚本会提前报错并提示修复属主
- 如需改端口，可使用：`HOST=0.0.0.0 PORT=8010 ./scripts/start-server-ubuntu.sh`
- 如需运行其他命令，可直接把参数传给脚本，例如：`./scripts/start-server-ubuntu.sh --schedule`

推荐拆成两个 service，共用同一个项目目录、`.env`、数据库和报告目录：
- `stock-analyzer.service`：常驻 Web/API 服务，运行 `--serve-only`
- `stock-analyzer-schedule.service`：常驻定时调度器，运行 `--schedule --no-run-immediately`

这样两者共享绝大部分信息，但职责清晰，不会互相覆盖。

### 1. 创建 Web/API 服务文件

```bash
cp ./scripts/stock-analyzer.service.example /tmp/stock-analyzer.service
vim /tmp/stock-analyzer.service
```

将下面这些占位符替换成你的实际值：
- `<APP_USER>`：运行服务的 Linux 用户，建议单独创建如 `stock`
- `<APP_DIR>`：项目部署目录，例如 `/opt/stock-analyzer`

模板文件位置：
- `scripts/stock-analyzer.service.example`
- `scripts/stock-analyzer-schedule.service.example`

替换后，将服务文件复制到 systemd 目录：

```ini
[Unit]
Description=Daily Stock Analysis service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<APP_USER>
Group=<APP_USER>
WorkingDirectory=<APP_DIR>
Environment=HOST=0.0.0.0
Environment=PORT=8000
Environment=WEBUI_AUTO_BUILD=false
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=<APP_DIR>/scripts/start-server-ubuntu.sh
Restart=always
RestartSec=30
TimeoutStartSec=300
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

安装到 systemd：

```bash
sudo cp /tmp/stock-analyzer.service /etc/systemd/system/stock-analyzer.service
```

### 2. 创建定时调度服务文件

```bash
cp ./scripts/stock-analyzer-schedule.service.example /tmp/stock-analyzer-schedule.service
vim /tmp/stock-analyzer-schedule.service
```

内容如下：

```ini
[Unit]
Description=Daily Stock Analysis scheduled runner
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<APP_USER>
Group=<APP_USER>
WorkingDirectory=<APP_DIR>
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=<APP_DIR>/scripts/start-server-ubuntu.sh --schedule --no-run-immediately
Restart=always
RestartSec=30
TimeoutStartSec=300
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

安装到 systemd：

```bash
sudo cp /tmp/stock-analyzer-schedule.service /etc/systemd/system/stock-analyzer-schedule.service
```

### 3. 启动服务

```bash
# 重载配置
sudo systemctl daemon-reload

# 启动 Web/API 服务
sudo systemctl start stock-analyzer

# 启动定时调度服务
sudo systemctl start stock-analyzer-schedule

# 开机自启
sudo systemctl enable stock-analyzer
sudo systemctl enable stock-analyzer-schedule

# 查看状态
sudo systemctl status stock-analyzer
sudo systemctl status stock-analyzer-schedule

# 查看日志
journalctl -u stock-analyzer -f
journalctl -u stock-analyzer-schedule -f
```

如果你只想启动 Web/API 常驻服务，不跑进程内定时器，可以只安装 `stock-analyzer.service`。

如果你需要改端口，例如 `18000`，可直接修改 Web/API 服务中的：

```ini
Environment=PORT=18000
```

如果你希望每天早上 08:00 运行，修改 `.env`：

```env
SCHEDULE_TIME=08:00
```

注意：
- `stock-analyzer-schedule.service` 使用 `--no-run-immediately`，所以服务启动时不会先跑一轮
- 它只会等到 `.env` 中的 `SCHEDULE_TIME` 到点再执行

---

## ⚙️ 配置说明

### 必须配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `STOCK_LIST` | 自选股列表 | 逗号分隔的股票代码 |
| `LLM_BACKEND` | LLM 后端，`codex` 或 `native` | `.env` |
| `FEISHU_WEBHOOK_URL` / 其他通知渠道 | 推送结果到飞书/Telegram/企微等 | 各平台机器人 |

> 如果你使用 `LLM_BACKEND=codex`，服务器上还需要可用的 `codex` CLI 和登录态，不要求在 `.env` 中配置 `OPENAI_API_KEY/GEMINI_API_KEY`。

### `codex` CLI 准备

服务器模式下若要使用 `LLM_BACKEND=codex`，建议按以下顺序准备：

```bash
# 1. 安装 Codex CLI（按你的安装方式）
codex --version

# 2. 登录
codex login --device-auth

# 3. 在项目目录探活
cd /opt/stock-analyzer
./scripts/start-server-ubuntu.sh --llm-smoke-test
```

探活成功后，再启动常驻服务或 systemd。

### `native` 模式必须配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` 等 | AI 分析必需 | 各模型平台 |
| `STOCK_LIST` | 自选股列表 | 逗号分隔的股票代码 |
| `WECHAT_WEBHOOK_URL` | 微信推送 | 企业微信群机器人 |

### 可选配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SCHEDULE_ENABLED` | `false` | 是否启用定时任务 |
| `SCHEDULE_TIME` | `18:00` | 每日执行时间 |
| `MARKET_REVIEW_ENABLED` | `true` | 是否启用大盘复盘 |
| `TAVILY_API_KEYS` | - | 新闻搜索（可选） |
| `MINIMAX_API_KEYS` | - | MiniMax 搜索（可选） |

---

## 🌐 代理配置

如果服务器在国内，访问 Gemini API 需要代理：

### Docker 方式

编辑 `docker-compose.yml`：
```yaml
environment:
  - http_proxy=http://your-proxy:port
  - https_proxy=http://your-proxy:port
```

### 直接部署方式

编辑 `main.py` 顶部：
```python
os.environ["http_proxy"] = "http://your-proxy:port"
os.environ["https_proxy"] = "http://your-proxy:port"
```

---

## 📊 监控与维护

### 日志查看

```bash
# Docker 方式
docker-compose -f ./docker/docker-compose.yml logs -f --tail=100

# 直接部署
tail -f /opt/stock-analyzer/logs/stock_analysis_*.log
```

### 健康检查

```bash
# 检查进程
ps aux | grep main.py

# 检查最近的报告
ls -la /opt/stock-analyzer/reports/
```

### 定期维护

```bash
# 清理旧日志（保留7天）
find /opt/stock-analyzer/logs -mtime +7 -delete

# 清理旧报告（保留30天）
find /opt/stock-analyzer/reports -mtime +30 -delete
```

---

## ❓ 常见问题

### 1. Docker 构建失败

```bash
# 清理缓存重新构建
docker-compose -f ./docker/docker-compose.yml build --no-cache
```

### 2. API 访问超时

检查代理配置，确保服务器能访问 Gemini API。

### 3. 数据库锁定

```bash
# 停止服务后删除 lock 文件
rm /opt/stock-analyzer/data/*.lock
```

### 4. 内存不足

调整 `docker-compose.yml` 中的内存限制：
```yaml
deploy:
  resources:
    limits:
      memory: 1G
```

---

## 🔄 快速迁移

从一台服务器迁移到另一台：

```bash
# 源服务器：打包
cd /opt/stock-analyzer
tar -czvf stock-analyzer-backup.tar.gz .env data/ logs/ reports/

# 目标服务器：部署
mkdir -p /opt/stock-analyzer
cd /opt/stock-analyzer
git clone <your-repo-url> .
tar -xzvf stock-analyzer-backup.tar.gz
docker-compose -f ./docker/docker-compose.yml up -d
```

---

## ☁️ 方案四：GitHub Actions 部署（免服务器）

**最简单的方案！** 无需服务器，利用 GitHub 免费计算资源。

### 优势
- ✅ **完全免费**（每月 2000 分钟）
- ✅ **无需服务器**
- ✅ **自动定时执行**
- ✅ **零维护成本**

### 限制
- ⚠️ 无状态（每次运行是新环境）
- ⚠️ 定时可能有几分钟延迟
- ⚠️ 无法提供 HTTP API

### 部署步骤

#### 1. 创建 GitHub 仓库

```bash
# 初始化 git（如果还没有）
cd /path/to/daily_stock_analysis
git init
git add .
git commit -m "Initial commit"

# 创建 GitHub 仓库并推送
# 在 GitHub 网页上创建新仓库后：
git remote add origin https://github.com/你的用户名/daily_stock_analysis.git
git branch -M main
git push -u origin main
```

#### 2. 配置 Secrets（重要！）

打开仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

添加以下 Secrets：

| Secret 名称 | 说明 | 必填 |
|------------|------|------|
| `GEMINI_API_KEY` | Gemini AI API Key | ✅ |
| `WECHAT_WEBHOOK_URL` | 企业微信机器人 Webhook | 可选* |
| `FEISHU_WEBHOOK_URL` | 飞书机器人 Webhook | 可选* |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 可选* |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选* |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID | 可选* |
| `EMAIL_SENDER` | 发件人邮箱 | 可选* |
| `EMAIL_PASSWORD` | 邮箱授权码 | 可选* |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey | 可选* |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（多个逗号分隔） | 可选* |
| `STOCK_LIST` | 自选股列表，如 `600519,300750` | ✅ |
| `TAVILY_API_KEYS` | Tavily 搜索 API Key | 推荐 |
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search | 可选 |
| `SERPAPI_API_KEYS` | SerpAPI Key | 可选 |
| `SEARXNG_BASE_URLS` | SearXNG 自建实例（无配额兜底，需在 settings.yml 启用 format: json） | 可选 |
| `TUSHARE_TOKEN` | Tushare Token | 可选 |
| `GEMINI_MODEL` | 模型名称（默认 gemini-2.0-flash） | 可选 |

> *注：通知渠道至少配置一个，支持多渠道同时推送

#### 3. 验证 Workflow 文件

确保 `.github/workflows/daily_analysis.yml` 文件存在且已提交：

```bash
git add .github/workflows/daily_analysis.yml
git commit -m "Add GitHub Actions workflow"
git push
```

#### 4. 手动测试运行

1. 打开仓库页面 → **Actions** 标签
2. 选择 **"每日股票分析"** workflow
3. 点击 **"Run workflow"** 按钮
4. 选择运行模式：
   - `full` - 完整分析（股票+大盘）
   - `market-only` - 仅大盘复盘
   - `stocks-only` - 仅股票分析
5. 点击绿色 **"Run workflow"** 按钮

#### 5. 查看执行日志

- Actions 页面可以看到运行历史
- 点击具体的运行记录查看详细日志
- 分析报告会作为 Artifact 保存 30 天

### 定时说明

默认配置：**周一到周五，北京时间 18:00** 自动执行

修改时间：编辑 `.github/workflows/daily_analysis.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '0 10 * * 1-5'  # UTC 时间，+8 = 北京时间
```

常用 cron 示例：
| 表达式 | 说明 |
|--------|------|
| `'0 10 * * 1-5'` | 周一到周五 18:00（北京时间） |
| `'30 7 * * 1-5'` | 周一到周五 15:30（北京时间） |
| `'0 10 * * *'` | 每天 18:00（北京时间） |
| `'0 2 * * 1-5'` | 周一到周五 10:00（北京时间） |

### 修改自选股

方法一：修改仓库 Secret `STOCK_LIST`

方法二：直接修改代码后推送：
```bash
# 修改 .env.example 或在代码中设置默认值
git commit -am "Update stock list"
git push
```

### 常见问题

**Q: 为什么定时任务没有执行？**
A: GitHub Actions 定时任务可能有 5-15 分钟延迟，且仅在仓库有活动时才触发。长时间无 commit 可能导致 workflow 被禁用。

**Q: 如何查看历史报告？**
A: Actions → 选择运行记录 → Artifacts → 下载 `analysis-reports-xxx`

**Q: 免费额度够用吗？**
A: 每次运行约 2-5 分钟，一个月 22 个工作日 = 44-110 分钟，远低于 2000 分钟限制。

---

**祝部署顺利！🎉**
