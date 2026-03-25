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
- 依赖券商侧提供的 AmazingData / tgw SDK wheel
- 登录参数（账号、密码、host、port）需向银河证券申请
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import RLock
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


logger = logging.getLogger(__name__)


class GalaxyFetcher(BaseFetcher):
    """星耀数智查询式 A 股数据源。"""

    name = "GalaxyFetcher"
    priority = int(os.getenv("GALAXY_PRIORITY", "0"))

    _login_lock = RLock()
    _login_signature = None
    _login_ready = False

    def __init__(self) -> None:
        self.enabled = os.getenv("GALAXY_ENABLED", "false").lower() == "true"
        self.host = (os.getenv("GALAXY_HOST", "") or "").strip()
        self.port = int((os.getenv("GALAXY_PORT", "0") or "0").strip() or "0")
        self.username = (os.getenv("GALAXY_USERNAME", "") or "").strip()
        self.password = (os.getenv("GALAXY_PASSWORD", "") or "").strip()
        raw_local_path = (os.getenv("GALAXY_LOCAL_PATH", "./data/galaxy") or "./data/galaxy").strip()
        self.local_path = str(Path(raw_local_path).expanduser().resolve())
        self.history_enabled = os.getenv("GALAXY_HISTORY_ENABLED", "true").lower() == "true"
        self._calendar_cache: Optional[list[int]] = None
        self._stock_basic_cache: Dict[str, Optional[pd.Series]] = {}

        if self.enabled:
            logger.info(
                "GalaxyFetcher 已启用: host=%s, port=%s, priority=%s, local_path=%s",
                self.host,
                self.port,
                self.priority,
                self.local_path,
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
        missing = []
        if not self.username:
            missing.append("GALAXY_USERNAME")
        if not self.password:
            missing.append("GALAXY_PASSWORD")
        if not self.host:
            missing.append("GALAXY_HOST")
        if not self.port:
            missing.append("GALAXY_PORT")
        if missing:
            raise DataSourceUnavailableError(f"GalaxyFetcher 配置不完整: {', '.join(missing)}")

    @staticmethod
    def _load_sdk():
        try:
            import AmazingData as ad
        except Exception as exc:  # pragma: no cover - optional dependency
            raise DataSourceUnavailableError(
                "未安装 AmazingData SDK，请先安装券商提供的 tgw / AmazingData wheel"
            ) from exc
        return ad

    def _ensure_login(self):
        self._ensure_available()
        ad = self._load_sdk()
        signature = (self.username, self.password, self.host, self.port)
        with self._login_lock:
            if self.__class__._login_ready and self.__class__._login_signature == signature:
                return ad
            Path(self.local_path).mkdir(parents=True, exist_ok=True)
            ad.login(
                username=self.username,
                password=self.password,
                host=self.host,
                port=self.port,
            )
            self.__class__._login_signature = signature
            self.__class__._login_ready = True
        return ad

    def _get_calendar(self) -> list[int]:
        if self._calendar_cache:
            return self._calendar_cache
        ad = self._ensure_login()
        calendar = ad.BaseData().get_calendar()
        if not isinstance(calendar, list) or not calendar:
            raise DataFetchError("Galaxy get_calendar 未返回有效交易日历")
        self._calendar_cache = calendar
        return calendar

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
    def _pick_latest_row(df: Optional[pd.DataFrame], stock_code: str) -> Optional[pd.Series]:
        if df is None or df.empty:
            return None
        work_df = df.copy()
        target = normalize_stock_code(stock_code)
        code_col = next(
            (col for col in work_df.columns if str(col) in {"MARKET_CODE", "证券代码", "股票代码", "code", "symbol"}),
            None,
        )
        if code_col is not None:
            try:
                matched = work_df[work_df[code_col].astype(str).str.extract(r"(\d{6})", expand=False) == target]
                if not matched.empty:
                    work_df = matched.copy()
            except Exception:
                pass

        for candidate in ("LISTDATE", "DELISTDATE"):
            if candidate in work_df.columns:
                try:
                    work_df = work_df.sort_values(candidate)
                except Exception:
                    pass
        return work_df.iloc[-1]

    def _get_stock_basic_row(self, stock_code: str) -> Optional[pd.Series]:
        normalized = normalize_stock_code(stock_code)
        if normalized in self._stock_basic_cache:
            return self._stock_basic_cache[normalized]

        if not self._supports_code(normalized):
            self._stock_basic_cache[normalized] = None
            return None

        ad = self._ensure_login()
        info_data = ad.InfoData()
        payload = info_data.get_stock_basic([self._to_galaxy_code(normalized)])
        df = self._extract_frame(payload, normalized)
        row = self._pick_latest_row(df, normalized)
        self._stock_basic_cache[normalized] = row
        return row

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self._ensure_available()
        if not self.history_enabled:
            raise DataSourceUnavailableError("Galaxy 历史行情已禁用（GALAXY_HISTORY_ENABLED=false）")
        if not self._supports_code(stock_code):
            raise DataSourceUnavailableError("Galaxy 当前仅支持 A 股 / 北交所 6 位代码")

        ad = self._ensure_login()
        calendar = self._get_calendar()
        market_data = ad.MarketData(calendar)
        period = getattr(getattr(ad, "constant", None), "Period", None)
        if period is None or getattr(period, "day", None) is None:
            raise DataFetchError("AmazingData SDK 缺少 Period.day")
        period_value = getattr(period.day, "value", period.day)

        payload = market_data.query_kline(
            [self._to_galaxy_code(stock_code)],
            begin_date=int(start_date.replace("-", "")),
            end_date=int(end_date.replace("-", "")),
            period=period_value,
        )
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
        for key in ("SECURITY_NAME", "COMP_NAME", "COMP_NAME_ENG"):
            value = row.get(key)
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
        board = row.get("LISTPLATE_NAME")
        if board is None or not str(board).strip():
            return []
        return [{"name": str(board).strip(), "type": "list_plate"}]
