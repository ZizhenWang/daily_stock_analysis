#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV_DIR="${VENV_DIR:-${APP_DIR}/.server-venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WEBUI_AUTO_BUILD="${WEBUI_AUTO_BUILD:-false}"

pick_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "${PYTHON_BIN}"
    return 0
  fi

  local candidates=("python3.11" "python3.12" "python3.10" "python3")
  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  echo "No suitable Python interpreter found. Install python3.11+ first." >&2
  return 1
}

PYTHON_CMD="$(pick_python)"

cd "${APP_DIR}"

mkdir -p data logs reports

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[server-start] Creating isolated virtualenv at ${VENV_DIR}"
  "${PYTHON_CMD}" -m venv "${VENV_DIR}"
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"
REQ_STAMP="${VENV_DIR}/.requirements.sha256"

echo "[server-start] Bootstrapping Python environment with ${VENV_PYTHON}"
"${VENV_PYTHON}" -m pip install --upgrade pip setuptools wheel >/dev/null

REQ_HASH="$("${VENV_PYTHON}" - <<'PY'
from pathlib import Path
import hashlib
print(hashlib.sha256(Path("requirements.txt").read_bytes()).hexdigest())
PY
)"

if [[ ! -f "${REQ_STAMP}" ]] || [[ "$(<"${REQ_STAMP}")" != "${REQ_HASH}" ]]; then
  echo "[server-start] Installing Python dependencies into ${VENV_DIR}"
  "${VENV_PIP}" install -r requirements.txt
  printf '%s\n' "${REQ_HASH}" > "${REQ_STAMP}"
else
  echo "[server-start] Dependencies already up to date"
fi

if [[ ! -f ".env" ]]; then
  echo "[server-start] Warning: .env not found in ${APP_DIR}. The service may start without business configuration." >&2
fi

export PYTHONUNBUFFERED=1
export WEBUI_AUTO_BUILD

if [[ $# -gt 0 ]]; then
  CMD=("${VENV_PYTHON}" "main.py" "$@")
else
  CMD=("${VENV_PYTHON}" "main.py" "--serve-only" "--host" "${HOST}" "--port" "${PORT}")
fi

echo "[server-start] Starting service in isolated env"
echo "[server-start] Command: ${CMD[*]}"

exec "${CMD[@]}"
