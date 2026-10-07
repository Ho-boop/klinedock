"""
KlineDock - 实盘交易引擎

真实资金交易（需谨慎使用）
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import hmac
import hashlib
import time
import aiohttp
from loguru import logger

from src.core.config import get_config
from src.core.event_bus import event_bus, Event, EventType
from src.strategy import BaseStrategy, StrategyContext, Signal, SignalType
from src.risk import RiskEngine, Order, Position, create_position_control, create_stop_loss_module
from src.engine.paper_engine import EngineState


@dataclass
class OrderResult:
    """订单结果"""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    filled_qty: float = 0.0
    filled_price: float = 0.0
    commission: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class LiveEngine:
    """
    实盘交易引擎
    
    功能:
    - 币安API对接
    - 真实订单执行
    - 账户和持仓同步
    - 风控集成
    
    ⚠️ 警告: 此引擎涉及真实资金，请谨慎使用！
    """
    
    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"
    
    def __init__(self, testnet: bool = True):
        """
        初始化实盘引擎
        
        Args:
            testnet: 是否使用测试网（强烈建议先用测试网）
        """
        self.config = get_config()
        self._testnet = testnet
        self._base_url = self.TESTNET_URL if testnet else self.BASE_URL
        
        # API凭证
        self._api_key = self.config.binance.api_key
        self._api_secret = self.config.binance.api_secret
        
        # 状态
        self._state = EngineState.IDLE
        self._strategy: Optional[BaseStrategy] = None
        
        # 会话
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 风控
        self._risk_engine = RiskEngine()
        self._risk_engine.register(create_position_control())
        self._risk_engine.register(create_stop_loss_module())
        
        # 账户信息
        self._balance: float = 0.0
        self._positions: Dict[str, Position] = {}
        
        # 安全确认
        self._confirmed = False
    
    @property
    def state(self) -> EngineState:
        return self._state
    
    @property
    def is_running(self) -> bool:
        return self._state == EngineState.RUNNING
    
    def _check_credentials(self) -> bool:
        """检查API凭证是否配置"""
        if not self._api_key or not self._api_secret:
            logger.error("未配置币安API凭证！请在.env文件中设置BINANCE_API_KEY和BINANCE_API_SECRET")
            return False
        return True
    
    def _sign_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """签名请求"""
        params["timestamp"] = int(time.time() * 1000)
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self._api_key}
            )
        return self._session
    
    def confirm_live_trading(self, confirmation: str) -> bool:
        """
        确认实盘交易
        
        必须输入 "I UNDERSTAND THE RISKS" 才能启用实盘
        
        Args:
            confirmation: 确认文本
            
        Returns:
            bool: 是否确认成功
        """
        if confirmation == "I UNDERSTAND THE RISKS":
            self._confirmed = True
            logger.warning("⚠️ 实盘交易已确认！请谨慎操作！")
            return True
        
        logger.error("确认失败：请输入正确的确认文本")
        return False
    
    async def start(self, strategy: BaseStrategy, symbols: List[str]) -> bool:
        """
        启动实盘引擎
        
        Args:
            strategy: 策略实例
            symbols: 交易标的
            
        Returns:
            bool: 是否启动成功
        """
        # 安全检查
        if not self._testnet and not self._confirmed:
            logger.error(
                "未确认实盘交易！请先调用 confirm_live_trading('I UNDERSTAND THE RISKS')"
            )
            return False
        
        if not self._check_credentials():
            return False
        
        self._state = EngineState.STARTING
        self._strategy = strategy
        
        # 同步账户信息
        if not await self.sync_account():
            self._state = EngineState.ERROR
            return False
        
        self._state = EngineState.RUNNING
        
        mode = "测试网" if self._testnet else "⚠️ 实盘"
        logger.info(f"实盘引擎已启动 [{mode}]: {strategy.name}")
        
        event_bus.publish(Event(
            event_type=EventType.STRATEGY_START,
            data={"strategy": strategy.name, "mode": "live", "testnet": self._testnet},
            source="live_engine"
        ))
        
        return True
    
    async def stop(self) -> None:
        """停止实盘引擎"""
        if self._state != EngineState.RUNNING:
            return
        
        self._state = EngineState.STOPPING
        
        # 关闭会话
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        
        self._state = EngineState.STOPPED
        logger.info("实盘引擎已停止")
    
    async def sync_account(self) -> bool:
        """同步账户信息"""
        try:
            session = await self._get_session()
            params = self._sign_request({})
            
            async with session.get(
                f"{self._base_url}/api/v3/account",
                params=params
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"同步账户失败: {error}")
                    return False
                
                data = await response.json()
                
                # 解析余额
                for balance in data.get("balances", []):
                    asset = balance["asset"]
                    free = float(balance["free"])
                    locked = float(balance["locked"])
                    
                    if asset == "USDT":
                        self._balance = free
                    
                    if free + locked > 0:
                        logger.debug(f"资产: {asset} = {free} (锁定: {locked})")
                
                logger.info(f"账户同步成功，USDT余额: {self._balance}")
                return True
                
        except Exception as e:
            logger.error(f"同步账户异常: {e}")
            return False
    
    async def submit_order(self, order: Order) -> OrderResult:
        """
        提交真实订单
        
        Args:
            order: 订单
            
        Returns:
            OrderResult: 执行结果
        """
        if not self.is_running:
            return OrderResult(success=False, message="引擎未运行")
        
        # 风控检查
        from src.risk import RiskContext
        risk_context = RiskContext(
            balance=self._balance,
            equity=self._balance,  # 简化
            positions=self._positions
        )
        
        result = self._risk_engine.check_order(order)
        if not result.passed:
            return OrderResult(success=False, message=f"风控拒绝: {result.reason}")
        
        # 执行订单
        return await self._execute_order(order)
    
    async def _execute_order(self, order: Order) -> OrderResult:
        """执行订单"""
        try:
            session = await self._get_session()
            
            params = {
                "symbol": order.symbol,
                "side": order.side.upper(),
                "type": order.order_type.upper(),
                "quantity": order.quantity
            }
            
            if order.order_type == "limit" and order.price:
                params["price"] = order.price
                params["timeInForce"] = "GTC"
            
            params = self._sign_request(params)
            
            async with session.post(
                f"{self._base_url}/api/v3/order",
                params=params
            ) as response:
                data = await response.json()
                
                if response.status != 200:
                    msg = data.get("msg", "未知错误")
                    logger.error(f"订单失败: {msg}")
                    return OrderResult(success=False, message=msg)
                
                # 解析结果
                order_result = OrderResult(
                    success=True,
                    order_id=str(data.get("orderId")),
                    filled_qty=float(data.get("executedQty", 0)),
                    filled_price=float(data.get("price", 0)),
                    message=data.get("status", "")
                )
                
                logger.info(
                    f"订单成功: {order.side.upper()} {order.quantity} {order.symbol} "
                    f"订单ID: {order_result.order_id}"
                )
                
                # 发布事件
                event_bus.publish(Event(
                    event_type=EventType.ORDER_SUBMITTED,
                    data={"order": order, "result": order_result},
                    source="live_engine"
                ))
                
                return order_result
                
        except Exception as e:
            logger.error(f"订单执行异常: {e}")
            return OrderResult(success=False, message=str(e))
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """取消订单"""
        try:
            session = await self._get_session()
            params = self._sign_request({
                "symbol": symbol,
                "orderId": order_id
            })
            
            async with session.delete(
                f"{self._base_url}/api/v3/order",
                params=params
            ) as response:
                if response.status == 200:
                    logger.info(f"订单已取消: {order_id}")
                    return True
                else:
                    error = await response.json()
                    logger.error(f"取消订单失败: {error.get('msg')}")
                    return False
                    
        except Exception as e:
            logger.error(f"取消订单异常: {e}")
            return False
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """获取未成交订单"""
        try:
            session = await self._get_session()
            params = {}
            if symbol:
                params["symbol"] = symbol
            params = self._sign_request(params)
            
            async with session.get(
                f"{self._base_url}/api/v3/openOrders",
                params=params
            ) as response:
                if response.status == 200:
                    return await response.json()
                return []
                
        except Exception as e:
            logger.error(f"获取未成交订单失败: {e}")
            return []
    
    def get_balance(self) -> float:
        """获取余额"""
        return self._balance
    
    def get_positions(self) -> Dict[str, Position]:
        """获取持仓"""
        return self._positions.copy()


# 全局实盘引擎（默认使用测试网）
live_engine = LiveEngine(testnet=True)
