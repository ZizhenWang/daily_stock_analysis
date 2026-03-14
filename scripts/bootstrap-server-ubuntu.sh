#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

INSTALL_CODEX="${INSTALL_CODEX:-true}"
PYTHON_PACKAGE="${PYTHON_PACKAGE:-python3.11}"
PYTHON_VENV_PACKAGE="${PYTHON_VENV_PACKAGE:-python3.11-venv}"
NODE_SETUP="${NODE_SETUP:-true}"
NODE_MAJOR="${NODE_MAJOR:-22}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[bootstrap] Please run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "[bootstrap] App directory not found: ${APP_DIR}" >&2
  exit 1
fi

echo "[bootstrap] Updating apt package index"
apt-get update

echo "[bootstrap] Installing base system packages"
apt-get install -y \
  ca-certificates \
  curl \
  git \
  build-essential \
  "${PYTHON_PACKAGE}" \
  "${PYTHON_VENV_PACKAGE}" \
  python3-pip

if [[ "${NODE_SETUP}" == "true" ]]; then
  echo "[bootstrap] Installing Node.js ${NODE_MAJOR}.x"
  install -d -m 0755 /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/nodesource.gpg ]]; then
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  fi
  echo \
    "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
    > /etc/apt/sources.list.d/nodesource.list
  apt-get update
  apt-get install -y nodejs
fi

if [[ "${INSTALL_CODEX}" == "true" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[bootstrap] npm is required to install Codex CLI" >&2
    exit 1
  fi
  echo "[bootstrap] Installing Codex CLI globally via npm"
  npm install -g @openai/codex
fi

echo "[bootstrap] Preparing app directories"
mkdir -p "${APP_DIR}/data" "${APP_DIR}/logs" "${APP_DIR}/reports"

echo "[bootstrap] Bootstrap completed"
echo "[bootstrap] Next steps:"
echo "  1. cd ${APP_DIR}"
echo "  2. cp .env.example .env"
echo "  3. Edit .env and set STOCK_LIST / LLM_BACKEND / notification configs"
echo "  4. Run: codex login"
echo "  5. Run: ./scripts/start-server-ubuntu.sh --llm-smoke-test"
