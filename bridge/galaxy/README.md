# Galaxy Bridge

这个目录用于部署一个独立的 `Galaxy bridge` 服务，让 NAS 主框架通过 HTTP 访问银河证券星耀数智 / AmazingData，而不是在 NAS 主容器里直接加载 `AmazingData` / `tgw`。

## 目录结构

- `app.py`
  - FastAPI 入口，提供 `health`、`kline`、`stock-basic`、`fundamental`
- `sdk_client.py`
  - AmazingData SDK 封装，负责登录与 best-effort 方法调用
- `config.py`
  - 读取 bridge 环境变量
- `schemas.py`
  - 返回结构与辅助响应
- `requirements.txt`
  - bridge 自身依赖
- `.env.example`
  - bridge 环境变量示例
- `scripts/smoke_test.py`
  - SDK 模式 / HTTP 模式自检脚本
- `systemd/galaxy-bridge.service`
  - Ubuntu 上的 systemd 示例

## 前置条件

1. 目标机器可以正常导入 `tgw` 与 `AmazingData`
2. 目标机器可访问银河证券提供的 SDK 地址与端口
3. 已将本仓库代码同步到目标机器

## 安装

```bash
cd /opt/daily_stock_analysis
python3 -m venv .venv-galaxy-bridge
source .venv-galaxy-bridge/bin/activate
pip install -r bridge/galaxy/requirements.txt
pip install /path/to/tgw-*.whl /path/to/AmazingData-*.whl
cp bridge/galaxy/.env.example bridge/galaxy/.env
```

然后编辑 `bridge/galaxy/.env`：

```env
GALAXY_HOST=券商提供的 host
GALAXY_PORT=券商提供的 port
GALAXY_USERNAME=账号
GALAXY_PASSWORD=密码
GALAXY_LOCAL_PATH=/tmp/galaxy-bridge

GALAXY_BRIDGE_HOST=0.0.0.0
GALAXY_BRIDGE_PORT=8080
GALAXY_BRIDGE_TOKEN=请填一个随机 token
GALAXY_BRIDGE_LOG_LEVEL=info
GALAXY_BRIDGE_RELOAD=false
```

## 最小验证

先验证 SDK：

```bash
source .venv-galaxy-bridge/bin/activate
python bridge/galaxy/scripts/smoke_test.py --mode sdk
```

再启动服务：

```bash
source .venv-galaxy-bridge/bin/activate
set -a
source bridge/galaxy/.env
set +a
uvicorn bridge.galaxy.app:app --host "$GALAXY_BRIDGE_HOST" --port "$GALAXY_BRIDGE_PORT"
```

HTTP 自检：

```bash
curl http://127.0.0.1:8080/health
curl -H "Authorization: Bearer $GALAXY_BRIDGE_TOKEN" \
  "http://127.0.0.1:8080/api/v1/galaxy/stock-basic?code=600519"
```

## 暴露的接口

- `GET /health`
- `GET /api/v1/galaxy/kline?code=600519&start_date=2026-01-01&end_date=2026-03-27`
- `GET /api/v1/galaxy/stock-basic?code=600519`
- `GET /api/v1/galaxy/fundamental?code=600519`

bridge 默认使用 `Bearer` token 鉴权；如果 `GALAXY_BRIDGE_TOKEN` 留空，则不启用鉴权。

`GALAXY_LOCAL_PATH` 用于部分 AmazingData 类要求的本地缓存/工作目录。若不确定，保留默认 `/tmp/galaxy-bridge` 即可。

## 返回格式

### `/health`

```json
{
  "status": "ok",
  "service": "galaxy-bridge",
  "sdk_ready": true,
  "sdk_error": null
}
```

### `/api/v1/galaxy/kline`

```json
{
  "status": "ok",
  "data": [
    {
      "TRADE_DATE": "2026-03-27",
      "OPEN": 123.4,
      "HIGH": 125.0,
      "LOW": 122.8,
      "CLOSE": 124.6,
      "VOLUME": 123456,
      "AMOUNT": 987654321,
      "PCT_CHG": 1.23
    }
  ]
}
```

### `/api/v1/galaxy/stock-basic`

```json
{
  "status": "ok",
  "data": {
    "code": "600519",
    "name": "贵州茅台",
    "board": "上证主板",
    "belong_boards": [
      {
        "name": "白酒"
      }
    ],
    "raw": {}
  }
}
```

### `/api/v1/galaxy/fundamental`

```json
{
  "status": "partial",
  "data": {
    "status": "partial",
    "growth": {},
    "earnings": {},
    "institution": {},
    "source_chain": [
      "galaxy_bridge:get_income"
    ],
    "errors": []
  }
}
```

## systemd 部署

1. 按需修改 `bridge/galaxy/systemd/galaxy-bridge.service`
2. 安装到系统目录：

```bash
sudo cp bridge/galaxy/systemd/galaxy-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now galaxy-bridge
sudo systemctl status galaxy-bridge
```

## 与 NAS 主框架对接

NAS 上的 `.env`：

```env
GALAXY_ENABLED=true
GALAXY_BRIDGE_URL=https://你的阿里云域名或IP
GALAXY_BRIDGE_TOKEN=与 bridge 一致的 token
GALAXY_BRIDGE_TIMEOUT_SECONDS=10
GALAXY_HISTORY_ENABLED=true
GALAXY_PRIORITY=0
```

然后重启 NAS 主服务即可。
