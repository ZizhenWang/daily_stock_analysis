# -*- coding: utf-8 -*-
"""
===================================
GalaxyFetcher - 星耀数智 / AmazingData 数据源
===================================

定位：
1. Phase 1：A 股查询式历史日线 + 股票基础信息
2. Phase 3：财务/业绩数据由独立基本面适配层接入

注意：
- 仅覆盖 A 股 / 北交所查询式能力，不包含订阅式实时行情
- 主应用通过 HTTP bridge 获取数据，不再在 NAS 主容器内直接 import AmazingData / tgw
- bridge 服务建议部署在兼容银河 SDK 的独立环境（如阿里云 Ubuntu）
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import pandas as pd

from .base import (
    BaseFetcher,
    DataFetchError,
    DataSourceUnavailableError,
    STANDARD_COLUMNS,
    _is_hk_market,
    _is_us_market,
    is_bse_code,
    normalize_stock_code,
)
from .galaxy_bridge import GalaxyBridgeClient


logger = logging.getLogger(__name__)


class GalaxyFetcher(BaseFetcher):
    """星耀数智查询式 A 股数据源。"""

    name = "GalaxyFetcher"
    priority = int(os.getenv("GALAXY_PRIORITY", "0"))

    def __init__(self) -> None:
        self.enabled = os.getenv("GALAXY_ENABLED", "false").lower() == "true"
        self.bridge_url = (os.getenv("GALAXY_BRIDGE_URL", "") or "").strip()
        self.bridge_timeout_seconds = int((os.getenv("GALAXY_BRIDGE_TIMEOUT_SECONDS", "10") or "10").strip() or "10")
        self.history_enabled = os.getenv("GALAXY_HISTORY_ENABLED", "true").lower() == "true"
        self._stock_basic_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._client: Optional[GalaxyBridgeClient] = None

        if self.enabled:
            logger.info(
                "GalaxyFetcher 已启用（bridge 模式）: bridge_url=%s, timeout=%ss, priority=%s",
                self.bridge_url,
                self.bridge_timeout_seconds,
                self.priority,
            )
        else:
            logger.info("GalaxyFetcher 未启用（GALAXY_ENABLED=false）")

    @staticmethod
    def _supports_code(stock_code: str) -> bool:
        normalized = normalize_stock_code(stock_code)
        return normalized.isdigit() and len(normalized) == 6 and not _is_hk_market(normalized) and not _is_us_market(normalized)

    @staticmethod
    def _to_galaxy_code(stock_code: str) -> str:
        normalized = normalize_stock_code(stock_code).upper()
        if not normalized.isdigit() or len(normalized) != 6:
            return normalized
        if is_bse_code(normalized):
            return f"{normalized}.BJ"
        if normalized.startswith(("5", "6", "9", "11")):
            return f"{normalized}.SH"
        return f"{normalized}.SZ"

    def _ensure_available(self) -> None:
        if not self.enabled:
            raise DataSourceUnavailableError("GalaxyFetcher 未启用，请设置 GALAXY_ENABLED=true")
        if not self.bridge_url:
            raise DataSourceUnavailableError("GalaxyFetcher 配置不完整: GALAXY_BRIDGE_URL")

    def _get_client(self) -> GalaxyBridgeClient:
        self._ensure_available()
        if self._client is None:
            self._client = GalaxyBridgeClient.from_env()
        return self._client

    @staticmethod
    def _extract_frame(payload: Any, stock_code: str) -> Optional[pd.DataFrame]:
        if isinstance(payload, pd.DataFrame):
            return payload.copy()
        if isinstance(payload, pd.Series):
            return payload.to_frame().T
        if isinstance(payload, dict):
            normalized = normalize_stock_code(stock_code)
            variants = {
                stock_code,
                str(stock_code).upper(),
                normalized,
                GalaxyFetcher._to_galaxy_code(stock_code),
            }
            for key, value in payload.items():
                if str(key).upper() in {str(v).upper() for v in variants}:
                    return GalaxyFetcher._extract_frame(value, stock_code)
            if len(payload) == 1:
                return GalaxyFetcher._extract_frame(next(iter(payload.values())), stock_code)
        if isinstance(payload, list):
            try:
                df = pd.DataFrame(payload)
                return df if not df.empty else None
            except Exception:
                return None
        return None

    @staticmethod
    def _get_stock_basic_row(self, stock_code: str) -> Optional[Dict[str, Any]]:
        normalized = normalize_stock_code(stock_code)
        if normalized in self._stock_basic_cache:
            return self._stock_basic_cache[normalized]

        if not self._supports_code(normalized):
            self._stock_basic_cache[normalized] = None
            return None

        payload = self._get_client().get_stock_basic(normalized)
        if isinstance(payload, dict):
            row = payload
        elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
            row = payload[0]
        else:
            row = None
        self._stock_basic_cache[normalized] = row
        return row

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self._ensure_available()
        if not self.history_enabled:
            raise DataSourceUnavailableError("Galaxy 历史行情已禁用（GALAXY_HISTORY_ENABLED=false）")
        if not self._supports_code(stock_code):
            raise DataSourceUnavailableError("Galaxy 当前仅支持 A 股 / 北交所 6 位代码")

        payload = self._get_client().get_kline(stock_code, start_date, end_date)
        df = self._extract_frame(payload, stock_code)
        if df is None or df.empty:
            raise DataFetchError(f"Galaxy 未返回 {stock_code} 的历史 K 线数据")
        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df is None or df.empty:
            raise DataFetchError(f"Galaxy 未返回 {stock_code} 的有效 K 线数据")

        normalized = df.copy()
        rename_map = {
            "TRADE_DATE": "date",
            "trade_date": "date",
            "datetime": "date",
            "OPEN": "open",
            "HIGH": "high",
            "LOW": "low",
            "CLOSE": "close",
            "VOLUME": "volume",
            "AMOUNT": "amount",
            "TURNOVER": "amount",
            "PCT_CHG": "pct_chg",
            "CHANGE_RATE": "pct_chg",
            "change_rate": "pct_chg",
        }
        normalized = normalized.rename(columns=rename_map)

        if "date" not in normalized.columns and not isinstance(normalized.index, pd.RangeIndex):
            normalized = normalized.reset_index()
            if "date" not in normalized.columns:
                first_col = normalized.columns[0]
                normalized = normalized.rename(columns={first_col: "date"})

        if "pct_chg" not in normalized.columns and "close" in normalized.columns:
            prev_close = pd.to_numeric(normalized["close"], errors="coerce").shift(1)
            close = pd.to_numeric(normalized["close"], errors="coerce")
            normalized["pct_chg"] = ((close - prev_close) / prev_close.replace(0, pd.NA)) * 100

        for column in STANDARD_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA

        return normalized[STANDARD_COLUMNS].copy()

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        if not self.enabled or not self._supports_code(stock_code):
            return None
        try:
            row = self._get_stock_basic_row(stock_code)
        except Exception as exc:
            logger.debug("[Galaxy] 获取 %s 股票名称失败: %s", stock_code, exc)
            return None
        if row is None:
            return None
        for key in ("name", "SECURITY_NAME", "COMP_NAME", "COMP_NAME_ENG"):
            value = row.get(key) if isinstance(row, dict) else None
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def get_belong_board(self, stock_code: str):
        if not self.enabled or not self._supports_code(stock_code):
            return []
        try:
            row = self._get_stock_basic_row(stock_code)
        except Exception as exc:
            logger.debug("[Galaxy] 获取 %s 上市板块失败: %s", stock_code, exc)
            return []
        if row is None:
            return []
        if isinstance(row, dict):
            boards = row.get("belong_boards")
            if isinstance(boards, list) and boards:
                normalized_boards = []
                for item in boards:
                    if isinstance(item, dict) and str(item.get("name", "")).strip():
                        normalized_boards.append(item)
                    elif item is not None and str(item).strip():
                        normalized_boards.append({"name": str(item).strip()})
                if normalized_boards:
                    return normalized_boards
            board = row.get("board") or row.get("LISTPLATE_NAME")
            if board is not None and str(board).strip():
                return [{"name": str(board).strip(), "type": "list_plate"}]
        return []
