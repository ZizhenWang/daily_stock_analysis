# -*- coding: utf-8 -*-
"""
===================================
大盘复盘命令
===================================

执行大盘复盘分析，生成市场概览报告。
"""

import logging
import threading
from typing import List, Optional

from bot.commands.base import BotCommand
from bot.models import BotMessage, BotResponse

logger = logging.getLogger(__name__)


class MarketCommand(BotCommand):
    """
    大盘复盘命令
    
    执行大盘复盘分析，包括：
    - 主要指数表现
    - 板块热点
    - 市场情绪
    - 后市展望
    
    用法：
        /market - 按 .env 默认区域执行大盘复盘
        /market cn - 仅复盘 A 股
        /market us - 仅复盘美股
        /market both - 复盘 A 股 + 美股
    """

    @property
    def name(self) -> str:
        return "market"

    @property
    def aliases(self) -> List[str]:
        return ["m", "大盘", "复盘", "行情"]

    @property
    def description(self) -> str:
        return "大盘复盘分析"

    @property
    def usage(self) -> str:
        return "/market [cn|us|both]"

    def validate_args(self, args: List[str]) -> Optional[str]:
        """验证可选市场区域参数"""
        if not args:
            return None
        region = (args[0] or "").strip().lower()
        if region not in {"cn", "us", "both"}:
            return f"无效的市场区域: {args[0]}（合法值：cn / us / both）"
        if len(args) > 1:
            return "最多只支持一个市场区域参数"
        return None

    def execute(self, message: BotMessage, args: List[str]) -> BotResponse:
        """执行大盘复盘命令"""
        region_override = (args[0].strip().lower() if args else None)
        logger.info(f"[MarketCommand] 开始大盘复盘分析, region_override={region_override}")

        # 在后台线程中执行复盘（避免阻塞）
        thread = threading.Thread(
            target=self._run_market_review,
            args=(message, region_override),
            daemon=True
        )
        thread.start()

        region_text = (
            {
                "cn": "A股",
                "us": "美股",
                "both": "A股 + 美股",
            }.get(region_override, "默认配置区域")
        )

        return BotResponse.markdown_response(
            "✅ **大盘复盘任务已启动**\n\n"
            f"复盘区域：{region_text}\n\n"
            "正在分析：\n"
            "• 主要指数表现\n"
            "• 板块热点分析\n"
            "• 市场情绪判断\n"
            "• 后市展望\n\n"
            "分析完成后将自动推送结果。"
        )

    def _run_market_review(self, message: BotMessage, region_override: Optional[str] = None) -> None:
        """后台执行大盘复盘"""
        try:
            from src.config import get_config
            from src.notification import NotificationService
            from src.search_service import SearchService
            from src.analyzer import GeminiAnalyzer
            from src.core.market_review import run_market_review

            config = get_config()
            notifier = NotificationService(source_message=message)

            # 初始化搜索服务
            search_service = None
            if config.bocha_api_keys or config.tavily_api_keys or config.brave_api_keys or config.serpapi_keys or config.minimax_api_keys or config.searxng_base_urls:
                search_service = SearchService(
                    bocha_keys=config.bocha_api_keys,
                    tavily_keys=config.tavily_api_keys,
                    brave_keys=config.brave_api_keys,
                    serpapi_keys=config.serpapi_keys,
                    minimax_keys=config.minimax_api_keys,
                    searxng_base_urls=config.searxng_base_urls,
                    news_max_age_days=config.news_max_age_days,
                )

            # 初始化 AI 分析器
            analyzer = None
            if config.llm_backend == "codex" or config.gemini_api_key or config.openai_api_key:
                analyzer = GeminiAnalyzer()
                if not analyzer.is_available():
                    analyzer = None

            review_report = run_market_review(
                notifier=notifier,
                analyzer=analyzer,
                search_service=search_service,
                send_notification=True,
                override_region=region_override,
            )

            if review_report:
                logger.info("[MarketCommand] 大盘复盘完成并已推送")
            else:
                logger.warning("[MarketCommand] 大盘复盘返回空结果")

        except Exception as e:
            logger.error(f"[MarketCommand] 大盘复盘失败: {e}")
            logger.exception(e)
