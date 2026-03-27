# -*- coding: utf-8 -*-
"""Smoke tests for the standalone Galaxy bridge."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bridge.galaxy.config import BridgeSettings  # noqa: E402
from bridge.galaxy.sdk_client import GalaxySdkClient  # noqa: E402


def sdk_mode() -> int:
    settings = BridgeSettings.from_env()
    client = GalaxySdkClient(settings)
    ready, error = client.probe()
    print(json.dumps({"sdk_ready": ready, "sdk_error": error}, ensure_ascii=False, indent=2))
    if not ready:
        return 1
    print(json.dumps(client.get_stock_basic("600519"), ensure_ascii=False, indent=2))
    return 0


def http_mode(base_url: str, token: str) -> int:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    health = requests.get(base_url.rstrip("/") + "/health", headers=headers, timeout=10)
    print("/health =>", health.status_code, health.text[:300])
    stock = requests.get(
        base_url.rstrip("/") + "/api/v1/galaxy/stock-basic",
        params={"code": "600519"},
        headers=headers,
        timeout=10,
    )
    print("/stock-basic =>", stock.status_code, stock.text[:500])
    return 0 if health.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test Galaxy bridge")
    parser.add_argument("--mode", choices=["sdk", "http"], default="sdk")
    parser.add_argument("--base-url", default=os.getenv("GALAXY_BRIDGE_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--token", default=os.getenv("GALAXY_BRIDGE_TOKEN", ""))
    args = parser.parse_args()

    if args.mode == "http":
        return http_mode(args.base_url, args.token)
    return sdk_mode()


if __name__ == "__main__":
    raise SystemExit(main())

