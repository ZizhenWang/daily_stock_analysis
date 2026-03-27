# -*- coding: utf-8 -*-
"""Shared data-provider exceptions.

Keep these errors in a leaf module so lightweight helpers such as the
Galaxy bridge client can import them without triggering heavy fetcher
initialization and circular imports through ``data_provider.base``.
"""


class DataFetchError(Exception):
    """数据获取异常基类"""


class RateLimitError(DataFetchError):
    """API 速率限制异常"""


class DataSourceUnavailableError(DataFetchError):
    """数据源不可用异常"""
