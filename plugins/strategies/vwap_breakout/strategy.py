"""
KlineDock - VWAP放量突破策略
多周期融合：1D大趋势，4H中期结构，15m入场点
"""

from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.strategy.base_strategy import BaseStrategy, StrategyContext, Signal, SignalType


class VwapBreakoutStrategy(BaseStrategy):
    """VWAP放量突破策略"""

    name = "VWAP Breakout Strategy"
    version = "1.0.0"
    description = "多周期VWAP放量突破策略"
    author = "AI Agent"

    required_indicators = ["atr", "ema", "vwap"]

    def __init__(
        self,
        body_ratio_threshold: float = 0.6,
        **kwargs
    ):
        super().__init__(
            body_ratio_threshold=body_ratio_threshold,
            **kwargs
        )
        self.body_ratio_threshold = body_ratio_threshold
        
        # 内部状态管理
        self._pos_state: Dict[str, Dict[str, Any]] = {}

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close_prev = df['close'].shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vol = df['volume']
        
        # 按日锚定
        if not hasattr(df.index, 'date'):
            dates = pd.to_datetime(df.index).date
        else:
            dates = df.index.date
            
        tp_vol = typical_price * vol
        vwap = tp_vol.groupby(dates).cumsum() / vol.groupby(dates).cumsum()
        return vwap

    def on_bar(self, context: StrategyContext) -> Optional[Signal]:
        for symbol in self.symbols or context.bars.keys():
            # 需要至少 1920 根 K线才能准确计算 1D EMA20 (1D = 96根15m)
            # 但为保证系统不会因数据不足而崩溃，我们请求2000根
            bars = context.get_bars(symbol, count=2500)
            if bars is None or len(bars) < 100:
                continue

            current_price = context.get_last_price(symbol) or 0.0
            position = context.get_position(symbol)

            # === 1. 出场规则判定 ===
            if position != 0 and symbol in self._pos_state:
                state = self._pos_state[symbol]
                state['bars_since_entry'] += 1
                bars_held = state['bars_since_entry']
                
                # 做多出场
                if position > 0 and state['side'] == 'long':
                    stop_price = state['stop_price']
                    tp1_price = state['tp1_price']
                    entry_price = state['entry_price']
                    risk = state['risk']
                    
                    # 1. 初始极值止损
                    if current_price <= stop_price:
                        del self._pos_state[symbol]
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason="做多初始极值止损")
                        
                    # 2. 分批止盈 1.5R 减半
                    if not state['tp1_hit'] and current_price >= tp1_price:
                        state['tp1_hit'] = True
                        qty = position * 0.5
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, quantity=qty, reason="做多到达1.5R，平仓50%")
                        
                    # 3. 余仓吊灯跟踪止损
                    if state['tp1_hit']:
                        recent_highest = bars['high'].iloc[-22:].max()
                        atr_now = self._calculate_atr(bars.iloc[-30:], 14).iloc[-1]
                        trailing_line = recent_highest - 1.5 * atr_now
                        
                        if current_price < trailing_line:
                            del self._pos_state[symbol]
                            return Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason="做多余额触发吊灯止损")
                            
                    # 4. 时间止损
                    if bars_held == 6 and current_price < entry_price + 0.5 * risk:
                        del self._pos_state[symbol]
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason="做多时间止损 (6根K线未达0.5R)")
                        
                # 做空出场
                elif position < 0 and state['side'] == 'short':
                    stop_price = state['stop_price']
                    tp1_price = state['tp1_price']
                    entry_price = state['entry_price']
                    risk = state['risk']
                    
                    # 1. 初始极值止损
                    if current_price >= stop_price:
                        del self._pos_state[symbol]
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason="做空初始极值止损")
                        
                    # 2. 分批止盈 1.5R 减半
                    if not state['tp1_hit'] and current_price <= tp1_price:
                        state['tp1_hit'] = True
                        qty = abs(position) * 0.5
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, quantity=qty, reason="做空到达1.5R，平仓50%")
                        
                    # 3. 余仓吊灯跟踪止损
                    if state['tp1_hit']:
                        recent_lowest = bars['low'].iloc[-22:].min()
                        atr_now = self._calculate_atr(bars.iloc[-30:], 14).iloc[-1]
                        trailing_line = recent_lowest + 1.5 * atr_now
                        
                        if current_price > trailing_line:
                            del self._pos_state[symbol]
                            return Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason="做空余额触发吊灯止损")
                            
                    # 4. 时间止损
                    if bars_held == 6 and current_price > entry_price - 0.5 * risk:
                        del self._pos_state[symbol]
                        return Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason="做空时间止损 (6根K线未达0.5R)")
                        
                # 仍在持仓中，跳过入场逻辑
                continue

            # 当前空仓清除僵尸状态
            if position == 0 and symbol in self._pos_state:
                del self._pos_state[symbol]


            # === 2. 入场规则判定 ===
            close = bars['close']
            open_p = bars['open']
            high = bars['high']
            low = bars['low']
            vol = bars['volume']
            
            # --- 指标计算 ---
            # 1D EMA20: 1天=96根15mK线
            ema20_1d_period = 20 * 96
            if len(close) > ema20_1d_period:
                ema20_1d = close.ewm(span=ema20_1d_period, adjust=False).mean()
            else:
                ema20_1d = close.ewm(span=len(close), adjust=False).mean()
            current_ema20_1d = ema20_1d.iloc[-1]
            current_close_1d = close.iloc[-1] # 用最新价近似日线级收盘价
            
            # 4H 结构: 20根4H = 320根15mK线
            hh_20_4h_period = 320
            if len(high) > hh_20_4h_period:
                hh_20_4h_prev = high.shift(1).rolling(hh_20_4h_period).max().iloc[-1]
                ll_20_4h_prev = low.shift(1).rolling(hh_20_4h_period).min().iloc[-1]
            else:
                hh_20_4h_prev = high.shift(1).rolling(len(high)-1).max().iloc[-1]
                ll_20_4h_prev = low.shift(1).rolling(len(low)-1).min().iloc[-1]
                
            # 15m VWAP, ATR, Vol SMA
            atr = self._calculate_atr(bars, 14)
            current_atr = atr.iloc[-1]
            
            vwap = self._calculate_vwap(bars)
            current_vwap = vwap.iloc[-1]
            
            vol_sma20 = vol.rolling(20).mean()
            prev_vol_sma20 = vol_sma20.iloc[-2]
            prev_vol = vol.iloc[-2]
            
            # 实体比例
            body = (close.iloc[-1] - open_p.iloc[-1])
            kline_range = high.iloc[-1] - low.iloc[-1]
            if kline_range == 0:
                body_ratio = 0
            else:
                body_ratio = abs(body) / kline_range

            # --- 做多逻辑判定 ---
            long_cond_1 = current_close_1d > current_ema20_1d
            long_cond_2 = current_price > hh_20_4h_prev
            
            # 回踩VWAP +- 0.5 ATR
            long_cond_3_pullback = (low.iloc[-1] <= current_vwap + 0.5 * current_atr) and (low.iloc[-1] >= current_vwap - 0.5 * current_atr)
            long_cond_3_shrink = prev_vol < prev_vol_sma20
            long_cond_3 = long_cond_3_pullback and long_cond_3_shrink
            
            # 触发：强阳，饱满，破前两高
            long_cond_4_green = close.iloc[-1] > open_p.iloc[-1]
            long_cond_4_body = body_ratio >= self.body_ratio_threshold
            long_cond_4_break = close.iloc[-1] > max(high.iloc[-2], high.iloc[-3])
            long_cond_4 = long_cond_4_green and long_cond_4_body and long_cond_4_break
            
            if long_cond_1 and long_cond_2 and long_cond_3 and long_cond_4:
                signal_low = low.iloc[-1]
                stop_price = signal_low - 0.2 * current_atr
                risk = current_price - stop_price
                
                if risk > 0:
                    tp1_price = current_price + 1.5 * risk
                    
                    self._pos_state[symbol] = {
                        'entry_price': current_price,
                        'signal_low': signal_low,
                        'stop_price': stop_price,
                        'risk': risk,
                        'tp1_price': tp1_price,
                        'tp1_hit': False,
                        'bars_since_entry': 0,
                        'side': 'long'
                    }
                    
                    return Signal(
                        symbol=symbol, 
                        signal_type=SignalType.BUY, 
                        price=current_price, 
                        confidence=0.9,
                        stop_loss=stop_price,
                        take_profit=tp1_price,
                        reason=f"多头VWAP突破 (SL={stop_price:.2f}, TP1={tp1_price:.2f})"
                    )

            # --- 做空逻辑判定 ---
            short_cond_1 = current_close_1d < current_ema20_1d
            short_cond_2 = current_price < ll_20_4h_prev
            
            # 反抽VWAP +- 0.5 ATR
            short_cond_3_pullback = (high.iloc[-1] >= current_vwap - 0.5 * current_atr) and (high.iloc[-1] <= current_vwap + 0.5 * current_atr)
            short_cond_3_shrink = prev_vol < prev_vol_sma20
            short_cond_3 = short_cond_3_pullback and short_cond_3_shrink
            
            # 触发：强阴，饱满，破前两低
            short_cond_4_red = close.iloc[-1] < open_p.iloc[-1]
            short_cond_4_body = body_ratio >= self.body_ratio_threshold
            short_cond_4_break = close.iloc[-1] < min(low.iloc[-2], low.iloc[-3])
            short_cond_4 = short_cond_4_red and short_cond_4_body and short_cond_4_break
            
            if short_cond_1 and short_cond_2 and short_cond_3 and short_cond_4:
                signal_high = high.iloc[-1]
                stop_price = signal_high + 0.2 * current_atr
                risk = stop_price - current_price
                
                if risk > 0:
                    tp1_price = current_price - 1.5 * risk
                    
                    self._pos_state[symbol] = {
                        'entry_price': current_price,
                        'signal_high': signal_high,
                        'stop_price': stop_price,
                        'risk': risk,
                        'tp1_price': tp1_price,
                        'tp1_hit': False,
                        'bars_since_entry': 0,
                        'side': 'short'
                    }
                    
                    return Signal(
                        symbol=symbol, 
                        signal_type=SignalType.SELL, 
                        price=current_price,
                        confidence=0.9,
                        stop_loss=stop_price,
                        take_profit=tp1_price,
                        reason=f"空头VWAP突破 (SL={stop_price:.2f}, TP1={tp1_price:.2f})"
                    )

        return None
