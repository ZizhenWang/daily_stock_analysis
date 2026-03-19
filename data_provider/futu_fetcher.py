# -*- coding: utf-8 -*-
"""
===================================
FutuFetcher - OpenD 行情数据源
===================================

数据来源：富途 OpenAPI（通过 OpenD + futu-api Python SDK）
特点：港美股实时/历史数据质量较高，也可选支持 A 股
定位：可选增强数据源，优先补强港股/美股行情

第一期实现：
1. 历史日线：request_history_kline
2. 实时快照：get_market_snapshot
3. 实时报价补充：subscribe + get_stock_quote

注意：
- 不包含交易接口
- 不包含订阅推送流
- 依赖本地/局域网 OpenD 服务
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import pandas as pd

from .base import (
    BaseFetcher,
    DataFetchError,
    DataSourceUnavailableError,
    STANDARD_COLUMNS,
    _is_hk_market,
    _is_us_market,
    is_bse_code,
)
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource, safe_float, safe_int


logger = logging.getLogger(__name__)


class FutuFetcher(BaseFetcher):
    """富途 OpenAPI 行情数据源。"""

    name = "FutuFetcher"
    priority = int(os.getenv("FUTU_PRIORITY", "2"))

    def __init__(self) -> None:
        self.enabled = os.getenv("FUTU_ENABLED", "false").lower() == "true"
        self.host = os.getenv("FUTU_HOST", "127.0.0.1").strip() or "127.0.0.1"
        self.port = int(os.getenv("FUTU_PORT", "11111"))
        self.history_enabled = os.getenv("FUTU_HISTORY_ENABLED", "true").lower() == "true"
        self.realtime_enabled = os.getenv("FUTU_REALTIME_ENABLED", "true").lower() == "true"
        self.supported_markets = self._parse_markets(os.getenv("FUTU_MARKETS", "us,hk"))

        if self.enabled:
            logger.info(
                "FutuFetcher 已启用: host=%s, port=%s, markets=%s, priority=%s",
                self.host,
                self.port,
                ",".join(sorted(self.supported_markets)),
                self.priority,
            )
        else:
            logger.info("FutuFetcher 未启用（FUTU_ENABLED=false）")

    @staticmethod
    def _parse_markets(raw: str) -> Set[str]:
        values = {item.strip().lower() for item in (raw or "").split(",") if item.strip()}
        return values or {"us", "hk"}

    @staticmethod
    def _detect_market(stock_code: str) -> str:
        if _is_us_market(stock_code):
            return "us"
        if _is_hk_market(stock_code):
            return "hk"
        return "cn"

    def supports_market(self, stock_code: str) -> bool:
        return self._detect_market(stock_code) in self.supported_markets

    @staticmethod
    def _is_us_symbol(stock_code: str) -> bool:
        return _is_us_market(stock_code)

    def _ensure_available(self) -> None:
        if not self.enabled:
            raise DataSourceUnavailableError("FutuFetcher 未启用，请设置 FUTU_ENABLED=true")

    @staticmethod
    def _load_sdk() -> Tuple[Any, Any, Any, Any, Any, Any]:
        try:
            from futu import AuType, KLType, OpenQuoteContext, RET_OK, Session, SubType
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise DataSourceUnavailableError(
                "未安装 futu-api，请先执行 `pip install futu-api` 并确保 OpenD 可用"
            ) from exc
        return OpenQuoteContext, RET_OK, KLType, AuType, Session, SubType

    @contextmanager
    def _quote_context(self):
        OpenQuoteContext, _, _, _, _, _ = self._load_sdk()
        ctx = OpenQuoteContext(host=self.host, port=self.port)
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    def _to_futu_code(self, stock_code: str) -> str:
        code = (stock_code or "").strip().upper()
        market = self._detect_market(code)

        if market == "us":
            return f"US.{code}"

        if market == "hk":
            digits = code[2:] if code.startswith("HK") else code
            return f"HK.{digits.zfill(5)}"

        base = code.split(".", 1)[0]
        if is_bse_code(base):
            return f"BJ.{base}"
        if base.startswith(("600", "601", "603", "605", "688")):
            return f"SH.{base}"
        return f"SZ.{base}"

    @staticmethod
    def _build_session_kwargs(session_enum: Any, market: str) -> Dict[str, Any]:
        if market == "us":
            return {"session": session_enum.ALL}
        return {}

    def _request_history_df(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        _, RET_OK, _, AuType, Session, _ = self._load_sdk()
        futu_code = self._to_futu_code(stock_code)
        market = self._detect_market(stock_code)
        session_kwargs = self._build_session_kwargs(Session, market)

        frames = []
        page_req_key = None
        with self._quote_context() as quote_ctx:
            while True:
                ret, data, page_req_key = quote_ctx.request_history_kline(
                    futu_code,
                    start=start_date,
                    end=end_date,
                    max_count=1000,
                    page_req_key=page_req_key,
                    autype=AuType.QFQ,
                    **session_kwargs,
                )
                if ret != RET_OK:
                    raise DataFetchError(f"Futu 历史 K 线获取失败: {data}")
                if data is not None and not data.empty:
                    frames.append(data.copy())
                if page_req_key is None:
                    break

        if not frames:
            raise DataFetchError(f"Futu 未返回 {stock_code} 的历史 K 线数据")
        return pd.concat(frames, ignore_index=True)

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self._ensure_available()
        if not self.history_enabled:
            raise DataSourceUnavailableError("Futu 历史行情已禁用（FUTU_HISTORY_ENABLED=false）")
        if not self.supports_market(stock_code):
            raise DataSourceUnavailableError(
                f"Futu 当前未启用 {self._detect_market(stock_code)} 市场（FUTU_MARKETS={','.join(sorted(self.supported_markets))}）"
            )
        return self._request_history_df(stock_code, start_date, end_date)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df is None or df.empty:
            raise DataFetchError(f"Futu 未返回 {stock_code} 的有效 K 线数据")

        normalized = df.copy()
        rename_map = {
            "time_key": "date",
            "turnover": "amount",
            "change_rate": "pct_chg",
        }
        normalized = normalized.rename(columns=rename_map)

        if "date" not in normalized.columns:
            raise DataFetchError("Futu 返回数据缺少 time_key/date 字段")

        if "pct_chg" not in normalized.columns and "last_close" in normalized.columns:
            last_close = pd.to_numeric(normalized["last_close"], errors="coerce")
            close = pd.to_numeric(normalized["close"], errors="coerce")
            normalized["pct_chg"] = ((close - last_close) / last_close.replace(0, pd.NA)) * 100

        for column in STANDARD_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA

        return normalized[STANDARD_COLUMNS].copy()

    @staticmethod
    def _first_row(data: Any) -> Optional[pd.Series]:
        if data is None or not isinstance(data, pd.DataFrame) or data.empty:
            return None
        return data.iloc[0]

    @staticmethod
    def _row_value(row: pd.Series, *keys: str) -> Any:
        for key in keys:
            if key in row and pd.notna(row[key]):
                return row[key]
        return None

    def _snapshot_to_quote(self, stock_code: str, row: pd.Series) -> UnifiedRealtimeQuote:
        prev_close = safe_float(self._row_value(row, "prev_close_price", "last_close"))
        high = safe_float(self._row_value(row, "high_price", "high"))
        low = safe_float(self._row_value(row, "low_price", "low"))
        amplitude = safe_float(self._row_value(row, "amplitude"))
        if amplitude is None and prev_close and high is not None and low is not None and prev_close > 0:
            amplitude = round(((high - low) / prev_close) * 100, 2)

        return UnifiedRealtimeQuote(
            code=stock_code,
            name=str(self._row_value(row, "name") or ""),
            source=RealtimeSource.FUTU,
            price=safe_float(self._row_value(row, "last_price", "price")),
            change_pct=safe_float(self._row_value(row, "change_rate", "change_pct")),
            change_amount=safe_float(self._row_value(row, "change_val", "change_amount")),
            volume=safe_int(self._row_value(row, "volume")),
            amount=safe_float(self._row_value(row, "turnover", "amount")),
            turnover_rate=safe_float(self._row_value(row, "turnover_rate")),
            amplitude=amplitude,
            open_price=safe_float(self._row_value(row, "open_price", "open")),
            high=high,
            low=low,
            pre_close=prev_close,
            pe_ratio=safe_float(self._row_value(row, "pe_ratio", "pe_ttm_rate")),
            pb_ratio=safe_float(self._row_value(row, "pb_ratio", "pb_rate")),
            total_mv=safe_float(self._row_value(row, "total_market_val", "issued_market_val")),
            circ_mv=safe_float(self._row_value(row, "outstanding_market_val")),
            high_52w=safe_float(self._row_value(row, "highest_52weeks_price")),
            low_52w=safe_float(self._row_value(row, "lowest_52weeks_price")),
        )

    def _get_market_snapshot_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        _, RET_OK, _, _, _, _ = self._load_sdk()
        futu_code = self._to_futu_code(stock_code)
        with self._quote_context() as quote_ctx:
            ret, data = quote_ctx.get_market_snapshot([futu_code])
        if ret != RET_OK:
            raise DataFetchError(f"Futu 快照获取失败: {data}")
        row = self._first_row(data)
        if row is None:
            return None
        return self._snapshot_to_quote(stock_code, row)

    def _get_subscribed_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        _, RET_OK, _, _, Session, SubType = self._load_sdk()
        futu_code = self._to_futu_code(stock_code)
        market = self._detect_market(stock_code)
        session_kwargs = self._build_session_kwargs(Session, market)

        with self._quote_context() as quote_ctx:
            ret_sub, sub_msg = quote_ctx.subscribe(
                [futu_code],
                [SubType.QUOTE],
                subscribe_push=False,
                **session_kwargs,
            )
            if ret_sub != RET_OK:
                raise DataFetchError(f"Futu 实时报价订阅失败: {sub_msg}")
            ret, data = quote_ctx.get_stock_quote([futu_code])
            if ret != RET_OK:
                raise DataFetchError(f"Futu 实时报价获取失败: {data}")

        row = self._first_row(data)
        if row is None:
            return None
        return self._snapshot_to_quote(stock_code, row)

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        self._ensure_available()
        if not self.realtime_enabled:
            return None
        if not self.supports_market(stock_code):
            return None

        try:
            quote = self._get_market_snapshot_quote(stock_code)
            if quote and quote.has_basic_data():
                return quote
        except Exception as exc:
            logger.warning("[Futu] %s 快照获取失败: %s", stock_code, exc)

        try:
            quote = self._get_subscribed_quote(stock_code)
            if quote and quote.has_basic_data():
                return quote
        except Exception as exc:
            logger.warning("[Futu] %s 订阅报价获取失败: %s", stock_code, exc)

        return None
