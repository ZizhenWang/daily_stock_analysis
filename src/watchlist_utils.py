# -*- coding: utf-8 -*-
"""
===================================
Watchlist utilities
===================================

职责：
1. 推断标的市场与资产类型
2. 规范化 watchlist 标签与代码
3. 提供 watchlist 相关常量
"""

from __future__ import annotations

from typing import Iterable, List, Literal, Optional, Sequence

from data_provider import is_hk_stock_code, is_us_index_code, is_us_stock_code
from data_provider.base import ETF_PREFIXES, normalize_stock_code

WatchlistMarket = Literal["cn", "hk", "us"]
WatchlistSecurityType = Literal["stock", "etf", "option", "index", "fund", "other"]
WatchlistRelationType = Literal["underlying", "tracks", "related_to"]

SUPPORTED_RELATION_TYPES: tuple[str, ...] = ("underlying", "tracks", "related_to")
ANALYZABLE_SECURITY_TYPES: tuple[str, ...] = ("stock", "etf")

_KNOWN_US_ETF_SYMBOLS = {
    "ARKK",
    "DIA",
    "EEM",
    "EWH",
    "EWJ",
    "FXI",
    "GLD",
    "GXC",
    "IBB",
    "IVV",
    "IWM",
    "KWEB",
    "QQQ",
    "SCHD",
    "SMH",
    "SOXL",
    "SOXX",
    "SPY",
    "TQQQ",
    "VGT",
    "VHT",
    "VIG",
    "VNQ",
    "VOO",
    "VTI",
    "XBI",
    "XLF",
    "XLK",
}

_KNOWN_HK_ETF_CODES = {
    "02800",
    "03033",
    "03067",
    "03188",
    "03169",
    "03403",
}


def normalize_watchlist_symbol(symbol: str) -> str:
    """Normalize one watchlist symbol while preserving HK/US prefixes."""
    raw = (symbol or "").strip().upper()
    if not raw:
        return ""
    if raw.startswith("HK") and len(raw) >= 4:
        return f"HK{raw[2:].zfill(5)}"
    return raw


def infer_market(symbol: str) -> Optional[WatchlistMarket]:
    """Infer market from one symbol."""
    normalized = normalize_watchlist_symbol(symbol)
    if not normalized:
        return None
    if is_us_stock_code(normalized) or is_us_index_code(normalized):
        return "us"
    if is_hk_stock_code(normalized):
        return "hk"
    base = normalize_stock_code(normalized)
    if base.isdigit() and len(base) == 6:
        return "cn"
    return None


def infer_security_type(symbol: str, name: Optional[str] = None) -> WatchlistSecurityType:
    """Infer security type using conservative heuristics."""
    normalized = normalize_watchlist_symbol(symbol)
    base = normalize_stock_code(normalized)
    upper_name = (name or "").upper()
    lower_name = (name or "").lower()

    # Common US OCC option pattern, e.g. AAPL250117C00250000
    if len(normalized) >= 15 and any(flag in normalized for flag in ("C", "P")):
        if normalized[-8:].isdigit():
            cp_index = max(normalized.rfind("C"), normalized.rfind("P"))
            if cp_index > 0 and normalized[cp_index + 1 :].isdigit():
                return "option"
    if any(token in upper_name for token in ("OPTION", "CALL", "PUT", "期权")):
        return "option"

    if is_us_index_code(normalized):
        return "index"
    if any(token in upper_name for token in ("INDEX", "指数")):
        return "index"

    if (
        (base.isdigit() and len(base) == 6 and base.startswith(ETF_PREFIXES))
        or normalized in _KNOWN_US_ETF_SYMBOLS
        or base in _KNOWN_HK_ETF_CODES
        or " ETF" in upper_name
        or "ETF" in upper_name
    ):
        return "etf"

    if any(token in upper_name for token in ("FUND", "基金")):
        return "fund"

    market = infer_market(symbol)
    if market in {"cn", "hk", "us"}:
        return "stock"
    return "other"


def infer_watchlist_identity(symbol: str, name: Optional[str] = None) -> tuple[Optional[WatchlistMarket], WatchlistSecurityType]:
    """Infer both market and security type for one symbol."""
    return infer_market(symbol), infer_security_type(symbol, name=name)


def normalize_tags(values: Optional[Sequence[str] | str]) -> List[str]:
    """Normalize one tag list to unique ordered strings."""
    if values is None:
        return []
    if isinstance(values, str):
        parts = values.split(",")
    else:
        parts = list(values)

    result: List[str] = []
    seen = set()
    for raw in parts:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def normalize_symbol_list(symbols: Iterable[str]) -> List[str]:
    """Normalize one symbol list and drop empties/duplicates."""
    result: List[str] = []
    seen = set()
    for symbol in symbols:
        normalized = normalize_watchlist_symbol(symbol)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
