# -*- coding: utf-8 -*-
"""
===================================
Watchlist 管理命令
===================================

支持在 Bot 中直接维护结构化 watchlist。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse
from src.services.watchlist_service import WatchlistService
from src.watchlist_utils import normalize_tags, normalize_watchlist_symbol

logger = logging.getLogger(__name__)


class WatchlistCommand(BotCommand):
    """
    Watchlist 命令。

    用法：
        /watchlist add AAPL
        /watchlist add 510300 type=etf sector=宽基,指数 tag=观察
        /watchlist list
        /watchlist list market=cn active=true
    """

    @property
    def name(self) -> str:
        return "watchlist"

    @property
    def aliases(self) -> List[str]:
        return ["wl", "自选股", "观察池"]

    @property
    def description(self) -> str:
        return "管理结构化 watchlist（新增/查看）"

    @property
    def usage(self) -> str:
        return "/watchlist <add|list> ..."

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        if not args:
            return BotResponse.markdown_response(self._help_text())

        action = args[0].lower()
        service = WatchlistService()

        if action == "add":
            return self._handle_add(service, message, args[1:])
        if action == "list":
            return self._handle_list(service, args[1:])

        return BotResponse.error_response(
            f"不支持的 watchlist 操作: {action}\n\n{self._help_text()}"
        )

    def _handle_add(self, service: WatchlistService, message: BotMessage, args: List[str]) -> BotResponse:
        if not args:
            return BotResponse.error_response(
                "请提供股票代码。\n用法: `/watchlist add AAPL sector=AI,消费电子 concept=果链 tag=观察`"
            )

        symbol = normalize_watchlist_symbol(args[0])
        if not symbol:
            return BotResponse.error_response("股票代码不能为空")

        options = self._parse_options(args[1:])
        payload = {
            "symbol": symbol,
            "name": options.get("name"),
            "market": options.get("market"),
            "security_type": options.get("type"),
            "active": self._parse_bool(options.get("active"), default=True),
            "sector_tags": self._parse_tag_option(options, ["sector", "sectors", "field"]),
            "concept_tags": self._parse_tag_option(options, ["concept", "concepts"]),
            "custom_tags": self._parse_tag_option(options, ["tag", "tags", "custom"]),
            "notes": options.get("note") or options.get("notes"),
            "source": f"bot_{message.platform or 'manual'}",
        }

        try:
            item = service.create_item(payload)
        except ValueError as exc:
            return BotResponse.error_response(str(exc))
        except Exception as exc:  # pragma: no cover - bot runtime fallback
            logger.error("[WatchlistCommand] add failed: %s", exc, exc_info=True)
            return BotResponse.error_response(f"添加失败: {str(exc)[:120]}")

        return BotResponse.markdown_response(
            "\n".join(
                [
                    "✅ **已加入 Watchlist**",
                    "",
                    f"• 代码: `{item['symbol']}`",
                    f"• 名称: {item.get('name') or '自动识别'}",
                    f"• 市场 / 类型: `{(item.get('market') or '-').upper()}` / `{item.get('security_type', 'other')}`",
                    f"• 状态: {'启用' if item.get('active') else '停用'}",
                    f"• 领域标签: {', '.join(item.get('sector_tags') or []) or '无'}",
                    f"• 概念标签: {', '.join(item.get('concept_tags') or []) or '无'}",
                    f"• 自定义标签: {', '.join(item.get('custom_tags') or []) or '无'}",
                ]
            )
        )

    def _handle_list(self, service: WatchlistService, args: List[str]) -> BotResponse:
        options = self._parse_options(args)
        active_value = self._parse_optional_bool(options.get("active"))
        try:
            items = service.list_items(
                active=active_value,
                market=options.get("market"),
                security_type=options.get("type"),
                q=options.get("q") or options.get("keyword"),
                tag=options.get("tag"),
                sector_tag=options.get("sector"),
                concept_tag=options.get("concept"),
                custom_tag=options.get("custom"),
            )
        except Exception as exc:  # pragma: no cover - bot runtime fallback
            logger.error("[WatchlistCommand] list failed: %s", exc, exc_info=True)
            return BotResponse.error_response(f"读取 watchlist 失败: {str(exc)[:120]}")

        if not items:
            return BotResponse.text_response("当前筛选条件下没有匹配的 watchlist 标的。")

        preview = items[:12]
        lines = [
            f"📋 **Watchlist（共 {len(items)} 条）**",
            "",
        ]
        for item in preview:
            tags: List[str] = []
            if item.get("sector_tags"):
                tags.append(f"领域:{','.join(item['sector_tags'][:3])}")
            if item.get("concept_tags"):
                tags.append(f"概念:{','.join(item['concept_tags'][:3])}")
            if item.get("custom_tags"):
                tags.append(f"自定义:{','.join(item['custom_tags'][:3])}")
            lines.append(
                f"• `{item['symbol']}`"
                f" {item.get('name') or ''}".rstrip()
                + f" | {(item.get('market') or '-').upper()}/{item.get('security_type', 'other')}"
                + f" | {'启用' if item.get('active') else '停用'}"
                + (f" | {'；'.join(tags)}" if tags else "")
            )

        if len(items) > len(preview):
            lines.extend(["", f"仅展示前 {len(preview)} 条，可加筛选条件缩小范围。"])
        lines.extend(
            [
                "",
                "示例：`/watchlist add AAPL sector=AI,消费电子 concept=果链 tag=观察`",
            ]
        )
        return BotResponse.markdown_response("\n".join(lines))

    @staticmethod
    def _parse_options(tokens: List[str]) -> Dict[str, str]:
        options: Dict[str, str] = {}
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key:
                options[key] = value
        return options

    @staticmethod
    def _parse_tag_option(options: Dict[str, str], keys: List[str]) -> List[str]:
        for key in keys:
            if key in options:
                return normalize_tags(options[key])
        return []

    @staticmethod
    def _parse_bool(raw_value: Optional[str], *, default: bool) -> bool:
        if raw_value is None:
            return default
        return str(raw_value).strip().lower() not in {"0", "false", "no", "off", "停用"}

    @staticmethod
    def _parse_optional_bool(raw_value: Optional[str]) -> Optional[bool]:
        if raw_value is None:
            return None
        return str(raw_value).strip().lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def _help_text() -> str:
        return "\n".join(
            [
                "📘 **Watchlist 命令**",
                "",
                "• `/watchlist add <代码> [name=名称] [market=cn|hk|us] [type=stock|etf|option|index|fund|other]`",
                "• `/watchlist add AAPL sector=AI,消费电子 concept=果链 tag=观察`",
                "• `/watchlist list [market=cn] [type=etf] [active=true|false] [q=关键词]`",
            ]
        )
