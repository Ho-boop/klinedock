"""
KlineDock - 数据管理器

统一数据访问接口，整合数据获取、转换和存储
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
import pandas as pd
from loguru import logger

from src.core.config import get_config
from src.core.event_bus import event_bus, Event, EventType
from src.data.binance_fetcher import BinanceFetcher, BinanceInterval
from src.data.data_converter import DataConverter, DataQualityChecker, DataQualityReport


class DataManager:
    """
    数据管理器
    
    功能:
    - 统一数据获取接口
    - 数据缓存管理
    - 实时数据订阅
    - 数据质量检查
    - LEAN格式转换
    """
    
    def __init__(self):
        """初始化数据管理器"""
        self.config = get_config()
        self._fetcher: Optional[BinanceFetcher] = None
        self._converter = DataConverter()
        self._quality_checker = DataQualityChecker()
        
        # 数据缓存
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_expiry: Dict[str, datetime] = {}
        self._cache_ttl = timedelta(minutes=5)
        
        # 订阅管理
        self._subscriptions: Dict[str, asyncio.Task] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        
        # 运行状态
        self._running = False
    
    async def start(self) -> None:
        """启动数据管理器"""
        if self._running:
            return
        
        self._fetcher = BinanceFetcher()
        self._running = True
        
        logger.info("数据管理器已启动")
    
    async def stop(self) -> None:
        """停止数据管理器"""
        if not self._running:
            return
        
        # 取消所有订阅
        for sub_id in list(self._subscriptions.keys()):
            await self.unsubscribe(sub_id)
        
        # 关闭获取器
        if self._fetcher:
            await self._fetcher.close()
            self._fetcher = None
        
        # 清空缓存
        self._cache.clear()
        self._cache_expiry.clear()
        
        self._running = False
        logger.info("数据管理器已停止")
    
    async def get_bars(
        self,
        symbol: str,
        interval: str = BinanceInterval.HOUR_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        days_back: int = 30,
        use_cache: bool = True,
        check_quality: bool = False
    ) -> pd.DataFrame:
        """
        获取K线数据
        
        Args:
            symbol: 交易对
            interval: K线周期
            start: 开始时间
            end: 结束时间
            days_back: 向前获取天数
            use_cache: 是否使用缓存
            check_quality: 是否检查数据质量
            
        Returns:
            pd.DataFrame: OHLCV数据
        """
        if not self._fetcher:
            await self.start()
        
        cache_key = f"{symbol}_{interval}_{days_back}"
        
        # 检查缓存
        if use_cache and cache_key in self._cache:
            if datetime.now() < self._cache_expiry.get(cache_key, datetime.min):
                logger.debug(f"使用缓存数据: {cache_key}")
                return self._cache[cache_key]
        
        # 获取数据
        df = await self._fetcher.fetch_klines(
            symbol=symbol,
            interval=interval,
            start_time=start,
            end_time=end,
            days_back=days_back
        )
        
        if df.empty:
            return df
        
        # 数据质量检查
        if check_quality:
            report = self._quality_checker.check(df)
            if not report.is_healthy:
                logger.warning(f"{symbol} 数据质量问题:\n{report.summary()}")
        
        # 更新缓存
        if use_cache:
            self._cache[cache_key] = df
            self._cache_expiry[cache_key] = datetime.now() + self._cache_ttl
        
        return df
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        if not self._fetcher:
            await self.start()
        
        return await self._fetcher.fetch_ticker_price(symbol)
    
    async def get_orderbook(
        self,
        symbol: str,
        limit: int = 100
    ) -> Optional[Dict[str, Any]]:
        """获取订单簿"""
        if not self._fetcher:
            await self.start()
        
        return await self._fetcher.fetch_orderbook(symbol, limit)
    
    async def subscribe(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[Dict[str, Any]], None]
    ) -> str:
        """
        订阅实时数据
        
        Args:
            symbol: 交易对
            interval: K线周期
            callback: 数据回调
            
        Returns:
            str: 订阅ID
        """
        if not self._fetcher:
            await self.start()
        
        sub_id = f"{symbol}_{interval}_{id(callback)}"
        
        # 保存回调
        if sub_id not in self._callbacks:
            self._callbacks[sub_id] = []
        self._callbacks[sub_id].append(callback)
        
        # 创建订阅任务
        if sub_id not in self._subscriptions:
            task = asyncio.create_task(
                self._run_subscription(symbol, interval, sub_id)
            )
            self._subscriptions[sub_id] = task
            logger.info(f"已订阅: {sub_id}")
        
        return sub_id
    
    async def _run_subscription(
        self,
        symbol: str,
        interval: str,
        sub_id: str
    ) -> None:
        """运行订阅"""
        def on_data(data: Dict[str, Any]):
            # 调用所有回调
            for callback in self._callbacks.get(sub_id, []):
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}")
            
            # 发布事件
            event_bus.publish(Event(
                event_type=EventType.MARKET_DATA,
                data=data,
                source="data_manager"
            ))
        
        def on_error(error: Exception):
            logger.error(f"订阅错误 {sub_id}: {error}")
        
        await self._fetcher.stream_klines(
            symbol=symbol,
            interval=interval,
            callback=on_data,
            error_callback=on_error
        )
    
    async def unsubscribe(self, sub_id: str) -> bool:
        """取消订阅"""
        if sub_id in self._subscriptions:
            self._subscriptions[sub_id].cancel()
            try:
                await self._subscriptions[sub_id]
            except asyncio.CancelledError:
                pass
            del self._subscriptions[sub_id]
            
            if sub_id in self._callbacks:
                del self._callbacks[sub_id]
            
            logger.info(f"已取消订阅: {sub_id}")
            return True
        
        return False
    
    async def prepare_lean_data(
        self,
        symbol: str,
        interval: str = BinanceInterval.MINUTE_1,
        days_back: int = 90
    ) -> List[Path]:
        """
        准备LEAN格式数据
        
        Args:
            symbol: 交易对
            interval: K线周期
            days_back: 历史天数
            
        Returns:
            List[Path]: 生成的文件路径
        """
        logger.info(f"准备LEAN数据: {symbol}, {days_back}天")
        
        # 获取历史数据
        df = await self.get_bars(
            symbol=symbol,
            interval=interval,
            days_back=days_back,
            use_cache=False,
            check_quality=True
        )
        
        if df.empty:
            logger.warning(f"无法获取 {symbol} 数据")
            return []
        
        # 转换为LEAN格式
        resolution = "minute" if "m" in interval else "hour" if "h" in interval else "daily"
        files = self._converter.binance_to_lean(df, symbol, resolution)
        
        logger.info(f"LEAN数据准备完成: {len(files)} 个文件")
        
        return files
    
    def check_data_quality(self, df: pd.DataFrame) -> DataQualityReport:
        """检查数据质量"""
        return self._quality_checker.check(df)
    
    def clear_cache(self) -> None:
        """清空所有缓存"""
        self._cache.clear()
        self._cache_expiry.clear()
        logger.info("数据缓存已清空")
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()


# 全局实例
data_manager = DataManager()


# 便捷函数
async def get_btc_bars(days: int = 7) -> pd.DataFrame:
    """快速获取BTC K线数据"""
    return await data_manager.get_bars("BTCUSDT", days_back=days)
