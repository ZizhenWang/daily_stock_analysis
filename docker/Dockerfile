# ===================================
# A股自选股智能分析系统 - Docker 镜像
# ===================================
# 多阶段构建：前端打包 + 后端运行

ARG PYTHON_RUNTIME_IMAGE=registry.access.redhat.com/ubi9/python-311:latest

FROM node:20-slim AS web-builder

WORKDIR /app/apps/dsa-web

COPY apps/dsa-web/package.json apps/dsa-web/package-lock.json ./
RUN npm ci

COPY apps/dsa-web/ ./
RUN npm run build

FROM ${PYTHON_RUNTIME_IMAGE}

# 设置工作目录
WORKDIR /app

# UBI Python 镜像默认使用非 root 用户；切到 root 以便安装系统包、设置时区和创建运行目录。
USER 0

# 设置时区为上海
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖（wkhtmltopdf 含 wkhtmltoimage，用于 Markdown 转图片 Issue #289）
# 运行阶段额外安装 nodejs/npm，以便容器内可用 Codex CLI。
# 兼容 Debian/Ubuntu（apt）与 RedHat/UBI（yum/microdnf/dnf）三类基础镜像。
RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            gcc \
            curl \
            nodejs \
            npm \
            util-linux \
            wkhtmltopdf \
            fontconfig \
            libjpeg62-turbo \
            libxrender1 \
            libxext6; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v yum >/dev/null 2>&1; then \
        yum install -y \
            gcc \
            gcc-c++ \
            make \
            util-linux \
            fontconfig \
            libjpeg-turbo \
            libXrender \
            libXext \
            shadow-utils \
            findutils; \
        if ! command -v curl >/dev/null 2>&1; then yum install -y curl; fi; \
        yum install -y wkhtmltopdf || echo "wkhtmltopdf not available in current RPM repos; markdown-to-image may be limited"; \
        yum clean all; \
    elif command -v microdnf >/dev/null 2>&1; then \
        microdnf install -y \
            gcc \
            gcc-c++ \
            make \
            nodejs \
            npm \
            util-linux \
            fontconfig \
            libjpeg-turbo \
            libXrender \
            libXext \
            shadow-utils \
            findutils; \
        if ! command -v curl >/dev/null 2>&1; then microdnf install -y curl-minimal; fi; \
        microdnf install -y wkhtmltopdf || echo "wkhtmltopdf not available in current RPM repos; markdown-to-image may be limited"; \
        microdnf clean all; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y \
            gcc \
            gcc-c++ \
            make \
            nodejs \
            npm \
            util-linux \
            fontconfig \
            libjpeg-turbo \
            libXrender \
            libXext \
            shadow-utils \
            findutils; \
        if ! command -v curl >/dev/null 2>&1; then dnf install -y curl-minimal; fi; \
        dnf install -y wkhtmltopdf || echo "wkhtmltopdf not available in current RPM repos; markdown-to-image may be limited"; \
        dnf clean all; \
    else \
        echo "Unsupported package manager in runtime image"; \
        exit 1; \
    fi

# 安装 Codex CLI，供 LLM_BACKEND=codex 的容器部署使用。
RUN command -v npm >/dev/null 2>&1 || (echo "npm not found in runtime image"; exit 1)
RUN npm install -g @openai/codex

# 复制依赖文件
COPY requirements.txt .
COPY vendor/galaxy/ /tmp/vendor/galaxy/

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt \
    && if find /tmp/vendor/galaxy -maxdepth 1 -name '*.whl' -print -quit | grep -q .; then \
        pip install --no-cache-dir /tmp/vendor/galaxy/*.whl; \
    else \
        echo "No Galaxy wheels found under /tmp/vendor/galaxy, skipping AmazingData install"; \
    fi

# 复制应用代码
COPY *.py ./
COPY api/ ./api/
COPY data_provider/ ./data_provider/
COPY bot/ ./bot/
COPY patch/ ./patch/
COPY src/ ./src/
COPY strategies/ ./strategies/
COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=web-builder /app/static ./static/

# 创建数据目录
RUN mkdir -p /app/data /app/logs /app/reports
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1
ENV LOG_DIR=/app/logs
ENV DATABASE_PATH=/app/data/stock_analysis.db
ENV CODEX_HOME=/codex-home
# Web/API service
ENV WEBUI_HOST=0.0.0.0
ENV API_PORT=8000

# 暴露 API 端口
EXPOSE 8000

# 数据卷（持久化数据 + Codex 登录态）
VOLUME ["/app/data", "/app/logs", "/app/reports", "/codex-home"]

# 健康检查（FastAPI 模式）
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || curl -f http://localhost:8000/health \
    || python -c "import sys; sys.exit(0)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# 默认命令（可被覆盖）
CMD ["python", "main.py", "--schedule"]
