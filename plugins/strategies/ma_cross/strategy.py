"""
双均线交叉策略 - 示例插件

经典的技术指标策略：
- 快线上穿慢线时产生买入信号
- 快线下穿慢线时产生卖出信号
"""

from typing import Optional
import pandas as pd

import sys
from pathlib import Path
# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.strategy.base_strategy import BaseStrategy, StrategyContext, Signal, SignalType


class MACrossStrategy(BaseStrategy):
    """双均线交叉策略"""
    
    name = "MA Cross Strategy"
    version = "1.0.0"
    description = "经典双均线交叉策略"
    author = "KlineDock"
    
    required_indicators = ["sma", "ema"]
    
    
    def __init__(
        self, 
        fast_period: int = 10, 
        slow_period: int = 30,
        ma_type: str = "sma",
        stop_loss_pct: float = 0.05,    # 默认5%止损
        take_profit_pct: float = 0.10,  # 默认10%止盈
        **kwargs
    ):
        super().__init__(
            fast_period=fast_period,
            slow_period=slow_period,
            ma_type=ma_type,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            **kwargs
        )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.ma_type = ma_type
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 上一根K线的均线值，用于判断交叉
        self._prev_fast: Optional[float] = None
        self._prev_slow: Optional[float] = None
        
        # 记录持仓成本 (模拟)
        self._entry_prices: dict = {}
    
    def _calculate_ma(self, series: pd.Series, period: int) -> pd.Series:
        """计算移动平均线"""
        if self.ma_type == "ema":
            return series.ewm(span=period, adjust=False).mean()
        else:  # sma
            return series.rolling(window=period).mean()
    
    def on_bar(self, context: StrategyContext) -> Optional[Signal]:
        """每根K线调用一次"""
        
        # 遍历所有交易对
        for symbol in self.symbols or context.bars.keys():
            current_price = context.get_last_price(symbol) or 0.0
            if current_price == 0:
                continue
                
            position = context.get_position(symbol)
            
            # --- 止盈止损逻辑 (策略内实现) ---
            if position > 0 and symbol in self._entry_prices:
                entry_price = self._entry_prices[symbol]
                
                # 止损检查
                if current_price <= entry_price * (1 - self.stop_loss_pct):
                    signal = Signal(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        price=current_price,
                        reason=f"止损触发: 现价({current_price}) < 止损线({entry_price * (1 - self.stop_loss_pct):.2f})"
                    )
                    del self._entry_prices[symbol]
                    return signal

                # 止盈检查
                if current_price >= entry_price * (1 + self.take_profit_pct):
                    signal = Signal(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        price=current_price,
                        reason=f"止盈触发: 现价({current_price}) > 止盈线({entry_price * (1 + self.take_profit_pct):.2f})"
                    )
                    del self._entry_prices[symbol]
                    return signal
            
            # --- 原有均线逻辑 ---
            bars = context.get_bars(symbol, self.slow_period + 10)
            
            if bars is None or len(bars) < self.slow_period:
                continue
            
            close = bars["close"]
            
            # 计算均线
            fast_ma = self._calculate_ma(close, self.fast_period)
            slow_ma = self._calculate_ma(close, self.slow_period)
            
            current_fast = fast_ma.iloc[-1]
            current_slow = slow_ma.iloc[-1]
            
            # 第一次运行，记录当前值
            if self._prev_fast is None:
                self._prev_fast = current_fast
                self._prev_slow = current_slow
                continue
            
            signal = None
            
            # 金叉：快线从下方穿越慢线
            if self._prev_fast <= self._prev_slow and current_fast > current_slow:
                if position <= 0:  # 无持仓或空仓时买入
                    signal = Signal(
                        symbol=symbol,
                        signal_type=SignalType.BUY,
                        price=current_price,
                        confidence=0.8,
                        stop_loss=current_price * (1 - self.stop_loss_pct),
                        take_profit=current_price * (1 + self.take_profit_pct),
                        reason=f"金叉: 快线({current_fast:.2f}) 上穿 慢线({current_slow:.2f})"
                    )
                    self._entry_prices[symbol] = current_price
            
            # 死叉：快线从上方穿越慢线
            elif self._prev_fast >= self._prev_slow and current_fast < current_slow:
                if position > 0:  # 有多仓时卖出
                    signal = Signal(
                        symbol=symbol,
                        signal_type=SignalType.SELL,
                        price=current_price,
                        confidence=0.8,
                        reason=f"死叉: 快线({current_fast:.2f}) 下穿 慢线({current_slow:.2f})"
                    )
                    if symbol in self._entry_prices:
                        del self._entry_prices[symbol]
            
            # 更新历史值
            self._prev_fast = current_fast
            self._prev_slow = current_slow
            
            if signal:
                return signal
        
        return None
