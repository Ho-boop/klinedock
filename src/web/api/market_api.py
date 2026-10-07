"""
KlineDock - 行情API

封装币安数据获取操作，支持实时WebSocket推送
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from loguru import logger

from src.data.binance_fetcher import BinanceFetcher
from src.web.api.state_manager import app_state


class MarketAPI:
    """
    行情数据API
    
    功能:
    - 获取实时价格（WebSocket推送）
    - 获取K线数据
    - 获取真实订单簿深度
    """
    
    # 预定义的交易对
    DEFAULT_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", 
        "BTCUSDT.P", "ETHUSDT.P", "SOLUSDT.P", "DOGEUSDT.P", "ORDIUSDT.P"
    ]
    
    def __init__(self):
        self._fetcher_spot: Optional[BinanceFetcher] = None
        self._fetcher_futures: Optional[BinanceFetcher] = None
        self._prices: Dict[str, Dict[str, Any]] = {}
        self._last_update: Optional[datetime] = None
        self._active_symbols = set(self.DEFAULT_SYMBOLS)
        
        # WebSocket 相关
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_running: bool = False
        self._price_callbacks: List[Callable[[str, float], None]] = []
        self._orderbook_cache: Dict[str, Dict[str, Any]] = {}

    def _clean(self, symbol: str) -> str:
        return symbol.replace(".P", "")

    def add_symbol(self, symbol: str) -> bool:
        """添加新交易对"""
        symbol = symbol.upper()
        if symbol in self._active_symbols:
            return False
        
        self._active_symbols.add(symbol)
        
        # 如果WebSocket正在运行，重启它以包含新交易对
        # 注意：这在生产环境中应该更优雅地动态订阅
        if self._ws_running and self._ws_task:
            asyncio.create_task(self._restart_websocket())
            
        return True

    def get_available_symbols(self) -> List[str]:
        """获取所有可用交易对"""
        return sorted(list(self._active_symbols))
        
    async def _restart_websocket(self):
        """重启WebSocket以应用新交易对"""
        logger.info("检测到交易对变更，正在重启WebSocket...")
        await self.stop_websocket_stream()
        await asyncio.sleep(1)
        await self.start_websocket_stream(list(self._active_symbols))

    
    async def _get_fetcher(self, symbol: str) -> BinanceFetcher:
        """获取或创建BinanceFetcher实例"""
        if symbol.endswith(".P"):
            if self._fetcher_futures is None:
                self._fetcher_futures = BinanceFetcher(market_type="usdt_futures")
            return self._fetcher_futures
        else:
            if self._fetcher_spot is None:
                self._fetcher_spot = BinanceFetcher(market_type="spot")
            return self._fetcher_spot
    
    def register_price_callback(self, callback: Callable[[str, float], None]) -> None:
        """
        注册价格更新回调
        
        Args:
            callback: 回调函数，接收 (symbol, price) 参数
        """
        if callback not in self._price_callbacks:
            self._price_callbacks.append(callback)
    
    def unregister_price_callback(self, callback: Callable[[str, float], None]) -> None:
        """取消注册价格更新回调"""
        if callback in self._price_callbacks:
            self._price_callbacks.remove(callback)
    
    async def start_websocket_stream(
        self,
        symbols: List[str] = None,
        interval: str = "1m"
    ) -> None:
        """
        启动 WebSocket 实时行情推送
        
        Args:
            symbols: 交易对列表
            interval: K线周期（用于获取实时价格）
        """
        if self._ws_running:
            logger.warning("WebSocket 已在运行中")
            return
        
        symbols = symbols or self.DEFAULT_SYMBOLS
        self._ws_running = True
        
        logger.info(f"启动 WebSocket 行情推送: {symbols}")
        
        async def stream_loop():
            # 为每个交易对创建 WebSocket 连接任务
            tasks = []
            for symbol in symbols:
                fetcher = await self._get_fetcher(symbol)
                task = asyncio.create_task(
                    self._stream_symbol(fetcher, symbol, interval)
                )
                tasks.append(task)
            
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                logger.info("WebSocket 任务已取消")
            except Exception as e:
                logger.error(f"WebSocket 错误: {e}")
        
        self._ws_task = asyncio.create_task(stream_loop())
    
    async def _stream_symbol(
        self,
        fetcher: BinanceFetcher,
        symbol: str,
        interval: str
    ) -> None:
        """单个交易对的 WebSocket 流处理"""
        
        def on_kline(data: Dict[str, Any]):
            """K线数据回调"""
            if not data.get("is_closed", True):
                # 使用最新价格（即使K线未完结）
                price = data.get("close", 0)
                if price > 0:
                    self._update_price(symbol, price)
        
        def on_error(error: Exception):
            """错误回调"""
            logger.error(f"{symbol} WebSocket 错误: {error}")
        
        while self._ws_running:
            try:
                await fetcher.stream_klines(
                    symbol=self._clean(symbol),
                    interval=interval,
                    callback=on_kline,
                    error_callback=on_error
                )
            except Exception as e:
                logger.error(f"{symbol} 流断开: {e}")
                if self._ws_running:
                    await asyncio.sleep(5)  # 重连等待
    
    def _update_price(self, symbol: str, price: float) -> None:
        """更新价格并触发回调"""
        old_price = self._prices.get(symbol, {}).get("price", price)
        change_percent = ((price - old_price) / old_price * 100) if old_price else 0
        
        self._prices[symbol] = {
            "price": price,
            "change_percent": round(change_percent, 2),
            "time": datetime.now()
        }
        
        # 更新全局状态
        app_state.update_price(symbol, price)
        
        # 触发所有回调
        for callback in self._price_callbacks:
            try:
                callback(symbol, price)
            except Exception as e:
                logger.error(f"价格回调错误: {e}")
    
    async def stop_websocket_stream(self) -> None:
        """停止 WebSocket 行情推送"""
        if not self._ws_running:
            return
        
        self._ws_running = False
        
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        
        self._ws_task = None
        logger.info("WebSocket 行情推送已停止")
    
    @property
    def is_streaming(self) -> bool:
        """是否正在推送"""
        return self._ws_running
    
    async def get_prices(
        self,
        symbols: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取实时价格（HTTP轮询模式，作为 WebSocket 的备用）
        
        Args:
            symbols: 交易对列表
            
        Returns:
            List[Dict]: 价格信息列表
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        prices = []
        for symbol in symbols:
            try:
                fetcher = await self._get_fetcher(symbol)
                price = await fetcher.fetch_ticker_price(self._clean(symbol))
                if price:
                    # 计算24h变化
                    old_price = self._prices.get(symbol, {}).get("price", price)
                    change_percent = ((price - old_price) / old_price * 100) if old_price else 0
                    
                    price_info = {
                        "symbol": symbol,
                        "price": price,
                        "change_percent": round(change_percent, 2)
                    }
                    prices.append(price_info)
                    
                    # 缓存价格
                    self._prices[symbol] = {"price": price, "time": datetime.now()}
                    
                    # 更新全局状态
                    app_state.update_price(symbol, price)
                    
            except Exception as e:
                logger.error(f"获取 {symbol} 价格失败: {e}")
                # 返回缓存的价格
                if symbol in self._prices:
                    prices.append({
                        "symbol": symbol,
                        "price": self._prices[symbol]["price"],
                        "change_percent": 0
                    })
        
        self._last_update = datetime.now()
        app_state.api_connected = len(prices) > 0
        
        return prices
    

            
    def _convert_to_local_time(self, utc_time):
        """将UTC时间转换为本地时间 (UTC+8)"""
        # 简单处理：增加8小时
        return utc_time + timedelta(hours=8)

    async def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取K线数据
        
        Args:
            symbol: 交易对
            interval: K线周期
            limit: 数量限制
            
        Returns:
            List[Dict]: K线数据列表
        """
        fetcher = await self._get_fetcher(symbol)
        
        try:
            df = await fetcher.fetch_klines(
                symbol=self._clean(symbol),
                interval=interval,
                limit=limit
            )
            
            if df.empty:
                return []
            
            # 转换为字典列表
            klines = []
            for idx, row in df.iterrows():
                # 处理时间：UTC -> UTC+8
                if hasattr(idx, "strftime"):
                    local_time = self._convert_to_local_time(idx)
                    time_str = local_time.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = str(idx)
                    
                klines.append({
                    "time": time_str,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"])
                })
            
            return klines
            
        except Exception as e:
            logger.error(f"获取 {symbol} K线失败: {e}")
            return []
    
    async def get_orderbook(
        self,
        symbol: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        获取真实订单簿深度
        
        Args:
            symbol: 交易对
            limit: 深度档位
            
        Returns:
            Dict: 订单簿数据
        """
        fetcher = await self._get_fetcher(symbol)
        
        try:
            orderbook = await fetcher.fetch_orderbook(self._clean(symbol), limit)
            
            if not orderbook:
                return {"bids": [], "asks": [], "symbol": symbol}
            
            # 格式化
            bids = [
                {"price": f"{p:,.2f}", "quantity": f"{q:.4f}", "total": f"{p*q:,.2f}"}
                for p, q in orderbook["bids"][:limit]
            ]
            asks = [
                {"price": f"{p:,.2f}", "quantity": f"{q:.4f}", "total": f"{p*q:,.2f}"}
                for p, q in orderbook["asks"][:limit]
            ]
            
            result = {
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "timestamp": datetime.now().isoformat()
            }
            
            # 缓存
            self._orderbook_cache[symbol] = result
            
            return result
            
        except Exception as e:
            logger.error(f"获取 {symbol} 订单簿失败: {e}")
            # 返回缓存
            if symbol in self._orderbook_cache:
                return self._orderbook_cache[symbol]
            return {"bids": [], "asks": [], "symbol": symbol}
    
    def get_cached_prices(self) -> Dict[str, float]:
        """获取缓存的价格"""
        return {
            symbol: data["price"]
            for symbol, data in self._prices.items()
        }
    
    def get_cached_price_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单个交易对的缓存价格信息"""
        return self._prices.get(symbol)
    
    async def close(self) -> None:
        """关闭所有连接"""
        await self.stop_websocket_stream()
        
        if self._fetcher_spot:
            await self._fetcher_spot.close()
            self._fetcher_spot = None
            
        if self._fetcher_futures:
            await self._fetcher_futures.close()
            self._fetcher_futures = None


# 全局行情API实例
market_api = MarketAPI()

