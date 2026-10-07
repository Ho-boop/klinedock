"""
KlineDock - 模拟盘引擎

无真实资金风险的交易模拟
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import pandas as pd
from loguru import logger

from src.core.config import get_config
from src.core.event_bus import event_bus, Event, EventType
from src.strategy import BaseStrategy, StrategyContext, Signal, SignalType
from src.risk import (
    RiskEngine, RiskContext, Order, Position,
    create_position_control, create_stop_loss_module
)


class EngineState(str, Enum):
    """引擎状态"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class VirtualAccount:
    """虚拟账户"""
    balance: float = 10000.0
    initial_balance: float = 10000.0
    positions: Dict[str, Position] = field(default_factory=dict)
    pending_orders: List[Order] = field(default_factory=list)
    filled_orders: List[Order] = field(default_factory=list)
    
    @property
    def equity(self) -> float:
        """账户权益"""
        position_value = sum(p.market_value for p in self.positions.values())
        return self.balance + position_value
    
    @property
    def unrealized_pnl(self) -> float:
        """未实现盈亏"""
        return sum(p.unrealized_pnl for p in self.positions.values())
    
    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.equity - self.initial_balance
    
    @property
    def return_rate(self) -> float:
        """收益率"""
        return self.total_pnl / self.initial_balance


class PaperEngine:
    """
    模拟盘引擎
    
    功能:
    - 虚拟账户管理
    - 订单模拟执行
    - 持仓跟踪
    - 与风控系统集成
    """
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005
    ):
        """
        初始化模拟盘
        
        Args:
            initial_balance: 初始资金
            commission_rate: 手续费率
            slippage_rate: 滑点率
        """
        self.config = get_config()
        
        # 交易参数
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        
        # 虚拟账户
        self.account = VirtualAccount(
            balance=initial_balance,
            initial_balance=initial_balance
        )
        
        # 状态
        self._state = EngineState.IDLE
        self._strategy: Optional[BaseStrategy] = None
        self._context: Optional[StrategyContext] = None
        
        # 风控
        self._risk_engine = RiskEngine()
        self._risk_engine.register(create_position_control())
        self._risk_engine.register(create_stop_loss_module())
        
        # 数据
        self._current_prices: Dict[str, float] = {}
        self._bars: Dict[str, pd.DataFrame] = {}
        
        # 任务
        self._run_task: Optional[asyncio.Task] = None
        
        # 回调
        self._on_trade_callbacks: List[Callable] = []
        self._on_signal_callbacks: List[Callable] = []
    
    @property
    def state(self) -> EngineState:
        return self._state
    
    @property
    def is_running(self) -> bool:
        return self._state == EngineState.RUNNING
    
    def on_trade(self, callback: Callable[[Order], None]) -> None:
        """注册交易回调"""
        self._on_trade_callbacks.append(callback)
    
    def on_signal(self, callback: Callable[[Signal], None]) -> None:
        """注册信号回调"""
        self._on_signal_callbacks.append(callback)
    
    async def start(
        self,
        strategy: BaseStrategy,
        symbols: List[str],
        data_callback: Optional[Callable] = None
    ) -> None:
        """
        启动模拟盘
        
        Args:
            strategy: 策略实例
            symbols: 交易标的列表
            data_callback: 数据回调（用于获取实时数据）
        """
        if self._state == EngineState.RUNNING:
            logger.warning("模拟盘已在运行")
            return
        
        self._state = EngineState.STARTING
        self._strategy = strategy
        
        # 初始化上下文
        self._context = StrategyContext(
            positions={s: 0.0 for s in symbols},
            balance=self.account.balance,
            equity=self.account.equity,
            bars=self._bars,
            is_backtest=False,
            parameters=strategy.parameters
        )
        
        # 初始化策略
        if not strategy._initialized:
            strategy.initialize(self._context)
        
        self._state = EngineState.RUNNING
        logger.info(f"模拟盘已启动: {strategy.name}")
        
        # 发布事件
        event_bus.publish(Event(
            event_type=EventType.STRATEGY_START,
            data={"strategy": strategy.name, "mode": "paper"},
            source="paper_engine"
        ))
    
    async def stop(self) -> None:
        """停止模拟盘"""
        if self._state != EngineState.RUNNING:
            return
        
        self._state = EngineState.STOPPING
        
        if self._strategy:
            self._strategy.on_stop(self._context)
        
        self._state = EngineState.STOPPED
        logger.info("模拟盘已停止")
        
        # 发布事件
        event_bus.publish(Event(
            event_type=EventType.STRATEGY_STOP,
            data={"mode": "paper"},
            source="paper_engine"
        ))
    
    async def on_bar(self, symbol: str, bar: pd.Series) -> Optional[Signal]:
        """
        处理新K线
        
        Args:
            symbol: 交易对
            bar: K线数据
            
        Returns:
            Signal: 生成的信号
        """
        if not self.is_running or not self._strategy:
            return None
        
        # 更新当前价格
        current_price = float(bar.get("close", 0))
        self._current_prices[symbol] = current_price
        
        # 更新持仓价格
        if symbol in self.account.positions:
            self.account.positions[symbol].update_price(current_price)
        
        # 更新上下文
        self._update_context()
        
        # 执行策略
        try:
            signal = self._strategy.on_bar(self._context)
            
            if signal:
                self._handle_signal(signal)
            
            # 处理策略发出的待处理信号
            for s in self._strategy.get_pending_signals():
                self._handle_signal(s)
            
            return signal
            
        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            self._state = EngineState.ERROR
            return None
    
    def _update_context(self) -> None:
        """更新策略上下文"""
        if not self._context:
            return
        
        # 更新账户信息
        self._context.balance = self.account.balance
        self._context.equity = self.account.equity
        
        # 更新持仓
        self._context.positions = {
            s: p.quantity for s, p in self.account.positions.items()
        }
        
        # 更新K线数据
        self._context.bars = self._bars
        self._context.current_time = datetime.now()
    
    def _handle_signal(self, signal: Signal) -> None:
        """处理交易信号"""
        # 调用回调
        for callback in self._on_signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                logger.error(f"信号回调失败: {e}")
        
        # 创建订单
        order = Order(
            symbol=signal.symbol,
            side="buy" if signal.signal_type == SignalType.BUY else "sell",
            quantity=signal.quantity,
            price=signal.price or self._current_prices.get(signal.symbol, 0)
        )
        
        # 提交订单
        self.submit_order(order)
    
    def submit_order(self, order: Order) -> bool:
        """
        提交订单
        
        Args:
            order: 订单
            
        Returns:
            bool: 是否成功
        """
        # 风控检查
        risk_context = RiskContext(
            balance=self.account.balance,
            equity=self.account.equity,
            positions=self.account.positions
        )
        
        self._risk_engine.update_context(
            balance=self.account.balance,
            equity=self.account.equity
        )
        
        result = self._risk_engine.check_order(order)
        
        if not result.passed:
            logger.warning(f"订单被风控拒绝: {result.reason}")
            return False
        
        # 模拟执行
        return self._execute_order(order)
    
    def _execute_order(self, order: Order) -> bool:
        """模拟执行订单"""
        price = order.price or self._current_prices.get(order.symbol, 0)
        
        if price <= 0:
            logger.error(f"无效价格: {order.symbol}")
            return False
        
        # 计算滑点
        if order.side == "buy":
            exec_price = price * (1 + self.slippage_rate)
        else:
            exec_price = price * (1 - self.slippage_rate)
        
        # 计算交易金额和手续费
        trade_value = exec_price * order.quantity
        commission = trade_value * self.commission_rate
        
        if order.side == "buy":
            # 检查资金
            total_cost = trade_value + commission
            if total_cost > self.account.balance:
                logger.warning(f"资金不足: 需要 {total_cost:.2f}, 可用 {self.account.balance:.2f}")
                return False
            
            # 扣除资金
            self.account.balance -= total_cost
            
            # 更新持仓
            if order.symbol in self.account.positions:
                pos = self.account.positions[order.symbol]
                # 计算新均价
                total_qty = pos.quantity + order.quantity
                total_cost = pos.cost + trade_value
                pos.avg_price = total_cost / total_qty
                pos.quantity = total_qty
            else:
                self.account.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=order.quantity,
                    avg_price=exec_price,
                    current_price=exec_price
                )
        
        else:  # sell
            # 检查持仓
            if order.symbol not in self.account.positions:
                logger.warning(f"无持仓: {order.symbol}")
                return False
            
            pos = self.account.positions[order.symbol]
            if pos.quantity < order.quantity:
                logger.warning(f"持仓不足: 需要 {order.quantity}, 可用 {pos.quantity}")
                return False
            
            # 计算实现盈亏
            realized_pnl = (exec_price - pos.avg_price) * order.quantity
            pos.realized_pnl += realized_pnl
            
            # 收入资金
            self.account.balance += trade_value - commission
            
            # 更新持仓
            pos.quantity -= order.quantity
            if pos.quantity <= 0:
                del self.account.positions[order.symbol]
        
        # 记录成交
        order.price = exec_price
        order.timestamp = datetime.now()
        self.account.filled_orders.append(order)
        
        logger.info(
            f"订单成交: {order.side.upper()} {order.quantity} {order.symbol} "
            f"@ {exec_price:.4f}, 手续费: {commission:.4f}"
        )
        
        # 调用回调
        for callback in self._on_trade_callbacks:
            try:
                callback(order)
            except Exception as e:
                logger.error(f"交易回调失败: {e}")
        
        # 发布事件
        event_bus.publish(Event(
            event_type=EventType.ORDER_FILLED,
            data={
                "order": order,
                "price": exec_price,
                "commission": commission
            },
            source="paper_engine"
        ))
        
        return True
    
    def get_virtual_balance(self) -> float:
        """获取虚拟余额"""
        return self.account.balance
    
    def get_virtual_equity(self) -> float:
        """获取虚拟权益"""
        return self.account.equity
    
    def get_virtual_positions(self) -> Dict[str, Position]:
        """获取虚拟持仓"""
        return self.account.positions.copy()
    
    def get_trade_history(self) -> List[Order]:
        """获取交易历史"""
        return self.account.filled_orders.copy()
    
    def get_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        return {
            "balance": self.account.balance,
            "equity": self.account.equity,
            "unrealized_pnl": self.account.unrealized_pnl,
            "total_pnl": self.account.total_pnl,
            "return_rate": f"{self.account.return_rate:.2%}",
            "positions": len(self.account.positions),
            "trades": len(self.account.filled_orders)
        }
    
    def reset(self) -> None:
        """重置账户"""
        initial = self.account.initial_balance
        self.account = VirtualAccount(
            balance=initial,
            initial_balance=initial
        )
        self._state = EngineState.IDLE
        logger.info("模拟盘已重置")


# 全局模拟盘实例
paper_engine = PaperEngine()
