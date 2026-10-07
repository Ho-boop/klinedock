"""
KlineDock - 数据层模块

提供数据获取、格式转换、质量检查和存储功能
"""

from src.data.binance_fetcher import BinanceFetcher, BinanceInterval
from src.data.data_converter import (
    DataConverter,
    DataQualityChecker,
    DataQualityReport,
    DataQualityIssue
)
from src.data.data_manager import DataManager, data_manager

__all__ = [
    # 获取器
    "BinanceFetcher",
    "BinanceInterval",
    
    # 转换器
    "DataConverter",
    
    # 质量检查
    "DataQualityChecker",
    "DataQualityReport",
    "DataQualityIssue",
    
    # 管理器
    "DataManager",
    "data_manager",
]
