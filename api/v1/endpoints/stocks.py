# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. Watchlist 管理接口
2. POST /api/v1/stocks/extract-from-image 从图片提取股票代码
3. POST /api/v1/stocks/parse-import 解析 CSV/Excel/剪贴板
4. GET /api/v1/stocks/{code}/quote 实时行情接口
5. GET /api/v1/stocks/{code}/history 历史行情接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from api.v1.schemas.stocks import (
    ExtractFromImageResponse,
    ExtractItem,
    KLineData,
    StockHistoryResponse,
    StockQuote,
    WatchlistImportResponse,
    WatchlistItem,
    WatchlistItemInput,
    WatchlistListResponse,
    WatchlistRelation,
    WatchlistRelationInput,
)
from api.v1.schemas.common import ErrorResponse
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.import_parser import (
    MAX_FILE_BYTES,
    parse_import_from_bytes,
    parse_import_from_text,
)
from src.services.stock_service import StockService
from src.services.watchlist_service import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter()

# 须在 /{stock_code} 路由之前定义
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


def _get_watchlist_service() -> WatchlistService:
    return WatchlistService()


@router.get(
    "/watchlist",
    response_model=WatchlistListResponse,
    summary="获取结构化 watchlist",
    description="返回数据库中的结构化 watchlist，支持按市场、资产类型和标签筛选。",
)
def list_watchlist(
    active_only: bool = Query(False),
    analyzable_only: bool = Query(False),
    active: Optional[bool] = Query(None),
    market: Optional[str] = Query(None),
    security_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="按代码/名称/备注模糊筛选"),
    tag: Optional[str] = Query(None),
    sector_tag: Optional[str] = Query(None, description="按领域标签筛选，多个用逗号分隔"),
    concept_tag: Optional[str] = Query(None, description="按概念标签筛选，多个用逗号分隔"),
    custom_tag: Optional[str] = Query(None, description="按自定义标签筛选，多个用逗号分隔"),
) -> WatchlistListResponse:
    service = _get_watchlist_service()
    items = service.list_items(
        active_only=active_only,
        analyzable_only=analyzable_only,
        active=active,
        market=market,
        security_type=security_type,
        q=q,
        tag=tag,
        sector_tag=sector_tag,
        concept_tag=concept_tag,
        custom_tag=custom_tag,
    )
    return WatchlistListResponse(total=len(items), items=[WatchlistItem.model_validate(item) for item in items])


@router.post(
    "/watchlist",
    response_model=WatchlistItem,
    summary="新增 watchlist 标的",
)
def create_watchlist_item(payload: WatchlistItemInput) -> WatchlistItem:
    service = _get_watchlist_service()
    try:
        item = service.create_item({**payload.model_dump(), "source": "manual"})
        return WatchlistItem.model_validate(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": str(exc)})


@router.put(
    "/watchlist/{item_id}",
    response_model=WatchlistItem,
    summary="编辑 watchlist 标的",
)
def update_watchlist_item(item_id: int, payload: WatchlistItemInput) -> WatchlistItem:
    service = _get_watchlist_service()
    try:
        item = service.update_item(item_id, payload.model_dump())
        return WatchlistItem.model_validate(item)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail={"error": "bad_request", "message": str(exc)})


@router.delete(
    "/watchlist/{item_id}",
    summary="删除 watchlist 标的",
)
def delete_watchlist_item(item_id: int) -> dict:
    service = _get_watchlist_service()
    deleted = service.delete_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "watchlist item not found"})
    return {"success": True, "deleted": deleted}


@router.post(
    "/watchlist/{item_id}/active",
    response_model=WatchlistItem,
    summary="启用/停用 watchlist 标的",
)
def set_watchlist_item_active(item_id: int, active: bool = Query(...)) -> WatchlistItem:
    service = _get_watchlist_service()
    try:
        item = service.update_item(item_id, {"active": active})
        return WatchlistItem.model_validate(item)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail={"error": "bad_request", "message": str(exc)})


@router.post(
    "/watchlist/relations",
    response_model=WatchlistRelation,
    summary="创建 watchlist 关系",
)
def create_watchlist_relation(payload: WatchlistRelationInput) -> WatchlistRelation:
    service = _get_watchlist_service()
    try:
        relation = service.create_relation(payload.model_dump())
        return WatchlistRelation.model_validate(relation)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail={"error": "bad_request", "message": str(exc)})


@router.delete(
    "/watchlist/relations/{relation_id}",
    summary="删除 watchlist 关系",
)
def delete_watchlist_relation(relation_id: int) -> dict:
    service = _get_watchlist_service()
    deleted = service.delete_relation(relation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "watchlist relation not found"})
    return {"success": True, "deleted": deleted}


@router.post(
    "/watchlist/import-stock-list",
    response_model=WatchlistImportResponse,
    summary="从旧版 STOCK_LIST 导入 watchlist",
)
def import_watchlist_from_stock_list() -> WatchlistImportResponse:
    from src.config import get_config

    config = get_config()
    stock_list = config._read_stock_list_from_env()
    service = _get_watchlist_service()
    imported_count = service.bootstrap_from_stock_list(stock_list)
    items = service.list_items()
    return WatchlistImportResponse(
        imported_count=imported_count,
        items=[WatchlistItem.model_validate(item) for item in items],
    )


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "提取的股票代码"},
        400: {"description": "图片无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从图片提取股票代码",
    description="上传截图/图片，通过 Vision LLM 提取股票代码。支持 JPEG、PNG、WebP、GIF，最大 5MB。",
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> ExtractFromImageResponse:
    """
    从上传的图片中提取股票代码（使用 Vision LLM）。

    表单字段请使用 file 上传图片。优先级：Gemini / Anthropic / OpenAI（首个可用）。
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # 先读取限定大小，再检查是否还有剩余（语义清晰：超出则拒绝）
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"读取上传文件失败: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        )

    try:
        items, raw_text = extract_stock_codes_from_image(data, content_type)
        extract_items = [
            ExtractItem(code=code, name=name, confidence=conf) for code, name, conf in items
        ]
        codes = [i.code for i in extract_items]
        return ExtractFromImageResponse(
            codes=codes,
            items=extract_items,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"图片提取失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "图片提取失败"},
        )


@router.post(
    "/parse-import",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "解析结果"},
        400: {"description": "未提供数据或解析失败", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="解析 CSV/Excel/剪贴板",
    description="上传 CSV/Excel 文件或粘贴文本，自动解析股票代码。文件上限 2MB，文本上限 100KB。",
)
async def parse_import(request: Request) -> ExtractFromImageResponse:
    """
    解析 CSV/Excel 文件或剪贴板文本。

    - multipart/form-data + file: 上传文件
    - application/json + {"text": "..."}: 粘贴文本
    - 优先使用 file，若同时提供则忽略 text
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            logger.warning("[parse_import] JSON parse failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json", "message": f"JSON 解析失败: {e}"},
            )
        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供 text，请使用 {\"text\": \"...\"}"},
            )
        try:
            items = parse_import_from_text(text)
        except ValueError as e:
            text_bytes = len(text.encode("utf-8"))
            logger.warning(
                "[parse_import] parse_import_from_text failed: text_bytes=%d, error=%s",
                text_bytes,
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    elif "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file"},
            )
        file_size = getattr(file, "size", None)
        if isinstance(file_size, int) and file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
        try:
            data = file.file.read(MAX_FILE_BYTES)
            if file.file.read(1):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "file_too_large",
                        "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            filename = getattr(file, "filename", None) or ""
            size = getattr(file, "size", None)
            logger.warning(
                "[parse_import] file read failed: filename=%r, size=%s, error=%s",
                filename,
                size,
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": "read_failed", "message": "读取文件失败"},
            )
        filename = getattr(file, "filename", None) or ""
        try:
            items = parse_import_from_bytes(data, filename=filename)
        except ValueError as e:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            logger.warning(
                "[parse_import] parse_import_from_bytes failed: filename=%r, ext=%r, bytes=%d, error=%s",
                filename,
                ext,
                len(data),
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "请使用 multipart/form-data 上传文件，或 application/json 提交 {\"text\": \"...\"}",
            },
        )

    extract_items = [
        ExtractItem(code=code, name=name, confidence=conf)
        for code, name, conf in items
    ]
    codes = list(dict.fromkeys(i.code for i in extract_items if i.code))
    return ExtractFromImageResponse(codes=codes, items=extract_items, raw_text=None)


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情
    
    获取指定股票的最新行情数据
    
    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）
        
    Returns:
        StockQuote: 实时行情数据
        
    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )
        
        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情
    
    获取指定股票的历史 K 线数据
    
    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数
        
    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )
        
        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]
        
        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data
        )
    
    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"获取历史行情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )
