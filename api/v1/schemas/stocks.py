# -*- coding: utf-8 -*-
"""
===================================
股票数据相关模型
===================================

职责：
1. 定义股票实时行情模型
2. 定义历史 K 线数据模型
"""

from typing import Optional, List, Literal

from pydantic import BaseModel, Field


class StockQuote(BaseModel):
    """股票实时行情"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    current_price: float = Field(..., description="当前价格")
    change: Optional[float] = Field(None, description="涨跌额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    prev_close: Optional[float] = Field(None, description="昨收价")
    volume: Optional[float] = Field(None, description="成交量（股）")
    amount: Optional[float] = Field(None, description="成交额（元）")
    update_time: Optional[str] = Field(None, description="更新时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "current_price": 1800.00,
                "change": 15.00,
                "change_percent": 0.84,
                "open": 1785.00,
                "high": 1810.00,
                "low": 1780.00,
                "prev_close": 1785.00,
                "volume": 10000000,
                "amount": 18000000000,
                "update_time": "2024-01-01T15:00:00"
            }
        }


class KLineData(BaseModel):
    """K 线数据点"""
    
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    close: float = Field(..., description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    change_percent: Optional[float] = Field(None, description="涨跌幅 (%)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "date": "2024-01-01",
                "open": 1785.00,
                "high": 1810.00,
                "low": 1780.00,
                "close": 1800.00,
                "volume": 10000000,
                "amount": 18000000000,
                "change_percent": 0.84
            }
        }


class ExtractItem(BaseModel):
    """单条提取结果（代码、名称、置信度）"""

    code: Optional[str] = Field(None, description="股票代码，None 表示解析失败")
    name: Optional[str] = Field(None, description="股票名称（如有）")
    confidence: str = Field("medium", description="置信度：high/medium/low")


class ExtractFromImageResponse(BaseModel):
    """图片股票代码提取响应"""

    codes: List[str] = Field(..., description="提取的股票代码（已去重，向后兼容）")
    items: List[ExtractItem] = Field(default_factory=list, description="提取结果明细（代码+名称+置信度）")
    raw_text: Optional[str] = Field(None, description="原始 LLM 响应（调试用）")


class StockHistoryResponse(BaseModel):
    """股票历史行情响应"""
    
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    period: str = Field(..., description="K 线周期")
    data: List[KLineData] = Field(default_factory=list, description="K 线数据列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "period": "daily",
                "data": []
            }
        }


class WatchlistRelation(BaseModel):
    """Watchlist relation item."""

    id: int
    source_item_id: int
    target_item_id: int
    relation_type: Literal['underlying', 'tracks', 'related_to']
    target_symbol: Optional[str] = None
    target_name: Optional[str] = None
    target_market: Optional[str] = None
    target_security_type: Optional[str] = None


class WatchlistItem(BaseModel):
    """Structured watchlist item."""

    id: int
    symbol: str
    name: Optional[str] = None
    market: Optional[Literal['cn', 'hk', 'us']] = None
    security_type: Literal['stock', 'etf', 'option', 'index', 'fund', 'other']
    active: bool = True
    sector_tags: List[str] = Field(default_factory=list)
    concept_tags: List[str] = Field(default_factory=list)
    custom_tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    relations: List[WatchlistRelation] = Field(default_factory=list)


class WatchlistItemInput(BaseModel):
    """Create/update payload for one watchlist item."""

    symbol: str
    name: Optional[str] = None
    market: Optional[Literal['cn', 'hk', 'us']] = None
    security_type: Optional[Literal['stock', 'etf', 'option', 'index', 'fund', 'other']] = None
    active: bool = True
    sector_tags: Optional[List[str]] = None
    concept_tags: Optional[List[str]] = None
    custom_tags: Optional[List[str]] = None
    notes: Optional[str] = None


class WatchlistRelationInput(BaseModel):
    """Create relation payload."""

    source_item_id: int
    target_item_id: int
    relation_type: Literal['underlying', 'tracks', 'related_to']


class WatchlistListResponse(BaseModel):
    """Watchlist list response."""

    total: int
    items: List[WatchlistItem] = Field(default_factory=list)


class WatchlistImportResponse(BaseModel):
    """Legacy STOCK_LIST import response."""

    imported_count: int
    items: List[WatchlistItem] = Field(default_factory=list)
