"""
KlineDock - 币安数据获取器

支持历史K线下载和实时WebSocket数据流
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
import aiohttp
import pandas as pd
from loguru import logger

from src.core.config import get_config


class BinanceInterval:
    """币安K线周期"""
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"
    WEEK_1 = "1w"


class BinanceFetcher:
    """
    币安数据获取器
    
    支持:
    - 历史K线批量下载
    - 实时WebSocket行情订阅
    - 自动限速控制
    """
    
    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"
    WS_URL = "wss://stream.binance.com:9443/ws"
    
    # 每分钟最大请求数
    RATE_LIMIT = 1200
    # 单次K线请求最大数量
    MAX_KLINES_PER_REQUEST = 1000
    
    def __init__(self, testnet: bool = False, market_type: str = "spot"):
        """
        初始化获取器
        
        Args:
            testnet: 是否使用测试网
            market_type: 'spot' 或 'usdt_futures'
        """
        config = get_config()
        self._testnet = testnet or config.binance.testnet
        self._market_type = market_type
        
        if self._market_type == "usdt_futures":
            self._base_url = "https://testnet.binancefuture.com" if self._testnet else "https://fapi.binance.com"
            self._ws_url = "wss://stream.binancefuture.com/ws" if self._testnet else "wss://fstream.binance.com/ws"
            self._api_prefix = "/fapi/v1"
        else:
            self._base_url = self.TESTNET_URL if self._testnet else self.BASE_URL
            self._ws_url = "wss://testnet.binance.vision/ws" if self._testnet else self.WS_URL
            self._api_prefix = "/api/v3"
            
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws_connections: Dict[str, aiohttp.ClientWebSocketResponse] = {}
        self._request_count = 0
        self._last_reset = datetime.now()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def _check_rate_limit(self) -> None:
        """检查并控制请求频率"""
        now = datetime.now()
        if (now - self._last_reset).seconds >= 60:
            self._request_count = 0
            self._last_reset = now
        
        if self._request_count >= self.RATE_LIMIT:
            wait_time = 60 - (now - self._last_reset).seconds
            logger.warning(f"达到速率限制，等待 {wait_time} 秒")
            await asyncio.sleep(wait_time)
            self._request_count = 0
            self._last_reset = datetime.now()
        
        self._request_count += 1
    
    async def fetch_klines(
        self,
        symbol: str,
        interval: str = BinanceInterval.HOUR_1,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        days_back: int = 30,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        获取历史K线数据
        
        Args:
            symbol: 交易对，如 'BTCUSDT'
            interval: K线周期
            start_time: 开始时间
            end_time: 结束时间
            days_back: 如果未指定start_time，向前获取天数
            limit: 单次请求数量上限
            
        Returns:
            pd.DataFrame: OHLCV数据
        """
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=days_back)
        
        all_klines = []
        current_start = start_time
        
        logger.info(f"获取 {symbol} K线数据: {start_time} -> {end_time}")
        
        session = await self._get_session()
        
        while current_start < end_time:
            await self._check_rate_limit()
            
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": int(current_start.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": min(limit, self.MAX_KLINES_PER_REQUEST)
            }
            
            try:
                async with session.get(
                    f"{self._base_url}{self._api_prefix}/klines",
                    params=params
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API请求失败: {response.status} - {error_text}")
                        break
                    
                    klines = await response.json()
                    
                    if not klines:
                        break
                    
                    all_klines.extend(klines)
                    
                    # 更新下一次请求的起始时间
                    last_time = klines[-1][0]
                    current_start = datetime.fromtimestamp(last_time / 1000) + timedelta(milliseconds=1)
                    
                    logger.debug(f"已获取 {len(all_klines)} 条K线")
                    
                    # 如果返回数量小于limit，说明已经没有更多数据
                    if len(klines) < limit:
                        break
                        
            except aiohttp.ClientError as e:
                logger.error(f"网络请求失败: {e}")
                break
            except Exception as e:
                logger.error(f"获取K线数据失败: {e}")
                break
        
        if not all_klines:
            logger.warning(f"未获取到 {symbol} 的K线数据")
            return pd.DataFrame()
        
        # 转换为DataFrame
        df = pd.DataFrame(all_klines, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_volume",
            "taker_buy_quote_volume", "ignore"
        ])
        
        # 数据类型转换
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(float)
        
        # 设置索引
        df.set_index("open_time", inplace=True)
        df.index.name = "datetime"
        
        # 删除不需要的列
        df.drop(columns=["ignore"], inplace=True)
        
        logger.info(f"成功获取 {len(df)} 条 {symbol} K线数据")
        
        return df
    
    async def fetch_ticker_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        await self._check_rate_limit()
        session = await self._get_session()
        
        try:
            # 对于现货，价格接口在 v3/ticker/price
            # 对于合约，价格接口在 v1/ticker/price (已经在 __init__ 里分配给 _api_prefix)
            # 所以直接使用 _api_prefix
            async with session.get(
                f"{self._base_url}{self._api_prefix}/ticker/price",
                params={"symbol": symbol.upper()}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data["price"])
                else:
                    logger.error(f"获取价格失败: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"获取价格异常: {e}")
            return None
    
    async def fetch_orderbook(
        self,
        symbol: str,
        limit: int = 100
    ) -> Optional[Dict[str, Any]]:
        """
        获取订单簿深度
        
        Args:
            symbol: 交易对
            limit: 深度档位（5, 10, 20, 50, 100, 500, 1000, 5000）
        """
        await self._check_rate_limit()
        session = await self._get_session()
        
        try:
            async with session.get(
                f"{self._base_url}{self._api_prefix}/depth",
                params={"symbol": symbol.upper(), "limit": limit}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "bids": [(float(p), float(q)) for p, q in data["bids"]],
                        "asks": [(float(p), float(q)) for p, q in data["asks"]],
                        "timestamp": datetime.now()
                    }
                else:
                    logger.error(f"获取订单簿失败: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"获取订单簿异常: {e}")
            return None
    
    async def stream_klines(
        self,
        symbol: str,
        interval: str,
        callback: Callable[[Dict[str, Any]], None],
        error_callback: Optional[Callable[[Exception], None]] = None
    ) -> None:
        """
        实时K线WebSocket订阅
        
        Args:
            symbol: 交易对
            interval: K线周期
            callback: 数据回调函数
            error_callback: 错误回调函数
        """
        stream_name = f"{symbol.lower()}@kline_{interval}"
        ws_url = f"{self._ws_url}/{stream_name}"
        
        logger.info(f"连接WebSocket: {stream_name}")
        
        session = await self._get_session()
        retry_count = 0
        max_retries = 5
        
        while retry_count < max_retries:
            try:
                async with session.ws_connect(ws_url) as ws:
                    self._ws_connections[stream_name] = ws
                    retry_count = 0  # 重置重试计数
                    
                    logger.info(f"WebSocket已连接: {stream_name}")
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            
                            # 解析K线数据
                            kline = data.get("k", {})
                            parsed = {
                                "symbol": kline.get("s"),
                                "interval": kline.get("i"),
                                "open_time": datetime.fromtimestamp(kline.get("t", 0) / 1000),
                                "close_time": datetime.fromtimestamp(kline.get("T", 0) / 1000),
                                "open": float(kline.get("o", 0)),
                                "high": float(kline.get("h", 0)),
                                "low": float(kline.get("l", 0)),
                                "close": float(kline.get("c", 0)),
                                "volume": float(kline.get("v", 0)),
                                "is_closed": kline.get("x", False)
                            }
                            
                            callback(parsed)
                            
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket错误: {ws.exception()}")
                            break
                            
            except aiohttp.ClientError as e:
                retry_count += 1
                logger.error(f"WebSocket连接失败 ({retry_count}/{max_retries}): {e}")
                
                if error_callback:
                    error_callback(e)
                
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # 指数退避
                    logger.info(f"等待 {wait_time} 秒后重连...")
                    await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"WebSocket异常: {e}")
                if error_callback:
                    error_callback(e)
                break
        
        if stream_name in self._ws_connections:
            del self._ws_connections[stream_name]
        
        logger.info(f"WebSocket已断开: {stream_name}")
    
    async def close(self) -> None:
        """关闭所有连接"""
        # 关闭WebSocket连接
        for name, ws in list(self._ws_connections.items()):
            if not ws.closed:
                await ws.close()
            del self._ws_connections[name]
        
        # 关闭HTTP会话
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
        logger.info("币安数据获取器已关闭")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# 便捷函数
async def fetch_btc_price() -> Optional[float]:
    """快速获取BTC价格"""
    async with BinanceFetcher() as fetcher:
        return await fetcher.fetch_ticker_price("BTCUSDT")
