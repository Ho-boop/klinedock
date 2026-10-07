"""
KlineDock - 交易执行API

支持手动下单、一键平仓、订单管理等功能
支持订单类型：市价单、限价单、止损单、追踪止损
"""

import asyncio
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from loguru import logger

from src.engine.paper_engine import paper_engine, PaperEngine
from src.risk import Order, Position
from src.web.api.state_manager import app_state
from src.web.api.market_api import market_api


class OrderType(str, Enum):
    """订单类型"""
    MARKET = "market"           # 市价单
    LIMIT = "limit"             # 限价单
    STOP_LOSS = "stop_loss"     # 止损单
    STOP_LIMIT = "stop_limit"   # 止损限价单
    TRAILING_STOP = "trailing"  # 追踪止损


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class TradingOrder:
    """交易订单"""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None           # 限价单价格
    stop_price: Optional[float] = None      # 止损触发价
    trailing_delta: Optional[float] = None  # 追踪止损幅度（百分比）
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side.value,
            "type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "trailing_delta": self.trailing_delta,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class TradingAPI:
    """
    交易执行API
    
    功能：
    - 市价单/限价单下单
    - 止损单/追踪止损设置
    - 一键平仓
    - 订单管理（查询/取消）
    """
    
    def __init__(self):
        self._engine = paper_engine
        self._pending_orders: Dict[str, TradingOrder] = {}  # 挂单
        self._order_counter: int = 0
        self._stop_orders: Dict[str, TradingOrder] = {}     # 止损单
        self._trailing_orders: Dict[str, TradingOrder] = {} # 追踪止损单
        self._trailing_highs: Dict[str, float] = {}         # 追踪止损最高价
    
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        self._order_counter += 1
        return f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{self._order_counter:04d}"
    
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> Dict[str, Any]:
        """
        下市价单
        
        Args:
            symbol: 交易对
            side: 方向 ("buy" 或 "sell")
            quantity: 数量
            
        Returns:
            Dict: 订单结果
        """
        try:
            order_id = self._generate_order_id()
            order_side = OrderSide(side.lower())
            
            trading_order = TradingOrder(
                id=order_id,
                symbol=symbol,
                side=order_side,
                order_type=OrderType.MARKET,
                quantity=quantity
            )
            
            # 获取当前价格
            prices = market_api.get_cached_prices()
            current_price = prices.get(symbol)
            
            if current_price is None:
                # 尝试获取价格
                price_list = await market_api.get_prices([symbol])
                if price_list:
                    current_price = price_list[0].get("price")
            
            if current_price is None:
                return {
                    "success": False,
                    "message": f"无法获取 {symbol} 的当前价格",
                    "order_id": order_id
                }
            
            # 创建引擎订单
            engine_order = Order(
                symbol=symbol,
                side=side.lower(),
                quantity=quantity,
                price=current_price
            )
            
            # 提交到模拟盘引擎
            success = self._engine.submit_order(engine_order)
            
            if success:
                trading_order.status = OrderStatus.FILLED
                trading_order.filled_quantity = quantity
                trading_order.filled_price = current_price
                trading_order.updated_at = datetime.now()
                
                logger.info(f"市价单成交: {side.upper()} {quantity} {symbol} @ {current_price}")
                
                return {
                    "success": True,
                    "message": f"订单已成交: {side.upper()} {quantity} {symbol} @ ${current_price:,.2f}",
                    "order_id": order_id,
                    "order": trading_order.to_dict()
                }
            else:
                trading_order.status = OrderStatus.REJECTED
                return {
                    "success": False,
                    "message": "订单被拒绝（可能资金不足或持仓不足）",
                    "order_id": order_id
                }
                
        except Exception as e:
            logger.error(f"下单失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> Dict[str, Any]:
        """
        下限价单
        
        Args:
            symbol: 交易对
            side: 方向
            quantity: 数量
            price: 限价
            
        Returns:
            Dict: 订单结果
        """
        try:
            order_id = self._generate_order_id()
            order_side = OrderSide(side.lower())
            
            trading_order = TradingOrder(
                id=order_id,
                symbol=symbol,
                side=order_side,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=price
            )
            
            # 存入挂单列表
            self._pending_orders[order_id] = trading_order
            
            logger.info(f"限价单已挂出: {side.upper()} {quantity} {symbol} @ {price}")
            
            return {
                "success": True,
                "message": f"限价单已创建: {side.upper()} {quantity} {symbol} @ ${price:,.2f}",
                "order_id": order_id,
                "order": trading_order.to_dict()
            }
            
        except Exception as e:
            logger.error(f"创建限价单失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def place_stop_loss_order(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        limit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        设置止损单
        
        Args:
            symbol: 交易对
            quantity: 平仓数量
            stop_price: 止损触发价
            limit_price: 止损后的限价（可选，不填则为市价止损）
            
        Returns:
            Dict: 订单结果
        """
        try:
            order_id = self._generate_order_id()
            order_type = OrderType.STOP_LIMIT if limit_price else OrderType.STOP_LOSS
            
            trading_order = TradingOrder(
                id=order_id,
                symbol=symbol,
                side=OrderSide.SELL,  # 止损通常是卖出
                order_type=order_type,
                quantity=quantity,
                price=limit_price,
                stop_price=stop_price
            )
            
            # 存入止损单列表
            self._stop_orders[order_id] = trading_order
            
            # 注册价格监听
            self._register_stop_monitor(order_id, symbol, stop_price)
            
            logger.info(f"止损单已设置: {symbol} 触发价 ${stop_price:,.2f}")
            
            return {
                "success": True,
                "message": f"止损单已设置: {symbol} 价格跌破 ${stop_price:,.2f} 时触发",
                "order_id": order_id,
                "order": trading_order.to_dict()
            }
            
        except Exception as e:
            logger.error(f"设置止损单失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def place_trailing_stop_order(
        self,
        symbol: str,
        quantity: float,
        trailing_delta: float  # 百分比，如 5.0 表示 5%
    ) -> Dict[str, Any]:
        """
        设置追踪止损单
        
        Args:
            symbol: 交易对
            quantity: 平仓数量
            trailing_delta: 追踪幅度（百分比）
            
        Returns:
            Dict: 订单结果
        """
        try:
            order_id = self._generate_order_id()
            
            # 获取当前价格作为起始追踪价
            prices = market_api.get_cached_prices()
            current_price = prices.get(symbol, 0)
            
            if current_price <= 0:
                return {
                    "success": False,
                    "message": f"无法获取 {symbol} 的当前价格"
                }
            
            trading_order = TradingOrder(
                id=order_id,
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.TRAILING_STOP,
                quantity=quantity,
                trailing_delta=trailing_delta
            )
            
            # 存入追踪止损列表
            self._trailing_orders[order_id] = trading_order
            self._trailing_highs[order_id] = current_price
            
            stop_price = current_price * (1 - trailing_delta / 100)
            
            logger.info(f"追踪止损已设置: {symbol} 幅度 {trailing_delta}%, 当前止损价 ${stop_price:,.2f}")
            
            return {
                "success": True,
                "message": f"追踪止损已设置: {symbol} 幅度 {trailing_delta}%, 当前止损价 ${stop_price:,.2f}",
                "order_id": order_id,
                "order": trading_order.to_dict(),
                "current_stop_price": stop_price
            }
            
        except Exception as e:
            logger.error(f"设置追踪止损失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def _register_stop_monitor(self, order_id: str, symbol: str, stop_price: float):
        """注册止损价格监控"""
        def on_price_update(sym: str, price: float):
            if sym == symbol and price <= stop_price:
                # 触发止损
                asyncio.create_task(self._trigger_stop_order(order_id))
        
        market_api.register_price_callback(on_price_update)
    
    async def _trigger_stop_order(self, order_id: str):
        """触发止损单"""
        if order_id not in self._stop_orders:
            return
        
        order = self._stop_orders[order_id]
        
        # 执行市价卖出
        result = await self.place_market_order(
            symbol=order.symbol,
            side="sell",
            quantity=order.quantity
        )
        
        if result["success"]:
            order.status = OrderStatus.FILLED
            order.updated_at = datetime.now()
            del self._stop_orders[order_id]
            logger.info(f"止损单已触发: {order_id}")
    
    async def close_position(self, symbol: str) -> Dict[str, Any]:
        """
        平仓指定交易对
        
        Args:
            symbol: 交易对
            
        Returns:
            Dict: 平仓结果
        """
        try:
            positions = self._engine.get_virtual_positions()
            
            if symbol not in positions:
                return {
                    "success": False,
                    "message": f"没有 {symbol} 的持仓"
                }
            
            position = positions[symbol]
            
            # 下市价卖出单
            result = await self.place_market_order(
                symbol=symbol,
                side="sell",
                quantity=position.quantity
            )
            
            if result["success"]:
                return {
                    "success": True,
                    "message": f"已平仓 {symbol}: 卖出 {position.quantity:.4f}",
                    "closed_quantity": position.quantity,
                    "order": result.get("order")
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def close_all_positions(self) -> Dict[str, Any]:
        """
        一键平仓所有持仓
        
        Returns:
            Dict: 平仓结果
        """
        try:
            positions = self._engine.get_virtual_positions()
            
            if not positions:
                return {
                    "success": True,
                    "message": "没有持仓需要平仓",
                    "closed": []
                }
            
            closed = []
            failed = []
            
            for symbol, position in positions.items():
                result = await self.place_market_order(
                    symbol=symbol,
                    side="sell",
                    quantity=position.quantity
                )
                
                if result["success"]:
                    closed.append({
                        "symbol": symbol,
                        "quantity": position.quantity,
                        "price": result.get("order", {}).get("filled_price", 0)
                    })
                else:
                    failed.append({
                        "symbol": symbol,
                        "reason": result.get("message")
                    })
            
            if failed:
                return {
                    "success": False,
                    "message": f"部分平仓失败: {len(failed)} 笔",
                    "closed": closed,
                    "failed": failed
                }
            
            logger.info(f"一键平仓完成: {len(closed)} 笔")
            
            return {
                "success": True,
                "message": f"已平仓 {len(closed)} 个持仓",
                "closed": closed
            }
            
        except Exception as e:
            logger.error(f"一键平仓失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        取消订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            Dict: 取消结果
        """
        try:
            # 检查挂单
            if order_id in self._pending_orders:
                order = self._pending_orders.pop(order_id)
                order.status = OrderStatus.CANCELLED
                logger.info(f"限价单已取消: {order_id}")
                return {
                    "success": True,
                    "message": f"订单 {order_id} 已取消",
                    "order": order.to_dict()
                }
            
            # 检查止损单
            if order_id in self._stop_orders:
                order = self._stop_orders.pop(order_id)
                order.status = OrderStatus.CANCELLED
                logger.info(f"止损单已取消: {order_id}")
                return {
                    "success": True,
                    "message": f"止损单 {order_id} 已取消",
                    "order": order.to_dict()
                }
            
            # 检查追踪止损单
            if order_id in self._trailing_orders:
                order = self._trailing_orders.pop(order_id)
                if order_id in self._trailing_highs:
                    del self._trailing_highs[order_id]
                order.status = OrderStatus.CANCELLED
                logger.info(f"追踪止损单已取消: {order_id}")
                return {
                    "success": True,
                    "message": f"追踪止损单 {order_id} 已取消",
                    "order": order.to_dict()
                }
            
            return {
                "success": False,
                "message": f"订单 {order_id} 不存在或已成交"
            }
            
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """获取所有挂单"""
        orders = []
        
        # 限价单
        for order in self._pending_orders.values():
            orders.append(order.to_dict())
        
        # 止损单
        for order in self._stop_orders.values():
            orders.append(order.to_dict())
        
        # 追踪止损单
        for order in self._trailing_orders.values():
            order_dict = order.to_dict()
            # 计算当前止损价
            if order.id in self._trailing_highs:
                high = self._trailing_highs[order.id]
                order_dict["current_stop_price"] = high * (1 - order.trailing_delta / 100)
            orders.append(order_dict)
        
        return orders
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """获取当前持仓"""
        positions = []
        
        for symbol, pos in self._engine.get_virtual_positions().items():
            pnl = pos.unrealized_pnl
            pnl_percent = ((pos.current_price - pos.avg_price) / pos.avg_price * 100) if pos.avg_price > 0 else 0
            
            positions.append({
                "symbol": symbol,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": pos.current_price,
                "market_value": pos.market_value,
                "unrealized_pnl": pnl,
                "pnl_percent": pnl_percent
            })
        
        return positions
    
    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        return self._engine.get_summary()


# 全局交易API实例
trading_api = TradingAPI()
