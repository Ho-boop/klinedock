"""
KlineDock - 策略基类

所有策略插件必须继承此基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import pandas as pd


class SignalType(str, Enum):
    """信号类型"""
    BUY = "buy"           # 买入
    SELL = "sell"         # 卖出
    HOLD = "hold"         # 持有
    CLOSE_LONG = "close_long"   # 平多
    CLOSE_SHORT = "close_short" # 平空


@dataclass
class Signal:
    """交易信号"""
    symbol: str
    signal_type: SignalType
    price: float = 0.0
    quantity: float = 0.0
    take_profit: float = 0.0
    stop_loss: float = 0.0
    confidence: float = 1.0    # 信号置信度 0-1
    reason: str = ""           # 信号原因
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyContext:
    """策略上下文，包含策略运行所需的所有信息"""
    
    # 当前持仓
    positions: Dict[str, float] = field(default_factory=dict)
    
    # 账户信息
    balance: float = 0.0
    equity: float = 0.0
    available_margin: float = 0.0
    
    # 历史数据: {symbol: {interval: pd.DataFrame}}
    bars: Dict[str, Dict[str, pd.DataFrame]] = field(default_factory=dict)
    
    # 当前时间
    current_time: datetime = field(default_factory=datetime.now)
    
    # 是否回测模式
    is_backtest: bool = False
    
    # 策略参数
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # 默认的主时间周期
    base_interval: str = "1h"
    
    def get_position(self, symbol: str) -> float:
        """获取持仓数量"""
        return self.positions.get(symbol, 0.0)
    
    def get_bars(self, symbol: str, count: int = 100, interval: Optional[str] = None) -> Optional[pd.DataFrame]:
        """获取历史K线
         Args:
             symbol: 标的名称
             count: 获取数量
             interval: 周期 (例如 '1m', '15m', '1h'等). 如果不填默认使用 base_interval
        """
        interval = interval or self.base_interval
        if symbol not in self.bars or getattr(self.bars[symbol], 'empty', False):
            # 若仍是旧格式 (symbol直接映射df) 的防弹设计
            if isinstance(self.bars.get(symbol), pd.DataFrame):
                return self.bars[symbol].tail(count)
            return None
        
        if interval not in self.bars[symbol]:
            # 回退机制：如果没有该周期，取任一存在周期的最后一批数据
            if self.bars[symbol]:
                first_int = list(self.bars[symbol].keys())[0]
                return self.bars[symbol][first_int].tail(count)
            return None
            
        df = self.bars[symbol][interval]
        return df.tail(count)
    
    def get_last_price(self, symbol: str, interval: Optional[str] = None) -> Optional[float]:
        """获取最新价格"""
        interval = interval or self.base_interval
        if symbol not in self.bars:
            return None
            
        # 兼容旧格式
        if isinstance(self.bars[symbol], pd.DataFrame):
            if self.bars[symbol].empty: return None
            return float(self.bars[symbol]["close"].iloc[-1])
            
        if not self.bars[symbol]:
            return None
            
        if interval in self.bars[symbol] and not self.bars[symbol][interval].empty:
            return float(self.bars[symbol][interval]["close"].iloc[-1])
            
        # 如果对应的周期为空或不存在，尝试任意有数据的周期
        for k, v in self.bars[symbol].items():
            if not v.empty:
                return float(v["close"].iloc[-1])
        return None


class BaseStrategy(ABC):
    """
    策略基类
    
    所有策略插件必须继承此类并实现 on_bar 方法
    """
    
    # 策略元信息
    name: str = "BaseStrategy"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    
    # 策略依赖的指标
    required_indicators: List[str] = []
    
    # 策略支持的交易对
    symbols: List[str] = []
    
    def __init__(self, **parameters):
        """
        初始化策略
        
        Args:
            **parameters: 策略参数，会覆盖默认值
        """
        self.parameters = parameters
        self._signals: List[Signal] = []
        self._initialized = False
    
    def initialize(self, context: StrategyContext) -> None:
        """
        策略初始化（可选覆盖）
        
        在策略首次运行时调用一次
        """
        self._initialized = True
    
    @abstractmethod
    def on_bar(self, context: StrategyContext) -> Optional[Signal]:
        """
        K线事件处理（必须实现）
        
        每根新K线到来时调用
        
        Args:
            context: 策略上下文
            
        Returns:
            Signal: 交易信号，如无信号返回None
        """
        pass
    
    def on_tick(self, context: StrategyContext, tick: Dict[str, Any]) -> Optional[Signal]:
        """
        Tick事件处理（可选覆盖）
        
        每个Tick到来时调用，用于高频策略
        """
        return None
    
    def on_order_filled(self, context: StrategyContext, order: Dict[str, Any]) -> None:
        """
        订单成交事件（可选覆盖）
        """
        pass
    
    def on_stop(self, context: StrategyContext) -> None:
        """
        策略停止事件（可选覆盖）
        """
        pass
    
    def emit_signal(self, signal: Signal) -> None:
        """发出信号"""
        self._signals.append(signal)
    
    def get_pending_signals(self) -> List[Signal]:
        """获取并清空待处理信号"""
        signals = self._signals.copy()
        self._signals.clear()
        return signals
    
    def get_parameter(self, name: str, default: Any = None) -> Any:
        """获取策略参数"""
        return self.parameters.get(name, default)
    
    def __repr__(self) -> str:
        return f"<{self.name} v{self.version}>"
