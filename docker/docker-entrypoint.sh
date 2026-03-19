#!/bin/sh
set -eu

codex_home_root="${CODEX_HOME:-/codex-home}"
codex_auth_mode="${CODEX_AUTH_MODE:-shared}"

case "$codex_auth_mode" in
  shared)
    effective_codex_home="$codex_home_root"
    ;;
  account|api)
    effective_codex_home="$codex_home_root/$codex_auth_mode"
    ;;
  *)
    echo "[docker-entrypoint] Unknown CODEX_AUTH_MODE=$codex_auth_mode, fallback to shared" >&2
    effective_codex_home="$codex_home_root"
    ;;
esac

mkdir -p "$effective_codex_home"
export CODEX_HOME="$effective_codex_home"

if [ "${codex_auth_mode}" = "api" ] && [ ! -f "$CODEX_HOME/auth.json" ]; then
  codex_api_key="${CODEX_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
  if [ -n "$codex_api_key" ] && command -v codex >/dev/null 2>&1; then
    echo "[docker-entrypoint] Initializing Codex API-key login under $CODEX_HOME" >&2
    printf '%s' "$codex_api_key" | codex login --with-api-key >/dev/null
  fi
fi

exec "$@"
