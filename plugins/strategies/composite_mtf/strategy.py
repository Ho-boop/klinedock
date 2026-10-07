"""
Multi-timeframe Composite Strategy V2 (多周期复合策略 - 改良版)
包含 1D 趋势过滤, 4H 结构突破, 15m 量价结合入场的交易策略原型
"""

from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
from src.strategy.base_strategy import BaseStrategy, StrategyContext, Signal, SignalType

class CompositeMultiTimeframeStrategy(BaseStrategy):
    """
    多周期复合策略 (15m, 4H, 1D) 改良版
    
    信号触发:
    - 结合 1D 趋势 (EMA20)
    - 4H 阻力/支撑 突破 (HH_20 / LL_20)
    - 15m 量价回调, VWAP 附近确认等
    - 订单执行: 限价单 (Limit Buy/Short), TTL=3根K线
    - 出场管理: 初始结构止损(依据VWAP和ATR快照), TP1平半仓推保本损, TP2清仓, 降级版时间止损
    """
    name = "Composite MTF Strategy"
    version = "2.0.0"
    description = "多周期复合策略V2 - 改良的风控出场与限价入场网络"
    author = "KlineDock"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # 记录内部挂单与持仓状态
        # 结构: {symbol: order_info}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        # 结构: {symbol: position_info}
        self._trade_states: Dict[str, Dict[str, Any]] = {}

    def _calculate_ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        q = df['volume']
        p = (df['high'] + df['low'] + df['close']) / 3
        return (p * q).rolling(window=20).sum() / q.rolling(window=20).sum()

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()
        
    def _cancel_order(self, symbol: str):
        """模拟撤销未成交的挂单"""
        if symbol in self.pending_orders:
            del self.pending_orders[symbol]

    def on_bar(self, context: StrategyContext) -> Optional[Signal]:
        """K线数据触发核心逻辑 - 以 15m 作为基准驱动周期"""
        
        symbols = self.symbols or list(context.bars.keys())
        signal_to_return = None
        
        for symbol in symbols:
            # 1. 调阅多周期数据
            df_15m = context.get_bars(symbol, count=50, interval="15m")
            df_4h = context.get_bars(symbol, count=25, interval="4h")
            df_1d = context.get_bars(symbol, count=25, interval="1d")
            
            # 容错：跳过不足的数据
            if df_15m is None or len(df_15m) < 22: continue
            if df_4h is None or len(df_4h) < 21: continue
            if df_1d is None or len(df_1d) < 21: continue
            
            current_price = df_15m['close'].iloc[-1]
            pos_qty = context.get_position(symbol)
            
            # 判断挂单有效期 (TTL) 与成交模拟
            # 如果有挂单，且未成交：
            if symbol in self.pending_orders:
                order = self.pending_orders[symbol]
                
                # 检查是否能够成交（在当前 15m K线内触发 limit 价格）
                # 这里做简单模拟：最低价如果低于买单价，则买单成交；最高价高于卖单价，则卖单成交。
                executed = False
                if order['side'] == SignalType.BUY and df_15m['low'].iloc[-1] <= order['limit_price']:
                    executed = True
                elif order['side'] == SignalType.SELL and df_15m['high'].iloc[-1] >= order['limit_price']:
                    executed = True
                    
                if executed:
                    # 真正发单！并在内部状态机登记这笔订单的初始风控快照
                    self._trade_states[symbol] = {
                        "entry_price": order['limit_price'],
                        "side": order['side'],
                        "sl_price": order['sl_price'],
                        "risk": order['risk'],
                        "tp1_target": order['tp1_target'],
                        "tp2_target": order['tp2_target'],
                        "tp1_hit": False,
                        "bars_held": 0
                    }
                    signal_to_return = Signal(
                        symbol=symbol,
                        signal_type=order['side'],
                        price=order['limit_price'],  # 以 Limit 挂单价成交
                        reason=f"限价单触发成交 {order['side'].value} @ {order['limit_price']:.4f}"
                    )
                    self._cancel_order(symbol)
                    if signal_to_return: return signal_to_return
                    
                else: # 未成交，处理 TTL
                    order['ttl'] -= 1
                    if order['ttl'] <= 0:
                        self._cancel_order(symbol)
            
            
            # 如果有净持仓，更新持仓生命周期并判断出场
            if symbol in self._trade_states and pos_qty != 0:
                state = self._trade_states[symbol]
                state['bars_held'] += 1
                
                entry_price = state['entry_price']
                risk = state['risk']
                
                # ------ 多头出场逻辑 ------
                if state['side'] == SignalType.BUY and pos_qty > 0:
                    # 1. 结构止损 / 保本损 (Stop Loss / Breakeven Stop)
                    if current_price <= state['sl_price']:
                        reason_msg = "[保本出局] 市价平多" if state['tp1_hit'] else "[止损] 结构止损触发平多"
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason=reason_msg)
                        del self._trade_states[symbol]
                        return signal_to_return
                    
                    # 2. 分批止盈 (TP1 平半仓)
                    if not state['tp1_hit'] and current_price >= state['tp1_target']:
                        state['tp1_hit'] = True
                        # 触发后立刻推保本损
                        state['sl_price'] = entry_price
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, quantity=abs(pos_qty)*0.5, price=current_price, reason="[TP1止盈] 止盈50%且推保本损")
                        return signal_to_return
                    
                    # 3. 终极止盈 (TP2)
                    if state['tp1_hit'] and current_price >= state['tp2_target']:
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason="[TP2止盈] 到达终极目标平多")
                        del self._trade_states[symbol]
                        return signal_to_return
                    
                    # 4. 时间止损 (Time Stop - 持有达到 6 K线)
                    if state['bars_held'] >= 6 and current_price < entry_price + (0.2 * risk):
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_LONG, price=current_price, reason=f"[时间止损] 6K线不及预期动能平多")
                        del self._trade_states[symbol]
                        return signal_to_return

                # ------ 空头出场逻辑 ------
                elif state['side'] == SignalType.SELL and pos_qty < 0:
                    # 1. 结构止损 / 保本损
                    if current_price >= state['sl_price']:
                        reason_msg = "[保本出局] 市价平空" if state['tp1_hit'] else "[止损] 结构止损触发平空"
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason=reason_msg)
                        del self._trade_states[symbol]
                        return signal_to_return
                    
                    # 2. 分批止盈 (TP1 平半仓)
                    if not state['tp1_hit'] and current_price <= state['tp1_target']:
                        state['tp1_hit'] = True
                        # 一旦扫过 TP1立刻推保本损
                        state['sl_price'] = entry_price
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, quantity=abs(pos_qty)*0.5, price=current_price, reason="[TP1止盈] 止盈50%且推保本损")
                        return signal_to_return
                    
                    # 3. 终极止盈 (TP2)
                    if state['tp1_hit'] and current_price <= state['tp2_target']:
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason="[TP2止盈] 到达终极目标平空")
                        del self._trade_states[symbol]
                        return signal_to_return
                    
                    # 4. 时间止损
                    if state['bars_held'] >= 6 and current_price > entry_price - (0.2 * risk):
                        signal_to_return = Signal(symbol=symbol, signal_type=SignalType.CLOSE_SHORT, price=current_price, reason=f"[时间止损] 6K线不及预期动能平空")
                        del self._trade_states[symbol]
                        return signal_to_return
            
            # 状态重置机制 (避免错乱)
            if pos_qty == 0 and symbol in self._trade_states:
                del self._trade_states[symbol] # 清理过期凭证
            
            # --- 风控限制: 若存在持仓，忽略一切新信号 ---
            if pos_qty != 0:
                continue
                

            # ========================= 入场信号逻辑计算 =========================
            
            # 因子计算 - 15m
            atr_15m_ds = self._calculate_atr(df_15m, 14)
            vwap_15m_ds = self._calculate_vwap(df_15m)
            vol_sma20 = df_15m['volume'].rolling(20).mean()
            
            curr_low_15 = df_15m['low'].iloc[-1]
            curr_high_15 = df_15m['high'].iloc[-1]
            curr_close_15 = df_15m['close'].iloc[-1]
            curr_open_15 = df_15m['open'].iloc[-1]
            
            curr_atr_15 = atr_15m_ds.iloc[-1]
            curr_vwap_15 = vwap_15m_ds.iloc[-1]
            prev_vol_15 = df_15m['volume'].iloc[-2]
            prev_vol_sma_15 = vol_sma20.iloc[-2]
            
            prev_high_15 = df_15m['high'].iloc[-2]
            prev_high2_15 = df_15m['high'].iloc[-3]
            prev_low_15 = df_15m['low'].iloc[-2]
            prev_low2_15 = df_15m['low'].iloc[-3]
            
            body_ratio = abs(curr_close_15 - curr_open_15) / (curr_high_15 - curr_low_15) if curr_high_15 != curr_low_15 else 0
            
            # 因子计算 - 4H
            curr_close_4h = df_4h['close'].iloc[-1]
            hh_20_4h_prev = df_4h['high'].iloc[-21:-1].max() # 前20根最高点
            ll_20_4h_prev = df_4h['low'].iloc[-21:-1].min()  # 前20根最低点
            
            # 因子计算 - 1D
            ema20_1d = self._calculate_ema(df_1d['close'], 20).iloc[-1]
            curr_close_1d = df_1d['close'].iloc[-1]


            # ------ 做多条件判断 ------
            cond_long_1d = curr_close_1d > ema20_1d
            cond_long_4h = curr_close_4h > hh_20_4h_prev
            cond_long_15_vwap = (curr_low_15 <= curr_vwap_15 + 0.5 * curr_atr_15) and (curr_low_15 >= curr_vwap_15 - 0.5 * curr_atr_15)
            cond_long_15_vol = prev_vol_15 < prev_vol_sma_15
            cond_long_15_shape = (curr_close_15 > curr_open_15) and (body_ratio >= 0.6) and (curr_close_15 > max(prev_high_15, prev_high2_15))
            
            if cond_long_1d and cond_long_4h and cond_long_15_vwap and cond_long_15_vol and cond_long_15_shape:
                # 记录快照点极值
                signal_low = curr_low_15
                signal_high = curr_high_15
                vwap_snapshot = curr_vwap_15
                atr_snapshot = curr_atr_15
                
                limit_price = signal_low + (signal_high - signal_low) * 0.5
                sl_price = vwap_snapshot - (1.0 * atr_snapshot)
                
                if limit_price > sl_price:
                    risk = limit_price - sl_price
                    tp1_target = limit_price + (1.5 * risk)
                    tp2_target = limit_price + (3.0 * risk)
                    
                    # 挂单互斥：有新信号则直接覆盖取消旧挂单
                    self.pending_orders[symbol] = {
                        "side": SignalType.BUY,
                        "limit_price": limit_price,
                        "sl_price": sl_price,
                        "risk": risk,
                        "tp1_target": tp1_target,
                        "tp2_target": tp2_target,
                        "ttl": 3 # 3根15m K线的有效期
                    }
                    continue


            # ------ 做空条件判断 ------
            cond_short_1d = curr_close_1d < ema20_1d
            cond_short_4h = curr_close_4h < ll_20_4h_prev
            cond_short_15_vwap = (curr_high_15 >= curr_vwap_15 - 0.5 * curr_atr_15) and (curr_high_15 <= curr_vwap_15 + 0.5 * curr_atr_15)
            cond_short_15_vol = prev_vol_15 < prev_vol_sma_15
            cond_short_15_shape = (curr_close_15 < curr_open_15) and (body_ratio >= 0.6) and (curr_close_15 < min(prev_low_15, prev_low2_15))
            
            if cond_short_1d and cond_short_4h and cond_short_15_vwap and cond_short_15_vol and cond_short_15_shape:
                signal_low = curr_low_15
                signal_high = curr_high_15
                vwap_snapshot = curr_vwap_15
                atr_snapshot = curr_atr_15
                
                limit_price = signal_high - (signal_high - signal_low) * 0.5
                sl_price = vwap_snapshot + (1.0 * atr_snapshot)
                
                if sl_price > limit_price:
                    risk = sl_price - limit_price
                    tp1_target = limit_price - (1.5 * risk)
                    tp2_target = limit_price - (3.0 * risk)
                    
                    # 登记新的空头委托挂单覆盖
                    self.pending_orders[symbol] = {
                        "side": SignalType.SELL,
                        "limit_price": limit_price,
                        "sl_price": sl_price,
                        "risk": risk,
                        "tp1_target": tp1_target,
                        "tp2_target": tp2_target,
                        "ttl": 3
                    }
                
        return signal_to_return
