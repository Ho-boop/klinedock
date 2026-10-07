"""
KlineDock - 止损止盈模块

实现各种止损止盈策略
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from loguru import logger

from src.risk.base_risk import (
    BaseRiskModule,
    RiskCheckResult,
    RiskAction,
    RiskLevel,
    Order,
    Position,
    RiskContext
)


class StopType(str, Enum):
    """止损类型"""
    FIXED = "fixed"           # 固定价格
    PERCENTAGE = "percentage" # 百分比
    TRAILING = "trailing"     # 追踪止损
    ATR = "atr"              # ATR止损


@dataclass
class StopOrder:
    """止损/止盈订单"""
    symbol: str
    stop_type: StopType
    trigger_price: float
    direction: str  # "stop_loss" / "take_profit"
    quantity: Optional[float] = None
    trailing_pct: float = 0.0
    peak_price: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    order_id: str = ""
    
    def __post_init__(self):
        if not self.order_id:
            self.order_id = f"{self.symbol}_{self.direction}_{int(datetime.now().timestamp())}"


class StopLossModule(BaseRiskModule):
    """
    止损止盈模块
    
    功能:
    - 固定止损/止盈
    - 百分比止损/止盈
    - 追踪止损
    - 多目标止盈
    """
    
    name = "StopLoss"
    description = "止损止盈风控模块"
    priority = 10  # 较高优先级
    
    def __init__(self, config=None):
        super().__init__(config)
        
        # 活跃的止损/止盈订单
        self._stop_orders: Dict[str, List[StopOrder]] = {}
        
        # 默认止损比例
        self.default_stop_loss_pct = 0.02  # 2%
        self.default_take_profit_pct = 0.05  # 5%
        
        # 追踪止损配置
        self.trailing_activation_pct = 0.02  # 盈利2%后启动追踪
        self.trailing_stop_pct = 0.01  # 追踪止损1%
    
    def check_order(self, order: Order, context: RiskContext) -> RiskCheckResult:
        """
        检查订单（止损模块主要用于触发检查，订单检查直接通过）
        """
        return RiskCheckResult.approve("止损模块：订单检查通过")
    
    def set_stop_loss(
        self,
        symbol: str,
        trigger_price: float,
        stop_type: StopType = StopType.FIXED,
        quantity: Optional[float] = None,
        trailing_pct: float = 0.0
    ) -> str:
        """
        设置止损
        
        Args:
            symbol: 交易对
            trigger_price: 触发价格
            stop_type: 止损类型
            quantity: 止损数量（None表示全部）
            trailing_pct: 追踪止损百分比
            
        Returns:
            str: 止损订单ID
        """
        stop_order = StopOrder(
            symbol=symbol,
            stop_type=stop_type,
            trigger_price=trigger_price,
            direction="stop_loss",
            quantity=quantity,
            trailing_pct=trailing_pct,
            peak_price=trigger_price
        )
        
        if symbol not in self._stop_orders:
            self._stop_orders[symbol] = []
        
        self._stop_orders[symbol].append(stop_order)
        
        logger.info(f"设置止损: {symbol} @ {trigger_price} ({stop_type.value})")
        return stop_order.order_id
    
    def set_take_profit(
        self,
        symbol: str,
        trigger_price: float,
        quantity: Optional[float] = None
    ) -> str:
        """
        设置止盈
        
        Args:
            symbol: 交易对
            trigger_price: 触发价格
            quantity: 止盈数量（None表示全部）
            
        Returns:
            str: 止盈订单ID
        """
        stop_order = StopOrder(
            symbol=symbol,
            stop_type=StopType.FIXED,
            trigger_price=trigger_price,
            direction="take_profit",
            quantity=quantity
        )
        
        if symbol not in self._stop_orders:
            self._stop_orders[symbol] = []
        
        self._stop_orders[symbol].append(stop_order)
        
        logger.info(f"设置止盈: {symbol} @ {trigger_price}")
        return stop_order.order_id
    
    def set_trailing_stop(
        self,
        symbol: str,
        entry_price: float,
        trailing_pct: float = 0.02
    ) -> str:
        """
        设置追踪止损
        
        Args:
            symbol: 交易对
            entry_price: 入场价格
            trailing_pct: 追踪百分比
            
        Returns:
            str: 止损订单ID
        """
        # 初始止损价 = 入场价 * (1 - 追踪比例)
        initial_stop = entry_price * (1 - trailing_pct)
        
        stop_order = StopOrder(
            symbol=symbol,
            stop_type=StopType.TRAILING,
            trigger_price=initial_stop,
            direction="stop_loss",
            trailing_pct=trailing_pct,
            peak_price=entry_price
        )
        
        if symbol not in self._stop_orders:
            self._stop_orders[symbol] = []
        
        self._stop_orders[symbol].append(stop_order)
        
        logger.info(f"设置追踪止损: {symbol} 追踪{trailing_pct:.1%}")
        return stop_order.order_id
    
    def cancel_stop(self, order_id: str) -> bool:
        """取消止损/止盈订单"""
        for symbol, orders in self._stop_orders.items():
            for i, order in enumerate(orders):
                if order.order_id == order_id:
                    del self._stop_orders[symbol][i]
                    logger.info(f"已取消止损订单: {order_id}")
                    return True
        return False
    
    def check_triggers(
        self,
        current_prices: Dict[str, float]
    ) -> List[Order]:
        """
        检查止损/止盈触发
        
        Args:
            current_prices: 当前价格字典 {symbol: price}
            
        Returns:
            List[Order]: 触发的平仓订单列表
        """
        triggered_orders = []
        orders_to_remove = []
        
        for symbol, price in current_prices.items():
            if symbol not in self._stop_orders:
                continue
            
            for stop_order in self._stop_orders[symbol]:
                triggered = False
                
                if stop_order.direction == "stop_loss":
                    # 止损：价格下跌到触发价
                    if price <= stop_order.trigger_price:
                        triggered = True
                        logger.warning(
                            f"触发止损: {symbol} @ {price} "
                            f"(触发价: {stop_order.trigger_price})"
                        )
                    
                    # 追踪止损：更新峰值和触发价
                    elif stop_order.stop_type == StopType.TRAILING:
                        if price > stop_order.peak_price:
                            stop_order.peak_price = price
                            # 更新追踪止损价
                            new_trigger = price * (1 - stop_order.trailing_pct)
                            if new_trigger > stop_order.trigger_price:
                                stop_order.trigger_price = new_trigger
                                logger.debug(
                                    f"更新追踪止损: {symbol} 新触发价 {new_trigger:.4f}"
                                )
                
                elif stop_order.direction == "take_profit":
                    # 止盈：价格上涨到触发价
                    if price >= stop_order.trigger_price:
                        triggered = True
                        logger.info(
                            f"触发止盈: {symbol} @ {price} "
                            f"(触发价: {stop_order.trigger_price})"
                        )
                
                if triggered:
                    # 创建平仓订单
                    order = Order(
                        symbol=symbol,
                        side="sell",
                        quantity=stop_order.quantity or 0,
                        order_type="market"
                    )
                    triggered_orders.append(order)
                    orders_to_remove.append((symbol, stop_order.order_id))
        
        # 移除已触发的订单
        for symbol, order_id in orders_to_remove:
            self.cancel_stop(order_id)
        
        return triggered_orders
    
    def on_position_update(self, position: Position) -> None:
        """持仓更新时检查追踪止损"""
        symbol = position.symbol
        price = position.current_price
        
        if symbol not in self._stop_orders:
            return
        
        # 更新追踪止损
        for stop_order in self._stop_orders[symbol]:
            if stop_order.stop_type == StopType.TRAILING:
                if price > stop_order.peak_price:
                    stop_order.peak_price = price
                    new_trigger = price * (1 - stop_order.trailing_pct)
                    if new_trigger > stop_order.trigger_price:
                        stop_order.trigger_price = new_trigger
    
    def get_active_stops(self, symbol: Optional[str] = None) -> List[StopOrder]:
        """获取活跃的止损/止盈订单"""
        if symbol:
            return self._stop_orders.get(symbol, []).copy()
        
        all_stops = []
        for orders in self._stop_orders.values():
            all_stops.extend(orders)
        return all_stops
    
    def clear_stops(self, symbol: Optional[str] = None) -> None:
        """清除止损/止盈订单"""
        if symbol:
            if symbol in self._stop_orders:
                del self._stop_orders[symbol]
        else:
            self._stop_orders.clear()


# 便捷创建函数
def create_stop_loss_module() -> StopLossModule:
    """创建止损模块实例"""
    return StopLossModule()
