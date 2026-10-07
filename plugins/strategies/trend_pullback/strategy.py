"""
多时间周期的趋势回踩策略
4H: EMA20 > EMA50 > EMA200 且 ADX > 20
15m: 回踩EMA20，缩量，恢复阳线突破前高入场
止盈：1R 减30%，2R 减40%，余仓跟踪
止损：最近低点下方且 >= 1.2ATR
"""

from typing import Optional, Dict, Any
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.strategy.base_strategy import BaseStrategy, StrategyContext, Signal, SignalType


class TrendPullbackStrategy(BaseStrategy):
    """趋势回踩接力策略"""

    name = "Trend Pullback Strategy"
    version = "1.0.0"
    description = "多周期顺势回踩，多段止盈"
    author = "AI Agent"

    required_indicators = ["ema", "atr", "adx"]

    def __init__(
        self,
        timeframe_ratio: int = 16, # 默认15m K线，4H的倍数
        tp1_ratio: float = 0.30,
        tp2_ratio: float = 0.40,
        sl_atr_multiplier: float = 1.2,
        **kwargs
    ):
        super().__init__(
            timeframe_ratio=timeframe_ratio,
            tp1_ratio=tp1_ratio,
            tp2_ratio=tp2_ratio,
            sl_atr_multiplier=sl_atr_multiplier,
            **kwargs
        )
        self.timeframe_ratio = timeframe_ratio
        self.tp1_ratio = tp1_ratio
        self.tp2_ratio = tp2_ratio
        self.sl_atr_multiplier = sl_atr_multiplier
        
        # 记录持仓状态
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

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close']
        
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        tr_smooth = pd.Series(tr).ewm(alpha=1/period, adjust=False).mean()
        plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / tr_smooth
        minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / tr_smooth
        
        dx = 100 * (plus_di - minus_di).abs() / ((plus_di + minus_di).replace(0, 1))
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        return adx

    def on_bar(self, context: StrategyContext) -> Optional[Signal]:
        for symbol in self.symbols or context.bars.keys():
            bars = context.get_bars(symbol, count=1000)
            if bars is None or len(bars) < 200:
                continue

            current_price = context.get_last_price(symbol) or 0.0
            position = context.get_position(symbol)

            # --- 1. 持仓管理 (止损/止盈/追踪) ---
            if position > 0 and symbol in self._pos_state:
                state = self._pos_state[symbol]
                entry_price = state['entry_price']
                sl_price = state['sl_price']
                risk = state.get('initial_risk', entry_price - sl_price) # 获取锁定的初始风险
                
                # 触发止损或追踪止损
                if current_price <= sl_price:
                    signal = Signal(
                        symbol=symbol, signal_type=SignalType.SELL, 
                        price=current_price, 
                        reason=f"止损/追踪触发: 现价({current_price}) < 止损线({sl_price:.2f})"
                    )
                    del self._pos_state[symbol]
                    return signal
                
                # 检查第一止盈 (1R)
                if not state['tp1_hit'] and current_price >= entry_price + risk:
                    state['tp1_hit'] = True
                    state['sl_price'] = entry_price  # 保本
                    sell_qty = position * self.tp1_ratio
                    return Signal(
                        symbol=symbol, signal_type=SignalType.SELL, 
                        price=current_price, quantity=sell_qty, 
                        reason="1R目标完成，减仓30%，止损推保本"
                    )
                
                # 检查第二止盈 (2R)
                if state['tp1_hit'] and not state['tp2_hit'] and current_price >= entry_price + risk * 2:
                    state['tp2_hit'] = True
                    state['sl_price'] = entry_price + risk  # 止损推至 1R
                    # 之前由于卖掉 tp1_ratio，剩余 (1-tp1)，所以要卖出 tp2/剩余 才能卖出绝对的 40% 原仓量
                    sell_ratio_of_current = self.tp2_ratio / (1.0 - self.tp1_ratio)
                    sell_qty = position * sell_ratio_of_current
                    return Signal(
                        symbol=symbol, signal_type=SignalType.SELL, 
                        price=current_price, quantity=sell_qty, 
                        reason="2R目标完成，减仓40%，止损推至1R"
                    )
                
                # 当所有止盈完成后进入余仓追踪模式
                if state['tp2_hit']:
                    recent_lows = bars['low'].iloc[-5:].min()
                    # 简单移动低点追踪
                    if recent_lows > state['sl_price']:
                        state['sl_price'] = max(state['sl_price'], recent_lows - (risk * 0.2))

                continue  # 继续监控直到平仓
            
            # 若为空仓清除僵尸数据
            if position <= 0 and symbol in self._pos_state:
                del self._pos_state[symbol]

            # --- 2. 寻找入场条件 ---
            close = bars['close']
            open_p = bars['open']
            high = bars['high']
            low = bars['low']
            vol = bars['volume']

            ema20 = close.ewm(span=20, adjust=False).mean()
            atr = self._calculate_atr(bars, 14)

            # 条件A. 收出恢复阳线，且收盘突破前一根高点
            bullish_reversal = (close.iloc[-1] > open_p.iloc[-1]) and (close.iloc[-1] > high.iloc[-2])
            if not bullish_reversal:
                continue

            # 条件B. 回踩EMA20
            # 这里宽松地判断最近5根K线是否有下破或触碰EMA20
            touched_ema20 = (low.iloc[-5:] <= ema20.iloc[-5:]).any()
            if not touched_ema20:
                continue

            # 条件C. 回踩缩量
            # 判断下跌过程的总体成交量平均 是否低于近期平均量
            vol_sma20 = vol.rolling(20).mean()
            pullback_bars = bars.iloc[-5:-1]
            down_bars = pullback_bars[pullback_bars['close'] < pullback_bars['open']]
            if len(down_bars) > 0:
                avg_down_vol = down_bars['volume'].mean()
                if avg_down_vol > vol_sma20.iloc[-2]:  # 量未缩，过滤
                    continue
            
            # 条件D. 4H大级别趋势 (这里通过近似换算模拟大级别指标，避免强行Resample引起时间戳不对齐)
            # 因为15m里，20EMA≈320EMA, 50EMA≈800EMA，200需要3200(未必有足够数据，故这里我们折中或者直接降级算)
            p_ema20 = 20 * self.timeframe_ratio
            p_ema50 = 50 * self.timeframe_ratio
            if len(close) > p_ema50:
                htf_ema20 = close.ewm(span=p_ema20, adjust=False).mean().iloc[-1]
                htf_ema50 = close.ewm(span=p_ema50, adjust=False).mean().iloc[-1]
                # 有些用户获取不到足够长的数据(如200*16=3200)，如果有就用
                if len(close) > 200 * self.timeframe_ratio:
                    htf_ema200 = close.ewm(span=200 * self.timeframe_ratio, adjust=False).mean().iloc[-1]
                    trend_ok = (htf_ema20 > htf_ema50 > htf_ema200)
                else:
                    trend_ok = (htf_ema20 > htf_ema50) and (close.iloc[-1] > htf_ema20)
                
                # ADX在HTF的近似
                adx = self._calculate_adx(bars, 14 * self.timeframe_ratio)
                trend_ok = trend_ok and (adx.iloc[-1] > 20)
            else:
                # 极端不够长的情况下降级判断
                htf_ema20 = close.ewm(span=min(100, len(close)), adjust=False).mean().iloc[-1]
                trend_ok = (close.iloc[-1] > htf_ema20)

            if not trend_ok:
                continue

            # --- 3. 产生做多信号 ---
            current_atr = atr.iloc[-1]
            recent_low = low.iloc[-10:].min()
            
            # 止损：最近低点下方且至少1.2 ATR距离
            min_sl_dist = self.sl_atr_multiplier * current_atr
            sl_price_recent = recent_low - (current_atr * 0.1) # 低点适当缓冲
            sl_price_atr = current_price - min_sl_dist
            
            # 止损放在更低的位置
            final_sl_price = min(sl_price_recent, sl_price_atr)
            
            if final_sl_price >= current_price:
                continue # 安全校验

            # 记录入场信息用于后续止损止盈策略验证
            self._pos_state[symbol] = {
                'entry_price': current_price,
                'sl_price': final_sl_price,
                # 记录初始风险(1R)距离
                'initial_risk': current_price - final_sl_price,
                'tp1_hit': False,
                'tp2_hit': False
            }

            return Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                price=current_price,
                confidence=0.85,
                stop_loss=final_sl_price,
                reason=f"顺势回踩突破: 均线多头, 15m缩量企稳 (SL: {final_sl_price:.2f})"
            )

        return None
