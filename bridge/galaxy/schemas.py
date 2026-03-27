# -*- coding: utf-8 -*-
"""Shared response helpers and optional FastAPI schemas for Galaxy bridge."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "galaxy-bridge"
    sdk_ready: bool = True
    sdk_error: Optional[str] = None
    sdk_logged_in: bool = False
    last_activity_at: Optional[str] = None
    idle_timeout_seconds: int = 300


class BoardItem(BaseModel):
    name: str


class StockBasicResponse(BaseModel):
    code: str
    name: Optional[str] = None
    board: Optional[str] = None
    belong_boards: List[BoardItem] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


class FundamentalBundleResponse(BaseModel):
    status: str = "not_supported"
    growth: Dict[str, Any] = Field(default_factory=dict)
    earnings: Dict[str, Any] = Field(default_factory=dict)
    institution: Dict[str, Any] = Field(default_factory=dict)
    source_chain: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


def success(payload: Any, *, status: str = "ok") -> Dict[str, Any]:
    return {
        "status": status,
        "data": payload,
    }
