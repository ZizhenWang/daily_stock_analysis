# -*- coding: utf-8 -*-
"""
Galaxy bridge client.

当前主应用不再直接 import AmazingData / tgw，而是通过 HTTP bridge
从兼容环境（如阿里云 Ubuntu）获取银河证券数据。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

from .base import DataFetchError, DataSourceUnavailableError


logger = logging.getLogger(__name__)


class GalaxyBridgeClient:
    """HTTP client for Galaxy bridge service."""

    def __init__(
        self,
        base_url: str,
        *,
        token: Optional[str] = None,
        timeout_seconds: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = (token or "").strip()
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.session = requests.Session()

    @classmethod
    def from_env(cls) -> "GalaxyBridgeClient":
        enabled = os.getenv("GALAXY_ENABLED", "false").lower() == "true"
        if not enabled:
            raise DataSourceUnavailableError("Galaxy bridge 未启用，请设置 GALAXY_ENABLED=true")
        base_url = (os.getenv("GALAXY_BRIDGE_URL", "") or "").strip()
        if not base_url:
            raise DataSourceUnavailableError("Galaxy bridge 配置不完整: GALAXY_BRIDGE_URL")
        token = os.getenv("GALAXY_BRIDGE_TOKEN")
        timeout_seconds = int((os.getenv("GALAXY_BRIDGE_TIMEOUT_SECONDS", "10") or "10").strip() or "10")
        return cls(base_url, token=token, timeout_seconds=timeout_seconds)

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _unwrap(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            for key in ("data", "result", "payload"):
                if key in payload:
                    return payload[key]
        return payload

    def request_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(
                url,
                params=params or {},
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DataFetchError(f"Galaxy bridge 请求失败: {url} ({type(exc).__name__})") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataFetchError(f"Galaxy bridge 返回非 JSON: {url}") from exc

        if isinstance(payload, dict) and str(payload.get("status", "")).lower() in {"error", "failed"}:
            message = payload.get("message") or payload.get("error") or "unknown error"
            raise DataFetchError(f"Galaxy bridge 返回错误: {message}")
        return self._unwrap(payload)

    def get_kline(self, stock_code: str, start_date: str, end_date: str) -> Any:
        return self.request_json(
            "/api/v1/galaxy/kline",
            params={
                "code": stock_code,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    def get_stock_basic(self, stock_code: str) -> Any:
        return self.request_json(
            "/api/v1/galaxy/stock-basic",
            params={"code": stock_code},
        )

    def get_fundamental_bundle(self, stock_code: str) -> Any:
        return self.request_json(
            "/api/v1/galaxy/fundamental",
            params={"code": stock_code},
        )

    def healthcheck(self) -> Any:
        return self.request_json("/health")
