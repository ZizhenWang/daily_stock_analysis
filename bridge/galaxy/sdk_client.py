# -*- coding: utf-8 -*-
"""Best-effort AmazingData SDK wrapper for the standalone Galaxy bridge."""

from __future__ import annotations

import importlib
import logging
import math
import os
import time
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import BridgeSettings


logger = logging.getLogger(__name__)


class GalaxySdkError(RuntimeError):
    """Raised when the bridge cannot communicate with the AmazingData SDK."""


def _normalize_code(stock_code: str) -> str:
    raw = str(stock_code or "").strip().upper()
    if raw.startswith(("SH", "SZ", "BJ")) and len(raw) > 2:
        return raw[2:]
    if "." in raw:
        left, _, right = raw.partition(".")
        if right in {"SH", "SZ", "BJ"}:
            return left
    return raw


def _is_bse_code(stock_code: str) -> bool:
    normalized = _normalize_code(stock_code)
    return normalized.startswith(("4", "8"))


def _to_galaxy_code(stock_code: str) -> str:
    normalized = _normalize_code(stock_code)
    if not normalized.isdigit() or len(normalized) != 6:
        return normalized
    if _is_bse_code(normalized):
        return "%s.BJ" % normalized
    if normalized.startswith(("5", "6", "9", "11")):
        return "%s.SH" % normalized
    return "%s.SZ" % normalized


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    if text in {"NaT", "nan", "None", ""}:
        return None
    return text


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(key): _normalize_scalar(value) for key, value in row.items()}


def _records_from_payload(payload: Any, stock_code: Optional[str] = None) -> List[Dict[str, Any]]:
    if payload is None:
        return []

    if hasattr(payload, "to_dict") and hasattr(payload, "columns"):
        try:
            rows = payload.to_dict(orient="records")
            return [_normalize_row(row) for row in rows if isinstance(row, dict)]
        except Exception:
            pass

    if hasattr(payload, "to_frame") and hasattr(payload, "index"):
        try:
            frame = payload.to_frame().T
            rows = frame.to_dict(orient="records")
            return [_normalize_row(row) for row in rows if isinstance(row, dict)]
        except Exception:
            pass

    if isinstance(payload, dict):
        for wrapper_key in ("data", "result", "payload"):
            if wrapper_key in payload:
                return _records_from_payload(payload.get(wrapper_key), stock_code=stock_code)

        if stock_code:
            normalized = _normalize_code(stock_code)
            variants = {
                normalized,
                _to_galaxy_code(normalized),
                str(stock_code).upper(),
            }
            upper_variants = {str(item).upper() for item in variants}
            for key, value in payload.items():
                if str(key).upper() in upper_variants:
                    return _records_from_payload(value, stock_code=stock_code)

        if payload and all(not isinstance(v, (dict, list, tuple)) for v in payload.values()):
            return [_normalize_row(payload)]

        if len(payload) == 1:
            return _records_from_payload(next(iter(payload.values())), stock_code=stock_code)

    if isinstance(payload, (list, tuple)):
        rows: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(_normalize_row(item))
            else:
                rows.extend(_records_from_payload(item, stock_code=stock_code))
        return rows

    return []


def _parse_date(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("empty date")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError("unsupported date format: %s" % raw)


def _date_variants(value: str) -> Dict[str, str]:
    dt = _parse_date(value)
    return {
        "iso": dt.strftime("%Y-%m-%d"),
        "ymd": dt.strftime("%Y%m%d"),
        "ts": dt.strftime("%Y-%m-%d 00:00:00"),
    }


def _pick_by_keywords(row: Dict[str, Any], keywords: Sequence[str]) -> Any:
    normalized_keywords = [str(k).strip().lower() for k in keywords if str(k).strip()]
    for key, value in row.items():
        lowered = str(key).strip().lower()
        if any(keyword in lowered for keyword in normalized_keywords):
            normalized = _normalize_scalar(value)
            if normalized not in (None, "", [], {}):
                return normalized
    return None


class GalaxySdkClient:
    """Thread-safe best-effort wrapper over AmazingData classes."""

    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._sdk_module: Optional[Any] = None
        self._market_data: Optional[Any] = None
        self._info_data: Optional[Any] = None
        self._logged_in = False
        self._last_activity_ts: Optional[float] = None

    def _import_sdk(self) -> Any:
        if self._sdk_module is None:
            try:
                self._sdk_module = importlib.import_module("AmazingData")
            except Exception as exc:
                raise GalaxySdkError("Import AmazingData failed: %s" % exc) from exc
        return self._sdk_module

    def _build_instance(self, attr_name: str) -> Any:
        module = self._import_sdk()
        cls = getattr(module, attr_name, None)
        if cls is None:
            raise GalaxySdkError("AmazingData missing %s" % attr_name)

        os.makedirs(self.settings.galaxy_local_path, exist_ok=True)
        candidates = [
            {"args": (), "kwargs": {}},
            {"args": (self.settings.galaxy_local_path,), "kwargs": {}},
            {"args": (), "kwargs": {"local_path": self.settings.galaxy_local_path}},
            {"args": (), "kwargs": {"data_path": self.settings.galaxy_local_path}},
            {"args": (), "kwargs": {"cache_path": self.settings.galaxy_local_path}},
            {"args": (), "kwargs": {"base_path": self.settings.galaxy_local_path}},
        ]
        errors: List[str] = []
        for candidate in candidates:
            args = tuple(candidate.get("args", ()) or ())
            kwargs = dict(candidate.get("kwargs", {}) or {})
            try:
                return cls(*args, **kwargs)
            except TypeError as exc:
                errors.append("TypeError(%s)" % exc)
                continue
            except Exception as exc:
                raise GalaxySdkError("AmazingData %s init failed: %s" % (attr_name, exc)) from exc
        raise GalaxySdkError("%s init signature mismatch: %s" % (attr_name, "; ".join(errors[-4:])))

    def _ensure_login(self) -> None:
        with self._lock:
            if self._logged_in:
                self._touch()
                return
            self.settings.validate_sdk_env()
            module = self._import_sdk()
            login = getattr(module, "login", None)
            if login is None:
                raise GalaxySdkError("AmazingData.login not found")

            try:
                login(
                    username=self.settings.galaxy_username,
                    password=self.settings.galaxy_password,
                    host=self.settings.galaxy_host,
                    port=int(self.settings.galaxy_port),
                )
            except TypeError:
                login(
                    self.settings.galaxy_username,
                    self.settings.galaxy_password,
                    self.settings.galaxy_host,
                    int(self.settings.galaxy_port),
                )
            except Exception as exc:
                raise GalaxySdkError("AmazingData login failed: %s" % exc) from exc

            self._market_data = self._build_instance("MarketData")
            self._info_data = self._build_instance("InfoData")
            self._logged_in = True
            self._touch()
            logger.info(
                "Galaxy bridge SDK login ok: host=%s, port=%s",
                self.settings.galaxy_host,
                self.settings.galaxy_port,
            )

    def _reset_login_state(self) -> None:
        with self._lock:
            self._market_data = None
            self._info_data = None
            self._logged_in = False
            self._last_activity_ts = None

    @staticmethod
    def _is_relogin_candidate(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if not text:
            return False
        keywords = (
            "not login",
            "not logged",
            "login required",
            "session",
            "token",
            "expired",
            "disconnect",
            "disconnected",
            "connection reset",
            "force logout",
            "未登录",
            "登录",
            "会话",
            "失效",
            "断开",
            "超时",
        )
        return any(keyword in text for keyword in keywords)

    def _run_with_relogin(self, action: Any, action_name: str) -> Any:
        try:
            return action()
        except GalaxySdkError as exc:
            if not self._is_relogin_candidate(exc):
                raise
            logger.warning(
                "Galaxy bridge SDK %s hit possible stale session, retrying once with re-login: %s",
                action_name,
                exc,
            )
            self._reset_login_state()
            self._ensure_login()
            try:
                return action()
            except Exception as retry_exc:
                raise GalaxySdkError(
                    "%s failed after re-login retry: %s" % (action_name, retry_exc)
                ) from retry_exc

    def probe(self) -> Tuple[bool, Optional[str]]:
        return True, None

    def _touch(self) -> None:
        self._last_activity_ts = time.time()

    def status(self) -> Dict[str, Any]:
        last_activity = None
        if self._last_activity_ts is not None:
            last_activity = datetime.fromtimestamp(self._last_activity_ts).isoformat()
        return {
            "sdk_ready": True,
            "sdk_error": None,
            "sdk_logged_in": bool(self._logged_in),
            "last_activity_at": last_activity,
            "idle_timeout_seconds": int(max(1, self.settings.galaxy_idle_timeout_seconds)),
        }

    def recycle_if_idle(self) -> bool:
        with self._lock:
            if not self._logged_in or self._last_activity_ts is None:
                return False
            idle_timeout = max(1, int(self.settings.galaxy_idle_timeout_seconds))
            if (time.time() - self._last_activity_ts) < idle_timeout:
                return False

            self._market_data = None
            self._info_data = None
            self._logged_in = False
            self._last_activity_ts = None
            logger.info("Galaxy bridge SDK references recycled after idle timeout (without explicit logout)")
            return True

    @staticmethod
    def _invoke_candidates(target: Any, method_name: str, candidates: Iterable[Dict[str, Any]]) -> Any:
        method = getattr(target, method_name, None)
        if method is None:
            raise GalaxySdkError("%s.%s not found" % (type(target).__name__, method_name))

        errors: List[str] = []
        for candidate in candidates:
            args = tuple(candidate.get("args", ()) or ())
            kwargs = dict(candidate.get("kwargs", {}) or {})
            try:
                return method(*args, **kwargs)
            except TypeError as exc:
                errors.append("TypeError(%s)" % exc)
                continue
            except Exception as exc:
                raise GalaxySdkError("%s failed: %s" % (method_name, exc)) from exc
        raise GalaxySdkError("%s signature mismatch: %s" % (method_name, "; ".join(errors[-3:])))

    def get_kline(self, stock_code: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        symbol = _to_galaxy_code(stock_code)
        start_variants = _date_variants(start_date)
        end_variants = _date_variants(end_date)

        def _query() -> List[Dict[str, Any]]:
            self._ensure_login()
            assert self._market_data is not None

            candidates = [
                {"kwargs": {"code": symbol, "start_date": start_variants["iso"], "end_date": end_variants["iso"], "period": "day"}},
                {"kwargs": {"symbol": symbol, "start_date": start_variants["iso"], "end_date": end_variants["iso"], "period": "day"}},
                {"kwargs": {"stock_code": symbol, "start_date": start_variants["iso"], "end_date": end_variants["iso"], "period": "day"}},
                {"kwargs": {"code_list": [symbol], "start_date": start_variants["iso"], "end_date": end_variants["iso"], "period": "day"}},
                {"kwargs": {"code": symbol, "start_time": start_variants["ts"], "end_time": end_variants["ts"], "period": "day"}},
                {"kwargs": {"symbol": symbol, "start_time": start_variants["ts"], "end_time": end_variants["ts"], "period": "day"}},
                {"kwargs": {"code_list": [symbol], "start_time": start_variants["ts"], "end_time": end_variants["ts"], "period": "day"}},
                {"kwargs": {"code": symbol, "start_date": start_variants["ymd"], "end_date": end_variants["ymd"], "period": "day"}},
            ]
            payload = self._invoke_candidates(self._market_data, "query_kline", candidates)
            records = _records_from_payload(payload, stock_code=symbol)
            if not records:
                raise GalaxySdkError("query_kline returned empty payload for %s" % symbol)
            self._touch()
            return records

        return self._run_with_relogin(_query, "query_kline")

    def get_stock_basic(self, stock_code: str) -> Dict[str, Any]:
        symbol = _to_galaxy_code(stock_code)

        def _query() -> Dict[str, Any]:
            self._ensure_login()
            assert self._info_data is not None

            candidates = [
                {"kwargs": {"code": symbol}},
                {"kwargs": {"symbol": symbol}},
                {"kwargs": {"stock_code": symbol}},
                {"kwargs": {"code_list": [symbol]}},
                {"kwargs": {"symbol_list": [symbol]}},
            ]
            payload = self._invoke_candidates(self._info_data, "get_stock_basic", candidates)
            rows = _records_from_payload(payload, stock_code=symbol)
            if not rows:
                raise GalaxySdkError("get_stock_basic returned empty payload for %s" % symbol)
            self._touch()

            normalized = _normalize_code(stock_code)
            selected = rows[0]
            for row in rows:
                code_value = str(
                    row.get("code")
                    or row.get("CODE")
                    or row.get("security_code")
                    or row.get("SECURITY_CODE")
                    or ""
                ).upper()
                if normalized and normalized in code_value:
                    selected = row
                    break

            board_name = _pick_by_keywords(selected, ["板块", "listplate", "market_name", "board"])
            industry_name = _pick_by_keywords(selected, ["行业", "industry"])
            boards = []
            if board_name:
                boards.append({"name": str(board_name)})
            if industry_name and str(industry_name) != str(board_name):
                boards.append({"name": str(industry_name)})

            return {
                "code": normalized,
                "name": _pick_by_keywords(selected, ["证券简称", "股票简称", "security_name", "comp_name", "name"]),
                "board": str(board_name).strip() if board_name is not None else None,
                "belong_boards": boards,
                "raw": selected,
            }

        return self._run_with_relogin(_query, "get_stock_basic")

    def _query_info_rows(self, method_name: str, stock_code: str) -> List[Dict[str, Any]]:
        symbol = _to_galaxy_code(stock_code)

        def _query() -> List[Dict[str, Any]]:
            self._ensure_login()
            assert self._info_data is not None

            candidates = [
                {"kwargs": {"code": symbol}},
                {"kwargs": {"symbol": symbol}},
                {"kwargs": {"stock_code": symbol}},
                {"kwargs": {"code_list": [symbol]}},
                {"kwargs": {"symbol_list": [symbol]}},
            ]
            payload = self._invoke_candidates(self._info_data, method_name, candidates)
            self._touch()
            return _records_from_payload(payload, stock_code=symbol)

        return self._run_with_relogin(_query, method_name)

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }

        try:
            income_rows = self._query_info_rows("get_income", stock_code)
            if income_rows:
                income_row = income_rows[0]
                result["growth"].update(
                    {
                        "revenue_yoy": _pick_by_keywords(income_row, ["营收同比", "营业收入同比", "收入同比", "revenue_yoy", "同比增长"]),
                        "net_profit_yoy": _pick_by_keywords(income_row, ["净利润同比", "归母净利润同比", "profit_yoy"]),
                        "report_date": _pick_by_keywords(income_row, ["公告日期", "报告期", "report_date", "publish_date"]),
                        "income_raw": income_row,
                    }
                )
                result["earnings"].update(
                    {
                        "revenue": _pick_by_keywords(income_row, ["营业收入", "营收", "revenue"]),
                        "net_profit": _pick_by_keywords(income_row, ["净利润", "归母净利润", "net_profit"]),
                        "eps": _pick_by_keywords(income_row, ["每股收益", "eps"]),
                        "income_raw": income_row,
                    }
                )
                result["source_chain"].append("galaxy_bridge:get_income")
        except Exception as exc:
            result["errors"].append("get_income:%s" % type(exc).__name__)

        try:
            express_rows = self._query_info_rows("get_profit_express", stock_code)
            if express_rows:
                express_row = express_rows[0]
                result["growth"].update(
                    {
                        "profit_express_revenue_yoy": _pick_by_keywords(express_row, ["营业收入同比", "营收同比", "收入同比"]),
                        "profit_express_net_profit_yoy": _pick_by_keywords(express_row, ["净利润同比", "归母净利润同比"]),
                        "profit_express_raw": express_row,
                    }
                )
                result["earnings"].update(
                    {
                        "profit_express_revenue": _pick_by_keywords(express_row, ["营业收入", "营收"]),
                        "profit_express_net_profit": _pick_by_keywords(express_row, ["净利润", "归母净利润"]),
                        "profit_express_eps": _pick_by_keywords(express_row, ["每股收益", "eps"]),
                        "profit_express_raw": express_row,
                    }
                )
                result["source_chain"].append("galaxy_bridge:get_profit_express")
        except Exception as exc:
            result["errors"].append("get_profit_express:%s" % type(exc).__name__)

        try:
            notice_rows = self._query_info_rows("get_profit_notice", stock_code)
            if notice_rows:
                notice_row = notice_rows[0]
                result["earnings"].update(
                    {
                        "profit_notice_type": _pick_by_keywords(notice_row, ["预告类型", "notice_type", "类型"]),
                        "profit_notice_range": _pick_by_keywords(notice_row, ["变动区间", "预告区间", "forecast_range", "区间"]),
                        "profit_notice_summary": _pick_by_keywords(notice_row, ["预告摘要", "摘要", "summary", "内容"]),
                        "profit_notice_raw": notice_row,
                    }
                )
                result["source_chain"].append("galaxy_bridge:get_profit_notice")
        except Exception as exc:
            result["errors"].append("get_profit_notice:%s" % type(exc).__name__)

        has_content = bool(result["growth"] or result["earnings"] or result["institution"])
        result["status"] = "partial" if has_content else "not_supported"
        result["source_chain"] = list(dict.fromkeys(result["source_chain"]))
        result["errors"] = list(dict.fromkeys(result["errors"]))
        return result
