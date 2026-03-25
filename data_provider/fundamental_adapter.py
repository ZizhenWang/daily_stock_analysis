# -*- coding: utf-8 -*-
"""
AkShare fundamental adapter (fail-open).

This adapter intentionally uses capability probing against multiple AkShare
endpoint candidates. It should never raise to caller; partial data is allowed.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    """Best-effort float conversion."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_code(raw: Any) -> str:
    s = _safe_str(raw).upper()
    if "." in s:
        s = s.split(".", 1)[0]
    s = re.sub(r"^(SH|SZ|BJ)", "", s)
    return s


def _pick_by_keywords(row: pd.Series, keywords: List[str]) -> Optional[Any]:
    """
    Return first non-empty row value whose column name contains any keyword.
    """
    for col in row.index:
        col_s = str(col)
        if any(k in col_s for k in keywords):
            val = row.get(col)
            if val is not None and str(val).strip() not in ("", "-", "nan", "None"):
                return val
    return None


def _pick_column(columns: List[Any], keywords: List[str]) -> Optional[Any]:
    """Return the first column whose name contains any keyword."""
    for col in columns:
        col_s = str(col)
        if any(k in col_s for k in keywords):
            return col
    return None


def _safe_date_str(value: Any) -> str:
    """Normalize common date-ish values into YYYY-MM-DD."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        candidate = digits[:8]
        return f"{candidate[:4]}-{candidate[4:6]}-{candidate[6:8]}"
    return text[:32]


def _extract_latest_row(df: pd.DataFrame, stock_code: str) -> Optional[pd.Series]:
    """
    Select the most relevant row for the given stock.
    """
    if df is None or df.empty:
        return None

    code_cols = [c for c in df.columns if any(k in str(c) for k in ("代码", "股票代码", "证券代码", "ts_code", "symbol"))]
    target = _normalize_code(stock_code)
    if code_cols:
        for col in code_cols:
            try:
                series = df[col].astype(str).map(_normalize_code)
                matched = df[series == target]
                if not matched.empty:
                    return matched.iloc[0]
            except Exception:
                continue
        return None

    # Fallback: use latest row
    return df.iloc[0]


class AkshareFundamentalAdapter:
    """AkShare adapter for fundamentals, capital flow and dragon-tiger signals."""

    def _call_df_candidates(
        self,
        candidates: List[Tuple[str, Dict[str, Any]]],
    ) -> Tuple[Optional[pd.DataFrame], Optional[str], List[str]]:
        errors: List[str] = []
        try:
            import akshare as ak
        except Exception as exc:
            return None, None, [f"import_akshare:{type(exc).__name__}"]

        for func_name, kwargs in candidates:
            fn = getattr(ak, func_name, None)
            if fn is None:
                continue
            try:
                df = fn(**kwargs)
                if isinstance(df, pd.Series):
                    df = df.to_frame().T
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df, func_name, errors
            except Exception as exc:
                errors.append(f"{func_name}:{type(exc).__name__}")
                continue
        return None, None, errors

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        """
        Return normalized fundamental blocks from AkShare with partial tolerance.
        """
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }

        # Financial indicators
        fin_df, fin_source, fin_errors = self._call_df_candidates([
            ("stock_financial_abstract", {"symbol": stock_code}),
            ("stock_financial_analysis_indicator", {"symbol": stock_code}),
            ("stock_financial_analysis_indicator", {}),
        ])
        result["errors"].extend(fin_errors)
        if fin_df is not None:
            row = _extract_latest_row(fin_df, stock_code)
            if row is not None:
                revenue_yoy = _safe_float(_pick_by_keywords(row, ["营业收入同比", "营收同比", "收入同比", "同比增长"]))
                profit_yoy = _safe_float(_pick_by_keywords(row, ["净利润同比", "净利同比", "归母净利润同比"]))
                roe = _safe_float(_pick_by_keywords(row, ["净资产收益率", "ROE", "净资产收益"]))
                gross_margin = _safe_float(_pick_by_keywords(row, ["毛利率"]))
                result["growth"] = {
                    "revenue_yoy": revenue_yoy,
                    "net_profit_yoy": profit_yoy,
                    "roe": roe,
                    "gross_margin": gross_margin,
                }
                result["source_chain"].append(f"growth:{fin_source}")

        # Earnings forecast
        forecast_df, forecast_source, forecast_errors = self._call_df_candidates([
            ("stock_yjyg_em", {"symbol": stock_code}),
            ("stock_yjyg_em", {}),
            ("stock_yjbb_em", {"symbol": stock_code}),
            ("stock_yjbb_em", {}),
        ])
        result["errors"].extend(forecast_errors)
        if forecast_df is not None:
            row = _extract_latest_row(forecast_df, stock_code)
            if row is not None:
                result["earnings"]["forecast_summary"] = _safe_str(
                    _pick_by_keywords(row, ["预告", "业绩变动", "内容", "摘要", "公告"])
                )[:200]
                result["source_chain"].append(f"earnings_forecast:{forecast_source}")

        # Earnings quick report
        quick_df, quick_source, quick_errors = self._call_df_candidates([
            ("stock_yjkb_em", {"symbol": stock_code}),
            ("stock_yjkb_em", {}),
        ])
        result["errors"].extend(quick_errors)
        if quick_df is not None:
            row = _extract_latest_row(quick_df, stock_code)
            if row is not None:
                result["earnings"]["quick_report_summary"] = _safe_str(
                    _pick_by_keywords(row, ["快报", "摘要", "公告", "说明"])
                )[:200]
                result["source_chain"].append(f"earnings_quick:{quick_source}")

        # Institution / top shareholders
        inst_df, inst_source, inst_errors = self._call_df_candidates([
            ("stock_institute_hold", {}),
            ("stock_institute_recommend", {}),
        ])
        result["errors"].extend(inst_errors)
        if inst_df is not None:
            row = _extract_latest_row(inst_df, stock_code)
            if row is not None:
                inst_change = _safe_float(_pick_by_keywords(row, ["增减", "变化", "变动", "持股变化"]))
                result["institution"]["institution_holding_change"] = inst_change
                result["source_chain"].append(f"institution:{inst_source}")

        top10_df, top10_source, top10_errors = self._call_df_candidates([
            ("stock_gdfx_top_10_em", {"symbol": stock_code}),
            ("stock_gdfx_top_10_em", {}),
            ("stock_zh_a_gdhs_detail_em", {"symbol": stock_code}),
            ("stock_zh_a_gdhs_detail_em", {}),
        ])
        result["errors"].extend(top10_errors)
        if top10_df is not None:
            row = _extract_latest_row(top10_df, stock_code)
            if row is not None:
                holder_change = _safe_float(_pick_by_keywords(row, ["增减", "变化", "持股变化", "变动"]))
                result["institution"]["top10_holder_change"] = holder_change
                result["source_chain"].append(f"top10:{top10_source}")

        has_content = bool(result["growth"] or result["earnings"] or result["institution"])
        result["status"] = "partial" if has_content else "not_supported"
        return result

    def get_capital_flow(self, stock_code: str, top_n: int = 5) -> Dict[str, Any]:
        """
        Return stock + sector capital flow.
        """
        result: Dict[str, Any] = {
            "status": "not_supported",
            "stock_flow": {},
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": [],
            "errors": [],
        }

        stock_df, stock_source, stock_errors = self._call_df_candidates([
            ("stock_individual_fund_flow", {"stock": stock_code}),
            ("stock_individual_fund_flow", {"symbol": stock_code}),
            ("stock_individual_fund_flow", {}),
            ("stock_main_fund_flow", {"symbol": stock_code}),
            ("stock_main_fund_flow", {}),
        ])
        result["errors"].extend(stock_errors)
        if stock_df is not None:
            row = _extract_latest_row(stock_df, stock_code)
            if row is not None:
                net_inflow = _safe_float(_pick_by_keywords(row, ["主力净流入", "净流入", "净额"]))
                inflow_5d = _safe_float(_pick_by_keywords(row, ["5日", "五日"]))
                inflow_10d = _safe_float(_pick_by_keywords(row, ["10日", "十日"]))
                result["stock_flow"] = {
                    "main_net_inflow": net_inflow,
                    "inflow_5d": inflow_5d,
                    "inflow_10d": inflow_10d,
                }
                result["source_chain"].append(f"capital_stock:{stock_source}")

        sector_df, sector_source, sector_errors = self._call_df_candidates([
            ("stock_sector_fund_flow_rank", {}),
            ("stock_sector_fund_flow_summary", {}),
        ])
        result["errors"].extend(sector_errors)
        if sector_df is not None:
            name_col = next((c for c in sector_df.columns if any(k in str(c) for k in ("板块", "行业", "名称", "name"))), None)
            flow_col = next((c for c in sector_df.columns if any(k in str(c) for k in ("净流入", "主力", "flow", "净额"))), None)
            if name_col and flow_col:
                work_df = sector_df[[name_col, flow_col]].copy()
                work_df[flow_col] = pd.to_numeric(work_df[flow_col], errors="coerce")
                work_df = work_df.dropna(subset=[flow_col])
                top_df = work_df.nlargest(top_n, flow_col)
                bottom_df = work_df.nsmallest(top_n, flow_col)
                result["sector_rankings"] = {
                    "top": [{"name": _safe_str(r[name_col]), "net_inflow": float(r[flow_col])} for _, r in top_df.iterrows()],
                    "bottom": [{"name": _safe_str(r[name_col]), "net_inflow": float(r[flow_col])} for _, r in bottom_df.iterrows()],
                }
                result["source_chain"].append(f"capital_sector:{sector_source}")

        has_content = bool(result["stock_flow"] or result["sector_rankings"]["top"] or result["sector_rankings"]["bottom"])
        result["status"] = "partial" if has_content else "not_supported"
        return result

    def get_dragon_tiger_flag(self, stock_code: str, lookback_days: int = 20) -> Dict[str, Any]:
        """
        Return dragon-tiger signal in lookback window.
        """
        result: Dict[str, Any] = {
            "status": "not_supported",
            "is_on_list": False,
            "recent_count": 0,
            "latest_date": None,
            "source_chain": [],
            "errors": [],
        }

        df, source, errors = self._call_df_candidates([
            ("stock_lhb_stock_statistic_em", {}),
            ("stock_lhb_detail_em", {}),
            ("stock_lhb_jgmmtj_em", {}),
        ])
        result["errors"].extend(errors)
        if df is None:
            return result

        # Try code filter
        code_cols = [c for c in df.columns if any(k in str(c) for k in ("代码", "股票代码", "证券代码"))]
        target = _normalize_code(stock_code)
        matched = pd.DataFrame()
        for col in code_cols:
            try:
                series = df[col].astype(str).map(_normalize_code)
                cur = df[series == target]
                if not cur.empty:
                    matched = cur
                    break
            except Exception:
                continue
        if matched.empty:
            result["source_chain"].append(f"dragon_tiger:{source}")
            result["status"] = "ok" if code_cols else "partial"
            return result

        date_col = next((c for c in matched.columns if any(k in str(c) for k in ("日期", "上榜", "交易日", "time"))), None)
        parsed_dates: List[datetime] = []
        if date_col is not None:
            for val in matched[date_col].astype(str).tolist():
                try:
                    parsed_dates.append(pd.to_datetime(val).to_pydatetime())
                except Exception:
                    continue
        now = datetime.now()
        start = now - timedelta(days=max(1, lookback_days))
        recent_dates = [d for d in parsed_dates if start <= d <= now]

        result["is_on_list"] = bool(recent_dates)
        result["recent_count"] = len(recent_dates) if recent_dates else int(len(matched))
        result["latest_date"] = max(recent_dates).date().isoformat() if recent_dates else (
            max(parsed_dates).date().isoformat() if parsed_dates else None
        )
        result["status"] = "ok"
        result["source_chain"].append(f"dragon_tiger:{source}")
        return result


class GalaxyFundamentalAdapter:
    """AmazingData/星耀数智财务与业绩适配层（A股，fail-open）。"""

    _login_lock = RLock()
    _login_signature: Optional[Tuple[str, str, str, int]] = None
    _login_ready: bool = False

    def __init__(self) -> None:
        self.enabled = os.getenv("GALAXY_ENABLED", "false").lower() == "true"
        self.host = (os.getenv("GALAXY_HOST", "") or "").strip()
        self.port = int((os.getenv("GALAXY_PORT", "0") or "0").strip() or "0")
        self.username = (os.getenv("GALAXY_USERNAME", "") or "").strip()
        self.password = (os.getenv("GALAXY_PASSWORD", "") or "").strip()
        raw_local_path = (os.getenv("GALAXY_LOCAL_PATH", "./data/galaxy") or "./data/galaxy").strip()
        self.local_path = str(Path(raw_local_path).expanduser().resolve())

    @staticmethod
    def _is_cn_equity(stock_code: str) -> bool:
        normalized = _normalize_code(stock_code)
        return normalized.isdigit() and len(normalized) == 6

    @staticmethod
    def _to_galaxy_code(stock_code: str) -> str:
        normalized = _normalize_code(stock_code)
        if not normalized.isdigit() or len(normalized) != 6:
            return normalized
        if normalized.startswith(("8", "4", "92")):
            return f"{normalized}.BJ"
        if normalized.startswith(("5", "6", "9", "11")):
            return f"{normalized}.SH"
        return f"{normalized}.SZ"

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise RuntimeError("GalaxyFundamentalAdapter 未启用")
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
            raise RuntimeError(f"GalaxyFundamentalAdapter 配置不完整: {', '.join(missing)}")

    def _load_sdk(self):
        try:
            import AmazingData as ad
        except Exception as exc:
            raise RuntimeError("未安装 AmazingData SDK") from exc
        return ad

    def _ensure_login(self):
        self._ensure_enabled()
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

    @staticmethod
    def _extract_frame(payload: Any, stock_code: str) -> Optional[pd.DataFrame]:
        if isinstance(payload, pd.DataFrame):
            return payload.copy()
        if isinstance(payload, pd.Series):
            return payload.to_frame().T
        if isinstance(payload, dict):
            normalized = _normalize_code(stock_code)
            variants = {
                stock_code,
                str(stock_code).upper(),
                normalized,
                GalaxyFundamentalAdapter._to_galaxy_code(stock_code),
            }
            for key, value in payload.items():
                if str(key).upper() in {str(v).upper() for v in variants}:
                    return GalaxyFundamentalAdapter._extract_frame(value, stock_code)
            if len(payload) == 1:
                return GalaxyFundamentalAdapter._extract_frame(next(iter(payload.values())), stock_code)
        if isinstance(payload, list):
            try:
                df = pd.DataFrame(payload)
                return df if not df.empty else None
            except Exception:
                return None
        return None

    @staticmethod
    def _latest_row(df: Optional[pd.DataFrame], stock_code: str) -> Optional[pd.Series]:
        if df is None or df.empty:
            return None

        work_df = df.copy()
        code_col = _pick_column(list(work_df.columns), ["MARKET_CODE", "证券代码", "股票代码", "code", "symbol"])
        target = _normalize_code(stock_code)
        if code_col is not None:
            try:
                matched = work_df[work_df[code_col].astype(str).map(_normalize_code) == target]
                if not matched.empty:
                    work_df = matched.copy()
            except Exception:
                pass

        sort_col = _pick_column(
            list(work_df.columns),
            [
                "REPORTING_PERIOD",
                "REPORT_PERIOD",
                "REPORT_TYPE",
                "ANN_DATE",
                "ACTUAL_ANN_DATE",
                "TRADE_DATE",
                "date",
            ],
        )
        if sort_col is not None:
            try:
                sort_key = pd.to_datetime(work_df[sort_col], errors="coerce")
                work_df = work_df.assign(__sort_key=sort_key).sort_values("__sort_key")
                return work_df.iloc[-1]
            except Exception:
                pass

        return work_df.iloc[-1]

    @classmethod
    def _latest_summary_from_df(
        cls,
        df: Optional[pd.DataFrame],
        stock_code: str,
        content_keywords: List[str],
    ) -> str:
        row = cls._latest_row(df, stock_code)
        if row is None:
            return ""
        date_col = _pick_column(list(row.index), ["REPORTING_PERIOD", "ANN_DATE", "ACTUAL_ANN_DATE", "date"])
        date_prefix = _safe_date_str(row.get(date_col)) if date_col is not None else ""
        pieces: List[str] = []
        for col in row.index:
            col_name = str(col)
            if not any(k in col_name for k in content_keywords):
                continue
            val = row.get(col)
            if val is None:
                continue
            text = str(val).strip()
            if not text or text.lower() in {"nan", "none"}:
                continue
            pieces.append(f"{col_name}={text}")
            if len(pieces) >= 3:
                break
        if not pieces:
            return ""
        summary = "；".join(pieces)
        return f"{date_prefix} {summary}".strip()[:200]

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }

        if not self.enabled or not self._is_cn_equity(stock_code):
            return result

        try:
            ad = self._ensure_login()
            info_data = ad.InfoData()
            code_list = [self._to_galaxy_code(stock_code)]
        except Exception as exc:
            result["errors"].append(f"galaxy_login:{type(exc).__name__}")
            result["status"] = "failed"
            return result

        # income: revenue growth / profit growth / margin / roe
        try:
            income_payload = info_data.get_income(
                code_list,
                local_path=self.local_path,
                is_local=True,
            )
            income_df = self._extract_frame(income_payload, stock_code)
            income_row = self._latest_row(income_df, stock_code)
            if income_row is not None:
                result["growth"] = {
                    "revenue_yoy": _safe_float(
                        _pick_by_keywords(
                            income_row,
                            [
                                "TOT_OPERATE_INCOME_YOY",
                                "OPERATE_INCOME_YOY",
                                "营业总收入同比",
                                "营业收入同比",
                                "营收同比",
                            ],
                        )
                    ),
                    "net_profit_yoy": _safe_float(
                        _pick_by_keywords(
                            income_row,
                            [
                                "PARENT_NETPROFIT_YOY",
                                "NET_PROFIT_YOY",
                                "净利润同比",
                                "归母净利润同比",
                            ],
                        )
                    ),
                    "roe": _safe_float(
                        _pick_by_keywords(
                            income_row,
                            ["ROE", "WEIGHTAVG_ROE", "净资产收益率"],
                        )
                    ),
                    "gross_margin": _safe_float(
                        _pick_by_keywords(
                            income_row,
                            ["GROSS_MARGIN", "销售毛利率", "毛利率"],
                        )
                    ),
                }
                result["source_chain"].append("growth:galaxy_income")
        except Exception as exc:
            result["errors"].append(f"galaxy_income:{type(exc).__name__}")

        # profit express / notice: earnings summaries
        try:
            express_payload = info_data.get_profit_express(
                code_list,
                local_path=self.local_path,
                is_local=True,
            )
            express_df = self._extract_frame(express_payload, stock_code)
            quick_summary = self._latest_summary_from_df(
                express_df,
                stock_code,
                [
                    "NET_PROFIT",
                    "OPERATE_INCOME",
                    "BASIC_EPS",
                    "净利润",
                    "营业收入",
                    "每股收益",
                ],
            )
            if quick_summary:
                result["earnings"]["quick_report_summary"] = quick_summary
                result["source_chain"].append("earnings_quick:galaxy_profit_express")
        except Exception as exc:
            result["errors"].append(f"galaxy_profit_express:{type(exc).__name__}")

        try:
            notice_payload = info_data.get_profit_notice(
                code_list,
                local_path=self.local_path,
                is_local=True,
            )
            notice_df = self._extract_frame(notice_payload, stock_code)
            notice_summary = self._latest_summary_from_df(
                notice_df,
                stock_code,
                [
                    "NOTICE",
                    "FORECAST",
                    "SUMMARY",
                    "CONTENT",
                    "净利润",
                    "业绩",
                    "变动",
                    "预告",
                ],
            )
            if notice_summary:
                result["earnings"]["forecast_summary"] = notice_summary
                result["source_chain"].append("earnings_forecast:galaxy_profit_notice")
        except Exception as exc:
            result["errors"].append(f"galaxy_profit_notice:{type(exc).__name__}")

        has_content = bool(result["growth"] or result["earnings"] or result["institution"])
        if has_content:
            result["status"] = "partial"
        return result

    def get_capital_flow(self, stock_code: str, top_n: int = 5) -> Dict[str, Any]:
        del stock_code, top_n
        return {
            "status": "not_supported",
            "stock_flow": {},
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": ["capital_flow:galaxy_not_supported"],
            "errors": [],
        }

    def get_dragon_tiger_flag(self, stock_code: str, lookback_days: int = 20) -> Dict[str, Any]:
        del stock_code, lookback_days
        return {
            "status": "not_supported",
            "is_on_list": False,
            "recent_count": 0,
            "latest_date": None,
            "source_chain": ["dragon_tiger:galaxy_not_supported"],
            "errors": [],
        }


class FundamentalAdapterChain:
    """Galaxy 优先、AkShare 回退的基本面聚合层。"""

    def __init__(self, adapters: Optional[List[Any]] = None) -> None:
        self.adapters = adapters or [GalaxyFundamentalAdapter(), AkshareFundamentalAdapter()]

    @staticmethod
    def _merge_bundle(base: Dict[str, Any], incoming: Dict[str, Any]) -> None:
        for block in ("growth", "earnings", "institution"):
            current = base.setdefault(block, {})
            for key, value in (incoming.get(block, {}) or {}).items():
                if current.get(key) in (None, "", {}, []):
                    current[key] = value
        base.setdefault("source_chain", []).extend(incoming.get("source_chain", []) or [])
        base.setdefault("errors", []).extend(incoming.get("errors", []) or [])

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        merged: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }
        for adapter in self.adapters:
            try:
                payload = adapter.get_fundamental_bundle(stock_code)
            except Exception as exc:
                merged["errors"].append(f"{type(adapter).__name__}:{type(exc).__name__}")
                continue
            if not isinstance(payload, dict):
                continue
            self._merge_bundle(merged, payload)

        has_content = bool(merged["growth"] or merged["earnings"] or merged["institution"])
        merged["status"] = "partial" if has_content else "not_supported"
        return merged

    def _first_supported(self, method_name: str, stock_code: str, **kwargs: Any) -> Dict[str, Any]:
        combined_errors: List[str] = []
        combined_chain: List[str] = []
        for adapter in self.adapters:
            method = getattr(adapter, method_name, None)
            if method is None:
                continue
            try:
                payload = method(stock_code, **kwargs)
            except Exception as exc:
                combined_errors.append(f"{type(adapter).__name__}:{type(exc).__name__}")
                continue
            if not isinstance(payload, dict):
                continue
            combined_errors.extend(payload.get("errors", []) or [])
            combined_chain.extend(payload.get("source_chain", []) or [])
            status = str(payload.get("status", "not_supported"))
            if status != "not_supported":
                merged = dict(payload)
                merged["errors"] = list(dict.fromkeys(combined_errors))
                merged["source_chain"] = list(dict.fromkeys(combined_chain))
                return merged

        return {
            "status": "not_supported",
            "source_chain": combined_chain,
            "errors": combined_errors,
        }

    def get_capital_flow(self, stock_code: str, top_n: int = 5) -> Dict[str, Any]:
        return self._first_supported("get_capital_flow", stock_code, top_n=top_n)

    def get_dragon_tiger_flag(self, stock_code: str, lookback_days: int = 20) -> Dict[str, Any]:
        return self._first_supported("get_dragon_tiger_flag", stock_code, lookback_days=lookback_days)
