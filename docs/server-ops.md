# 服务器运维手册

本文档记录当前服务器部署方式下，日常运维最常用的命令和检查项。

当前假设：
- 运行用户：`stock`
- 项目目录：`/opt/stock-analyzer/daily_stock_analysis`
- Web/API 服务：`stock-analyzer.service`
- 定时调度服务：`stock-analyzer-schedule.service`
- LLM 后端：`LLM_BACKEND=codex`
- 服务器时区：`Asia/Shanghai`

## 服务职责

### `stock-analyzer.service`

用途：
- 常驻 Web/API 服务
- 默认监听 `0.0.0.0:18000`
- 适合访问 `/docs`、Web/API、后续 Agent 对话入口

对应启动命令：

```bash
/opt/stock-analyzer/daily_stock_analysis/scripts/start-server-ubuntu.sh
```

### `stock-analyzer-schedule.service`

用途：
- 常驻定时调度器
- 按 `.env` 中的 `SCHEDULE_TIME` 每天执行一次分析
- 当前建议使用 `--no-run-immediately`，避免服务启动时立刻跑一轮

对应启动命令：

```bash
/opt/stock-analyzer/daily_stock_analysis/scripts/start-server-ubuntu.sh --schedule --no-run-immediately
```

## 最常用命令

### 查看服务状态

```bash
sudo systemctl status stock-analyzer
sudo systemctl status stock-analyzer-schedule
```

### 启动 / 停止 / 重启服务

```bash
sudo systemctl start stock-analyzer
sudo systemctl stop stock-analyzer
sudo systemctl restart stock-analyzer

sudo systemctl start stock-analyzer-schedule
sudo systemctl stop stock-analyzer-schedule
sudo systemctl restart stock-analyzer-schedule
```

### 查看实时日志

```bash
sudo journalctl -u stock-analyzer -f
sudo journalctl -u stock-analyzer-schedule -f
```

### 查看是否开机自启

```bash
sudo systemctl is-enabled stock-analyzer
sudo systemctl is-enabled stock-analyzer-schedule
```

### 查看是否正在运行

```bash
sudo systemctl is-active stock-analyzer
sudo systemctl is-active stock-analyzer-schedule
```

## 配置变更

项目配置文件：

```bash
/opt/stock-analyzer/daily_stock_analysis/.env
```

编辑方式：

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && vim .env'
```

### 改完 `.env` 之后怎么生效

如果只改了 Web/API 相关配置：

```bash
sudo systemctl restart stock-analyzer
```

如果只改了定时任务相关配置，例如 `SCHEDULE_TIME`：

```bash
sudo systemctl restart stock-analyzer-schedule
```

不确定时，两个都重启：

```bash
sudo systemctl restart stock-analyzer
sudo systemctl restart stock-analyzer-schedule
```

## 定时任务说明

当前定时任务按服务器本地时间执行。

查看服务器时间：

```bash
date '+%F %T %Z %z'
timedatectl
```

当前服务器时区应为：

```text
Asia/Shanghai
```

定时任务时间来自 `.env`：

```env
SCHEDULE_TIME=08:00
```

由于 `stock-analyzer-schedule.service` 使用了 `--no-run-immediately`：
- 服务启动时不会立刻执行
- 会等待到下一次 `SCHEDULE_TIME` 再执行

查看定时服务是否已经正确等待下一次执行：

```bash
sudo journalctl -u stock-analyzer-schedule -n 50
```

如果日志里出现类似：

```text
模式: 定时任务
每日执行时间: 08:00
启动时立即执行: False
下次执行时间: 2026-03-15 08:00:00
```

说明调度器工作正常。

## Web/API 检查

当前 Web/API 服务默认监听端口：

```text
18000
```

本机检查：

```bash
curl http://127.0.0.1:18000/docs
sudo ss -ltnp | grep 18000
```

如果要从外网访问，还需要：
- 服务器防火墙放行 `18000/tcp`
- 云厂商安全组放行 `18000/tcp`

## Codex 运行时

当前服务器使用 `stock` 用户的 Codex 登录态。

登录命令：

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && codex login --device-auth'
```

探活命令：

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && ./scripts/start-server-ubuntu.sh --llm-smoke-test'
```

如果探活成功，日志中应包含：

```text
Codex 探活成功
后端: codex
模型: codex:default
```

## Git 与代码更新

建议统一使用 `stock` 用户做 Git 操作，避免与 `root` 混用导致权限问题。

更新代码：

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && git pull'
```

更新后建议：

```bash
sudo systemctl restart stock-analyzer
sudo systemctl restart stock-analyzer-schedule
```

如果更新后出现目录权限问题，可修复属主：

```bash
sudo chown -R stock:stock /opt/stock-analyzer/daily_stock_analysis
```

## 手动触发分析

### 手动跑一只股票

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && ./scripts/start-server-ubuntu.sh --stocks AAPL --no-market-review --force-run'
```

### 手动跑完整分析

```bash
sudo -u stock -H bash -lc 'cd /opt/stock-analyzer/daily_stock_analysis && ./scripts/start-server-ubuntu.sh --force-run'
```

默认情况下，如果 `.env` 已配置飞书等通知渠道，就会发送推送。

## 常见问题

### 1. `Unit stock-analyzer.service could not be found`

说明 `systemd` 服务文件还没有安装到：

```bash
/etc/systemd/system/
```

需要重新执行：

```bash
sudo cp /tmp/stock-analyzer.service /etc/systemd/system/stock-analyzer.service
sudo systemctl daemon-reload
```

### 2. `Permission denied: logs/...`

通常是项目目录被 `root` 写过，`stock` 无法继续写日志。

修复：

```bash
sudo chown -R stock:stock /opt/stock-analyzer/daily_stock_analysis
```

### 3. 飞书没有收到通知

先检查服务器 `.env` 是否真的配置了：

```bash
FEISHU_WEBHOOK_URL=...
```

然后重启服务或重新手动执行分析。

### 4. 定时任务没有立即执行

这是正常的，因为调度服务使用了：

```bash
--no-run-immediately
```

它只会等到下一个 `SCHEDULE_TIME` 再运行。

## 推荐巡检顺序

```bash
sudo systemctl status stock-analyzer
sudo systemctl status stock-analyzer-schedule
sudo journalctl -u stock-analyzer -n 50
sudo journalctl -u stock-analyzer-schedule -n 50
date '+%F %T %Z %z'
```
