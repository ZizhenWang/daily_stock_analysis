# -*- coding: utf-8 -*-
"""Watchlist service layer."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.storage import get_db
from src.watchlist_utils import normalize_symbol_list

logger = logging.getLogger(__name__)


class WatchlistService:
    """Service layer for structured watchlist CRUD and bootstrap."""

    def __init__(self) -> None:
        self._db = get_db()

    def bootstrap_from_stock_list(self, stock_list: List[str]) -> int:
        """Bootstrap DB watchlist from legacy STOCK_LIST once."""
        normalized = normalize_symbol_list(stock_list)
        if not normalized:
            return 0
        inserted = self._db.bootstrap_watchlist_from_symbols(normalized, source="env_bootstrap")
        if inserted:
            logger.info("Watchlist bootstrap completed from STOCK_LIST: inserted=%d", inserted)
        return inserted

    def has_items(self) -> bool:
        """Return True when DB-backed watchlist already exists."""
        return self._db.watchlist_has_items()

    def list_items(
        self,
        *,
        active_only: bool = False,
        analyzable_only: bool = False,
        active: Optional[bool] = None,
        market: Optional[str] = None,
        security_type: Optional[str] = None,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        sector_tag: Optional[str] = None,
        concept_tag: Optional[str] = None,
        custom_tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self._db.get_watchlist_items(
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

    def get_default_analysis_symbols(self) -> List[str]:
        return self._db.get_watchlist_codes(active_only=True, analyzable_only=True)

    def create_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._db.upsert_watchlist_item(**payload)

    def update_item(self, item_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._db.update_watchlist_item(item_id, **payload)

    def delete_item(self, item_id: int) -> int:
        return self._db.delete_watchlist_item(item_id)

    def create_relation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._db.create_watchlist_relation(**payload)

    def delete_relation(self, relation_id: int) -> int:
        return self._db.delete_watchlist_relation(relation_id)
