# -*- coding: utf-8 -*-
"""Standalone FastAPI bridge for AmazingData / Galaxy SDK."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query

from .config import BridgeSettings
from .schemas import FundamentalBundleResponse, HealthResponse, StockBasicResponse, success
from .sdk_client import GalaxySdkClient, GalaxySdkError


settings = BridgeSettings.from_env()
sdk_client = GalaxySdkClient(settings)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Galaxy Bridge",
    version="0.1.0",
    description="Standalone HTTP bridge for AmazingData / Galaxy broker SDK.",
)


def _check_token(authorization: Optional[str]) -> None:
    if not settings.bridge_token:
        return
    expected = "Bearer %s" % settings.bridge_token
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": "galaxy-bridge"}


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    sdk_ready, sdk_error = sdk_client.probe()
    return {
        "status": "ok",
        "service": "galaxy-bridge",
        "sdk_ready": sdk_ready,
        "sdk_error": sdk_error,
    }


@app.get("/api/v1/galaxy/kline")
def get_kline(
    code: str = Query(..., min_length=1),
    start_date: str = Query(..., min_length=1),
    end_date: str = Query(..., min_length=1),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _check_token(authorization)
    try:
        records = sdk_client.get_kline(code, start_date, end_date)
    except GalaxySdkError as exc:
        logger.exception("Galaxy bridge kline failed for %s", code)
        raise HTTPException(status_code=502, detail=str(exc))
    return success(records, status="ok")


@app.get("/api/v1/galaxy/stock-basic", response_model=None)
def get_stock_basic(
    code: str = Query(..., min_length=1),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _check_token(authorization)
    try:
        payload = sdk_client.get_stock_basic(code)
    except GalaxySdkError as exc:
        logger.exception("Galaxy bridge stock-basic failed for %s", code)
        raise HTTPException(status_code=502, detail=str(exc))
    validated = StockBasicResponse(**payload)
    return success(validated.model_dump(), status="ok")


@app.get("/api/v1/galaxy/fundamental", response_model=None)
def get_fundamental_bundle(
    code: str = Query(..., min_length=1),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    _check_token(authorization)
    try:
        payload = sdk_client.get_fundamental_bundle(code)
    except GalaxySdkError as exc:
        logger.exception("Galaxy bridge fundamental failed for %s", code)
        raise HTTPException(status_code=502, detail=str(exc))
    validated = FundamentalBundleResponse(**payload)
    return success(validated.model_dump(), status=validated.status)

