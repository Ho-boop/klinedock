"""
KlineDock - 仓位控制模块

实现仓位限制和敞口控制
"""

from dataclasses import dataclass
from typing import Dict, Optional, Any
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
from src.core.config import RiskConfig


class PositionControl(BaseRiskModule):
    """
    仓位控制模块
    
    功能:
    - 单标的仓位限制
    - 总敞口控制
    - 订单频率限制
    - 单笔订单金额限制
    """
    
    name = "PositionControl"
    description = "仓位控制风控模块"
    priority = 5  # 最高优先级
    
    def __init__(self, config: Optional[RiskConfig] = None):
        super().__init__(config)
        
        # 从配置读取限制
        self.max_single_position_pct = self.config.max_single_position_pct
        self.max_total_exposure_pct = self.config.max_total_exposure_pct
        self.max_leverage = self.config.max_leverage
        self.max_order_value = self.config.max_order_value_usdt
        self.max_orders_per_minute = self.config.max_orders_per_minute
        
        # 订单频率追踪
        self._recent_orders: list = []
    
    def check_order(self, order: Order, context: RiskContext) -> RiskCheckResult:
        """
        综合检查订单
        
        检查项:
        1. 单笔订单金额
        2. 单标的仓位限制
        3. 总敞口限制
        4. 订单频率
        """
        # 1. 检查单笔订单金额
        result = self._check_order_value(order, context)
        if not result.passed:
            return result
        
        # 2. 检查单标的仓位
        result = self._check_position_limit(order, context)
        if not result.passed:
            return result
        
        # 3. 检查总敞口
        result = self._check_exposure_limit(order, context)
        if not result.passed:
            return result
        
        # 4. 检查订单频率
        result = self._check_order_frequency(order, context)
        if not result.passed:
            return result
        
        return RiskCheckResult.approve("仓位控制检查通过")
    
    def _check_order_value(
        self,
        order: Order,
        context: RiskContext
    ) -> RiskCheckResult:
        """检查单笔订单金额"""
        # 估算订单价值
        price = order.price or 0
        if price == 0:
            # 市价单，使用持仓当前价格估算
            pos = context.get_position(order.symbol)
            if pos:
                price = pos.current_price
        
        if price == 0:
            # 无法估算，允许通过
            return RiskCheckResult.approve()
        
        order_value = price * order.quantity
        
        if order_value > self.max_order_value:
            return RiskCheckResult.reject(
                f"订单金额 {order_value:.2f} 超过限制 {self.max_order_value}",
                RiskLevel.MEDIUM
            )
        
        return RiskCheckResult.approve()
    
    def _check_position_limit(
        self,
        order: Order,
        context: RiskContext
    ) -> RiskCheckResult:
        """检查单标的仓位限制"""
        if order.side != "buy":
            # 卖出订单不检查
            return RiskCheckResult.approve()
        
        # 获取当前持仓
        current_position = context.get_position(order.symbol)
        current_value = current_position.market_value if current_position else 0
        
        # 估算订单后的仓位
        price = order.price or (current_position.current_price if current_position else 0)
        if price == 0:
            return RiskCheckResult.approve()
        
        new_position_value = current_value + (price * order.quantity)
        
        # 计算仓位比例
        if context.equity <= 0:
            return RiskCheckResult.reject("账户权益异常", RiskLevel.CRITICAL)
        
        position_pct = new_position_value / context.equity
        
        if position_pct > self.max_single_position_pct:
            max_qty = (self.max_single_position_pct * context.equity - current_value) / price
            return RiskCheckResult(
                passed=False,
                action=RiskAction.REDUCE,
                reason=f"仓位 {position_pct:.1%} 超过限制 {self.max_single_position_pct:.1%}",
                level=RiskLevel.MEDIUM,
                suggested_quantity=max(0, max_qty)
            )
        
        return RiskCheckResult.approve()
    
    def _check_exposure_limit(
        self,
        order: Order,
        context: RiskContext
    ) -> RiskCheckResult:
        """检查总敞口限制"""
        if order.side != "buy":
            return RiskCheckResult.approve()
        
        # 当前总敞口
        current_exposure = context.get_total_exposure()
        
        # 估算新增敞口
        price = order.price
        if not price:
            pos = context.get_position(order.symbol)
            price = pos.current_price if pos else 0
        
        if price == 0:
            return RiskCheckResult.approve()
        
        new_exposure = current_exposure + (price * order.quantity)
        
        if context.equity <= 0:
            return RiskCheckResult.reject("账户权益异常", RiskLevel.CRITICAL)
        
        exposure_ratio = new_exposure / context.equity
        
        if exposure_ratio > self.max_total_exposure_pct:
            return RiskCheckResult.reject(
                f"总敞口 {exposure_ratio:.1%} 超过限制 {self.max_total_exposure_pct:.1%}",
                RiskLevel.HIGH
            )
        
        return RiskCheckResult.approve()
    
    def _check_order_frequency(
        self,
        order: Order,
        context: RiskContext
    ) -> RiskCheckResult:
        """检查订单频率"""
        import time
        current_time = time.time()
        
        # 清理1分钟前的订单记录
        self._recent_orders = [
            t for t in self._recent_orders
            if current_time - t < 60
        ]
        
        if len(self._recent_orders) >= self.max_orders_per_minute:
            return RiskCheckResult.reject(
                f"订单频率超限（每分钟最多{self.max_orders_per_minute}单）",
                RiskLevel.MEDIUM
            )
        
        # 记录当前订单时间
        self._recent_orders.append(current_time)
        
        return RiskCheckResult.approve()
    
    def check_position_limit(
        self,
        symbol: str,
        quantity: float,
        current_positions: Dict[str, float],
        equity: float = 10000.0,
        price: float = 0.0
    ) -> RiskCheckResult:
        """
        便捷方法：检查仓位限制
        
        Args:
            symbol: 交易对
            quantity: 拟买入数量
            current_positions: 当前持仓 {symbol: quantity}
            equity: 账户权益
            price: 当前价格
        """
        if price <= 0:
            return RiskCheckResult.reject("价格无效", RiskLevel.MEDIUM)
        
        current_qty = current_positions.get(symbol, 0)
        new_qty = current_qty + quantity
        new_value = new_qty * price
        
        position_pct = new_value / equity
        
        if position_pct > self.max_single_position_pct:
            max_qty = (self.max_single_position_pct * equity / price) - current_qty
            return RiskCheckResult(
                passed=False,
                action=RiskAction.REDUCE,
                reason=f"仓位 {position_pct:.1%} 超过限制 {self.max_single_position_pct:.1%}",
                level=RiskLevel.MEDIUM,
                suggested_quantity=max(0, max_qty)
            )
        
        return RiskCheckResult.approve(f"仓位 {position_pct:.1%} 在限制内")
    
    def check_exposure(
        self,
        order_value: float,
        current_exposure: float,
        equity: float
    ) -> RiskCheckResult:
        """
        便捷方法：检查敞口
        
        Args:
            order_value: 订单价值
            current_exposure: 当前敞口
            equity: 账户权益
        """
        if equity <= 0:
            return RiskCheckResult.reject("权益无效", RiskLevel.CRITICAL)
        
        new_exposure = current_exposure + order_value
        exposure_pct = new_exposure / equity
        
        if exposure_pct > self.max_total_exposure_pct:
            return RiskCheckResult.reject(
                f"敞口 {exposure_pct:.1%} 超限 {self.max_total_exposure_pct:.1%}",
                RiskLevel.HIGH
            )
        
        return RiskCheckResult.approve(f"敞口 {exposure_pct:.1%} 在限制内")
    
    def calculate_position_size(
        self,
        symbol: str,
        price: float,
        context: RiskContext,
        risk_per_trade: float = 0.02
    ) -> float:
        """
        计算建议仓位大小
        
        Args:
            symbol: 交易对
            price: 当前价格
            context: 风控上下文
            risk_per_trade: 单次交易风险比例
            
        Returns:
            float: 建议买入数量
        """
        if price <= 0 or context.equity <= 0:
            return 0.0
        
        # 基于风险的仓位
        risk_capital = context.equity * risk_per_trade
        quantity_by_risk = risk_capital / price
        
        # 基于仓位限制
        current_pos = context.get_position(symbol)
        current_value = current_pos.market_value if current_pos else 0
        max_position_value = context.equity * self.max_single_position_pct
        remaining_capacity = max_position_value - current_value
        quantity_by_limit = remaining_capacity / price if remaining_capacity > 0 else 0
        
        # 基于敞口限制
        current_exposure = context.get_total_exposure()
        max_exposure = context.equity * self.max_total_exposure_pct
        remaining_exposure = max_exposure - current_exposure
        quantity_by_exposure = remaining_exposure / price if remaining_exposure > 0 else 0
        
        # 取最小值
        suggested = min(quantity_by_risk, quantity_by_limit, quantity_by_exposure)
        
        return max(0.0, suggested)


class DrawdownControl(BaseRiskModule):
    """
    回撤控制模块
    
    功能:
    - 日回撤监控
    - 周回撤监控
    - 策略停止线
    """
    
    name = "DrawdownControl"
    description = "回撤控制风控模块"
    priority = 3
    
    def __init__(self, config: Optional[RiskConfig] = None):
        super().__init__(config)
        
        # 从配置读取限制
        self.daily_max_dd = self.config.daily_max_drawdown_pct
        self.weekly_max_dd = self.config.weekly_max_drawdown_pct
        self.kill_dd = self.config.strategy_kill_drawdown_pct
        
        # 追踪变量
        self._day_start_equity = 0.0
        self._week_start_equity = 0.0
        self._peak_equity = 0.0
        self._is_paused = False
    
    def check_order(self, order: Order, context: RiskContext) -> RiskCheckResult:
        """如果已暂停则拒绝所有订单"""
        if self._is_paused:
            return RiskCheckResult.reject(
                "交易已暂停：回撤超限",
                RiskLevel.CRITICAL
            )
        return RiskCheckResult.approve()
    
    def on_pnl_update(self, pnl: float, equity: float) -> Optional[RiskAction]:
        """盈亏更新时检查回撤"""
        if self._peak_equity == 0:
            self._peak_equity = equity
            self._day_start_equity = equity
            self._week_start_equity = equity
        
        # 更新峰值
        if equity > self._peak_equity:
            self._peak_equity = equity
        
        # 计算回撤
        if self._peak_equity > 0:
            total_dd = (self._peak_equity - equity) / self._peak_equity
            
            # 检查策略停止线
            if total_dd >= self.kill_dd:
                self._is_paused = True
                logger.critical(f"触发策略停止线！回撤 {total_dd:.1%}")
                return RiskAction.KILL_SWITCH
        
        # 计算日回撤
        if self._day_start_equity > 0:
            daily_dd = (self._day_start_equity - equity) / self._day_start_equity
            if daily_dd >= self.daily_max_dd:
                self._is_paused = True
                logger.warning(f"触发日回撤限制！回撤 {daily_dd:.1%}")
                return RiskAction.CLOSE
        
        return None
    
    def reset_daily(self, current_equity: float) -> None:
        """重置日统计"""
        self._day_start_equity = current_equity
        self._is_paused = False
    
    def reset_weekly(self, current_equity: float) -> None:
        """重置周统计"""
        self._week_start_equity = current_equity
        self.reset_daily(current_equity)
    
    def resume(self) -> None:
        """恢复交易"""
        self._is_paused = False
        logger.info("交易已恢复")


# 便捷创建函数
def create_position_control() -> PositionControl:
    """创建仓位控制模块实例"""
    return PositionControl()


def create_drawdown_control() -> DrawdownControl:
    """创建回撤控制模块实例"""
    return DrawdownControl()
