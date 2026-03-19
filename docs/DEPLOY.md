# 🚀 部署指南

本文档介绍如何将 A股自选股智能分析系统部署到服务器。

如需部署完成后的日常运维命令速查，可参考 [服务器运维手册](server-ops.md)。

## 快速导航

- [群晖 NAS / Container Manager 部署](#-群晖-nas--container-manager-部署)
- [阿里云 / Ubuntu：Docker Compose 部署](#-阿里云--ubuntu方案一docker-compose-部署推荐)
- [阿里云 / Ubuntu：直接部署](#️-阿里云--ubuntu方案二直接部署)
- [阿里云 / Ubuntu：Systemd 服务](#-阿里云--ubuntu方案三systemd-服务)
- [配置说明](#️-配置说明)
- [常见问题](#-常见问题)

---

## 🧰 群晖 NAS / Container Manager 部署

如果你当前的主场景是 **群晖 DS423+ / DSM + Container Manager**，建议优先看这一节。

推荐目录：

```text
/volume1/docker/stock/daily_stock_analysis
```

推荐目录结构：

```text
/volume1/docker/stock/
  daily_stock_analysis/
    .env
    codex-home/
    data/
    logs/
    reports/
```

说明：
- `data/`、`logs/`、`reports/` 为运行数据
- `codex-home/` 用于 Docker 容器持久化 `CODEX_HOME`
- 群晖环境下相对路径解析可能与标准 Linux 不完全一致，建议把 `codex-home/`、`data/`、`logs/`、`reports/` 都放在仓库目录下并确认挂载生效

### 1. 首次拉取代码

群晖宿主机通常未安装 `git`，推荐使用临时 Git 容器拉代码：

```bash
sudo docker run --rm -it \
  -v /volume1/docker/stock:/work \
  alpine/git \
  clone -b dev --single-branch https://github.com/ZizhenWang/daily_stock_analysis.git /work/daily_stock_analysis
```

确认当前分支：

```bash
sudo docker run --rm -it \
  -v /volume1/docker/stock/daily_stock_analysis:/repo \
  -w /repo \
  alpine/git \
  branch --show-current
```

### 2. 初始化 `.env`

```bash
cp /volume1/docker/stock/daily_stock_analysis/.env.example /volume1/docker/stock/daily_stock_analysis/.env
vi /volume1/docker/stock/daily_stock_analysis/.env
```

建议至少确认：

```env
WEBUI_HOST=0.0.0.0
WEBUI_PORT=8000
API_PORT=8000
WEBUI_AUTO_BUILD=false
ADMIN_AUTH_ENABLED=true

FEISHU_STREAM_ENABLED=true
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_WEBHOOK_URL=

LLM_BACKEND=codex
```

### 3. 准备运行目录

```bash
mkdir -p /volume1/docker/stock/daily_stock_analysis/codex-home
mkdir -p /volume1/docker/stock/daily_stock_analysis/data
mkdir -p /volume1/docker/stock/daily_stock_analysis/logs
mkdir -p /volume1/docker/stock/daily_stock_analysis/reports
```

### 4. 构建镜像

```bash
cd /volume1/docker/stock/daily_stock_analysis
sudo docker-compose -f ./docker/docker-compose.yml build --no-cache server analyzer
```

说明：
- 首次部署、修改了 `docker/Dockerfile` / `requirements.txt` / 前端依赖时，建议使用 `--no-cache`
- 日常只更新 Python 代码、Bot、API、文档时，通常不需要 `--no-cache`

### 5. Docker 内完成 Codex 登录

```bash
sudo docker-compose -f ./docker/docker-compose.yml run --rm server codex login --device-auth
```

说明：
- Docker / NAS 模式下，分析链路中的 `codex exec` 会优先复用挂载的 `CODEX_HOME`
- 因此 `codex-home/` 目录必须和 `docker-compose.yml` 的卷挂载保持一致，并且登录动作需要在同一套 compose 配置下完成
- 若使用 API key 模式，Codex CLI 官方支持 `codex login --with-api-key`；当前 Docker 入口会在 `CODEX_AUTH_MODE=api` 且存在 `CODEX_OPENAI_API_KEY`（未设置时回退 `OPENAI_API_KEY`）时自动完成一次 API 登录，并继续在每次调用前完整复用挂载的 `CODEX_HOME`
- 如需同时保留“账号登录”和“API key 登录”，可在 `.env` 中设置 `CODEX_AUTH_MODE=account|api|shared`：
  - `shared`：直接使用 `/codex-home`（默认，兼容旧部署）
  - `account`：使用 `/codex-home/account`
  - `api`：使用 `/codex-home/api`
- 这意味着 NAS 宿主机上的配置文件也应放在对应目录下，例如：
  - `/volume1/docker/stock/daily_stock_analysis/codex-home/account/config.toml`
  - `/volume1/docker/stock/daily_stock_analysis/codex-home/api/config.toml`
- 若 `--llm-smoke-test` 报错里包含 `Refusing to create helper binaries under temporary dir "/tmp"`，通常是较新 Codex CLI 不再接受 `/tmp` 下的临时 `CODEX_HOME`；当前仓库已改为在项目内持久化临时目录运行，无需额外处理，更新代码并重建容器即可
- 若 `/help` 正常、`/analyze` 或 `/a AAPL` 只返回“评分 50 / 未知 / 待补充”，优先检查 `codex-home/` 是否挂载正确，以及是否在当前容器环境中重新执行过 `codex login --device-auth`

验证容器内 `codex`：

```bash
sudo docker-compose -f ./docker/docker-compose.yml run --rm server sh -lc 'which codex && codex --version'
sudo docker-compose -f ./docker/docker-compose.yml run --rm server python main.py --llm-smoke-test
```

若当前要把 NAS 上的 `config.toml` 写到 API key 登录目录，可直接执行：

```bash
mkdir -p /volume1/docker/stock/daily_stock_analysis/codex-home/api
cat > /volume1/docker/stock/daily_stock_analysis/codex-home/api/config.toml <<'EOF'
model_provider = "OpenAI"
model = "gpt-5.4"
review_model = "gpt-5.4"
model_reasoning_effort = "xhigh"
disable_response_storage = true
network_access = "enabled"
windows_wsl_setup_acknowledged = true
model_context_window = 1000000
model_auto_compact_token_limit = 900000

[model_providers.OpenAI]
name = "OpenAI"
base_url = "https://cc.sub.258000.sbs"
wire_api = "responses"
requires_openai_auth = true
EOF
```

然后在 `.env` 中设置：

```env
CODEX_AUTH_MODE=api
CODEX_OPENAI_API_KEY=sk-...
```

如果要切回账号登录，则把 `CODEX_AUTH_MODE=account`，并在对应目录里执行一次：

```bash
sudo docker-compose -f ./docker/docker-compose.yml run --rm server codex login --device-auth
```

### 6. 启动服务

当前推荐保留两个容器：
- `server`：WebUI + API + 飞书 Bot
- `analyzer`：定时任务调度器

启动：

```bash
sudo docker-compose -f ./docker/docker-compose.yml up -d server analyzer
```

查看状态：

```bash
sudo docker-compose -f ./docker/docker-compose.yml ps
```

查看日志：

```bash
sudo docker-compose -f ./docker/docker-compose.yml logs -f server
sudo docker-compose -f ./docker/docker-compose.yml logs -f analyzer
```

### 7. 功能验证

WebUI / API：

```bash
curl -I http://127.0.0.1:8000/docs
```

局域网访问：

```text
http://NAS内网IP:8000
```

飞书 Bot：
- `/help`
- `/market us`
- `/watchlist list`

### 8. 更新代码

日常更新（推荐，不带 `--no-cache`）：

```bash
sudo docker run --rm -it \
  -v /volume1/docker/stock/daily_stock_analysis:/repo \
  -w /repo \
  alpine/git \
  pull

cd /volume1/docker/stock/daily_stock_analysis
sudo docker-compose -f ./docker/docker-compose.yml build server analyzer
sudo docker-compose -f ./docker/docker-compose.yml up -d server analyzer
```

只改 `.env` 或少量运行参数时，可直接重启：

```bash
cd /volume1/docker/stock/daily_stock_analysis
sudo docker-compose -f ./docker/docker-compose.yml restart server analyzer
```

只有在以下情况才建议强制重建：
- 修改了 [docker/Dockerfile](/Users/zizhen/Documents/repos/codex/daily_stock_analysis/docker/Dockerfile)
- 修改了 `requirements.txt`
- 修改了 [apps/dsa-web/package.json](/Users/zizhen/Documents/repos/codex/daily_stock_analysis/apps/dsa-web/package.json) 或 [apps/dsa-web/package-lock.json](/Users/zizhen/Documents/repos/codex/daily_stock_analysis/apps/dsa-web/package-lock.json)
- 怀疑镜像缓存损坏或 `codex` / apt 依赖安装异常

强制重建命令：

```bash
cd /volume1/docker/stock/daily_stock_analysis
sudo docker-compose -f ./docker/docker-compose.yml build --no-cache server analyzer
sudo docker-compose -f ./docker/docker-compose.yml up -d server analyzer
```

### 9. 群晖常见问题

`docker: Got permission denied while trying to connect to the Docker daemon socket`

```bash
sudo docker-compose ...
sudo docker run ...
```

`docker compose` 不可用，但 `docker-compose` 可用：

```bash
sudo docker-compose -f ./docker/docker-compose.yml up -d
```

`exec: "codex": executable file not found in $PATH`

```bash
sudo docker run --rm -it \
  -v /volume1/docker/stock/daily_stock_analysis:/repo \
  -w /repo \
  alpine/git \
  pull

cd /volume1/docker/stock/daily_stock_analysis
sudo docker-compose -f ./docker/docker-compose.yml build --no-cache server analyzer
```

`Bind mount failed: ... logs does not exists`

```bash
mkdir -p /volume1/docker/stock/daily_stock_analysis/data
mkdir -p /volume1/docker/stock/daily_stock_analysis/logs
mkdir -p /volume1/docker/stock/daily_stock_analysis/reports
mkdir -p /volume1/docker/stock/daily_stock_analysis/codex-home
```

WebUI 添加股票偶发报错：
- 当前仓库已启用 SQLite `WAL + busy_timeout`
- 若仍偶发命中 `db_locked`，建议稍后重试并查看：

```bash
sudo docker-compose -f ./docker/docker-compose.yml logs -f server
```

飞书 `/analyze` 能返回，但内容大多是“待补充 / 未知”：
- 先检查容器内 `codex` 是否可用：

```bash
sudo docker-compose -f ./docker/docker-compose.yml run --rm server sh -lc 'which codex && codex --version'
sudo docker-compose -f ./docker/docker-compose.yml run --rm server python main.py --llm-smoke-test
```

- 再盯住服务日志后重新发一次 `/a AAPL`：

```bash
sudo docker-compose -f ./docker/docker-compose.yml logs -f server
```

- 如果日志里出现 `Codex CLI 未安装`、`Codex 调用失败`、`Codex 返回了空响应`、`LLM完整性` 等关键字，优先检查：
  - `codex-home/` 是否在仓库目录下并成功挂载
  - 是否用当前 compose 环境执行过 `codex login --device-auth`
  - `.env` 中 `LLM_BACKEND=codex` 是否和当前部署一致

## 📋 部署方案对比

| 方案 | 优点 | 缺点 | 推荐场景 |
|------|------|------|----------|
| **Docker Compose** ⭐ | 一键部署、环境隔离、易迁移、易升级 | 需要安装 Docker | **推荐**：大多数场景 |
| **直接部署** | 简单直接、无额外依赖 | 环境依赖、迁移麻烦 | 临时测试 |
| **Systemd 服务** | 系统级管理、开机自启 | 配置繁琐 | 长期稳定运行 |
| **Supervisor** | 进程管理、自动重启 | 需要额外安装 | 多进程管理 |

**结论：推荐使用 Docker Compose，迁移最快最方便！**

---

## 🐳 阿里云 / Ubuntu：方案一：Docker Compose 部署（推荐）

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

## 🖥️ 阿里云 / Ubuntu：方案二：直接部署

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

## 🔧 阿里云 / Ubuntu：方案三：Systemd 服务

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

如果你希望单任务模式每天早上 08:00 运行，修改 `.env`：

```env
SCHEDULE_TIME=08:00
```

注意：
- `stock-analyzer-schedule.service` 使用 `--no-run-immediately`，所以服务启动时不会先跑一轮
- 它只会等到 `.env` 中的 `SCHEDULE_TIME` 到点再执行

如果你希望同一个定时服务内部支持多个计划任务，例如“08:00 美股复盘、18:00 A股复盘、18:10 默认日报”，推荐直接在 `.env` 中设置：

```env
SCHEDULE_ENABLED=true
SCHEDULE_RUN_IMMEDIATELY=false
SCHEDULE_JOBS_JSON=[{"name":"us_market_review","time":"08:00","job_type":"market_review","market_review_region":"us","force_run":true},{"name":"cn_market_review","time":"18:00","job_type":"market_review","market_review_region":"cn"},{"name":"default_batch","time":"18:10","job_type":"full_analysis"}]
```

说明：
- 配置 `SCHEDULE_JOBS_JSON` 后，调度服务将优先使用多任务模式，不再只看 `SCHEDULE_TIME`
- Web / API / 飞书 Bot 仍由 `stock-analyzer.service` 承担，不在定时服务内处理

---

## ⚙️ 配置说明

### 必须配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `STOCK_LIST` | 兼容导入用旧版自选股列表 | 首次启动时若数据库 watchlist 为空，会自动导入 |
| `LLM_BACKEND` | LLM 后端，`codex` 或 `native` | `.env` |
| `FEISHU_WEBHOOK_URL` / 其他通知渠道 | 推送结果到飞书/Telegram/企微等 | 各平台机器人 |

> 如果你使用 `LLM_BACKEND=codex`，服务器上还需要可用的 `codex` CLI 和登录态，不要求在 `.env` 中配置 `OPENAI_API_KEY/GEMINI_API_KEY`。

> Watchlist 升级说明：
> - 首次部署或升级到本版本后，程序会在启动时检查数据库中的 watchlist；
> - 若 watchlist 为空且 `.env` 中配置了 `STOCK_LIST`，会自动导入；
> - 导入完成后，默认分析对象以数据库 watchlist 为主，WebUI 可直接进行新增/编辑/删除/启停管理。

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

对于 Docker / NAS 模式，不建议把交互式 `codex login` 放进容器启动流程。仓库内置 Dockerfile 已在运行镜像中安装 `codex` CLI，并在 `docker/docker-compose.yml` 中默认挂载 `../codex-home:/codex-home` 作为持久化登录态目录。推荐先单独执行一次：

```bash
docker-compose -f ./docker/docker-compose.yml run --rm server codex login --device-auth
```

然后再启动正式服务：

```bash
docker-compose -f ./docker/docker-compose.yml up -d server analyzer
```

如需验证容器内 Codex 是否可用：

```bash
docker-compose -f ./docker/docker-compose.yml exec server sh -lc 'which codex && codex --version'
docker-compose -f ./docker/docker-compose.yml exec server python main.py --llm-smoke-test
```

### `native` 模式必须配置项

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `GEMINI_API_KEY` / `OPENAI_API_KEY` 等 | AI 分析必需 | 各模型平台 |
| `STOCK_LIST` | 兼容导入用旧版自选股列表 | 数据库 watchlist 首次导入来源 |
| `WECHAT_WEBHOOK_URL` | 微信推送 | 企业微信群机器人 |

### 可选配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `SCHEDULE_ENABLED` | `false` | 是否启用定时任务 |
| `SCHEDULE_TIME` | `18:00` | 单任务模式下的每日执行时间 |
| `SCHEDULE_JOBS_JSON` | - | 多任务调度 JSON 数组，支持不同时间跑不同任务 |
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
| `STOCK_LIST` | 兼容导入用旧版自选股列表，如 `600519,300750` | ✅ |
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
