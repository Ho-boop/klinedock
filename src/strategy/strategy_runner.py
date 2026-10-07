"""
KlineDock - 策略运行器

执行策略逻辑，处理信号和管理策略生命周期
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
from src.strategy.base_strategy import BaseStrategy, StrategyContext, Signal, SignalType


class RunnerState(str, Enum):
    """运行器状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RunnerConfig:
    """运行器配置"""
    # 运行模式
    backtest_mode: bool = False
    paper_mode: bool = True
    
    # 数据配置
    symbols: List[str] = field(default_factory=list)
    interval: str = "1h"
    
    # 执行配置
    process_signals: bool = True
    emit_events: bool = True
    
    # 回测配置
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    initial_capital: float = 100000.0
    commission_rate: float = 0.001


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    config: RunnerConfig
    metrics: PerformanceMetrics
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: Optional[pd.DataFrame] = None
    signals: List[Signal] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    market_data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        # 转换市场数据
        market_data_dict = {}
        if self.market_data:
            for symbol, data_obj in self.market_data.items():
                if isinstance(data_obj, dict):
                    if hasattr(self.config, 'interval') and self.config.interval in data_obj:
                        df = data_obj[self.config.interval]
                    else:
                        df = list(data_obj.values())[0] if data_obj else None
                else:
                    df = data_obj
                    
                if df is None or getattr(df, 'empty', True):
                    continue
                
                # 转换为ECharts友好的列表格式: [timestamp_str, open, close, low, high, volume]
                data_list = []
                for index, row in df.iterrows():
                    ts_str = index.strftime("%Y-%m-%d %H:%M")
                    data_list.append({
                        "time": ts_str,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"])
                    })
                market_data_dict[symbol] = data_list

        # 序列化交易记录
        serialized_trades = []
        for t in self.trades:
            t_copy = t.copy()
            if isinstance(t_copy.get("timestamp"), datetime):
                t_copy["timestamp"] = t_copy["timestamp"].strftime("%Y-%m-%d %H:%M")
            serialized_trades.append(t_copy)

        return {
            "strategy_name": self.strategy_name,
            "metrics": {
                "total_return": f"{self.metrics.total_return:.2%}",
                "sharpe_ratio": f"{self.metrics.sharpe_ratio:.2f}",
                "max_drawdown": f"{self.metrics.max_drawdown:.2%}",
                "win_rate": f"{self.metrics.win_rate:.2%}",
                "total_trades": self.metrics.total_trades
            },
            "period": {
                "start": self.start_time.isoformat() if self.start_time else None,
                "end": self.end_time.isoformat() if self.end_time else None
            },
            "trades": serialized_trades,
            "equity_curve": [{'time': t['datetime'].strftime("%Y-%m-%d %H:%M"), 'value': t['equity']} for t in self.equity_curve.reset_index().to_dict('records')] if self.equity_curve is not None and not self.equity_curve.empty else [],
            "market_data": market_data_dict
        }


class StrategyRunner:
    """
    策略运行器
    
    功能:
    - 执行策略的on_bar/on_tick方法
    - 管理策略上下文
    - 处理和发布信号
    - 本地回测执行
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        config: Optional[RunnerConfig] = None
    ):
        """
        初始化运行器
        
        Args:
            strategy: 策略实例
            config: 运行器配置
        """
        self.strategy = strategy
        self.config = config or RunnerConfig()
        
        # 状态
        self._state = RunnerState.IDLE
        self._context: Optional[StrategyContext] = None
        
        # 信号和交易记录
        self._signals: List[Signal] = []
        self._trades: List[Dict[str, Any]] = []
        
        # 回测用
        self._equity_curve: List[Dict[str, Any]] = []
        self._current_equity = self.config.initial_capital
        
        # 回调
        self._signal_callbacks: List[Callable[[Signal], None]] = []
    
    @property
    def state(self) -> RunnerState:
        return self._state
    
    @property
    def is_running(self) -> bool:
        return self._state == RunnerState.RUNNING
    
    def create_context(
        self,
        bars: Dict[str, Dict[str, pd.DataFrame]],
        positions: Optional[Dict[str, float]] = None,
        balance: float = 0.0
    ) -> StrategyContext:
        """创建策略上下文"""
        return StrategyContext(
            positions=positions or {},
            balance=balance or self.config.initial_capital,
            equity=balance or self.config.initial_capital,
            bars=bars,
            base_interval=self.config.interval,
            is_backtest=self.config.backtest_mode,
            parameters=self.strategy.parameters
        )
    
    def on_signal(self, callback: Callable[[Signal], None]) -> None:
        """注册信号回调"""
        self._signal_callbacks.append(callback)
    
    def _emit_signal(self, signal: Signal) -> None:
        """发射信号"""
        self._signals.append(signal)
        
        # 调用回调
        for callback in self._signal_callbacks:
            try:
                callback(signal)
            except Exception as e:
                logger.error(f"信号回调执行失败: {e}")
        
        # 发布事件
        if self.config.emit_events:
            event_bus.publish(Event(
                event_type=EventType.STRATEGY_SIGNAL,
                data={
                    "strategy": self.strategy.name,
                    "signal": signal
                },
                source="strategy_runner"
            ))
    
    async def run_bar(
        self,
        bars: Dict[str, Dict[str, pd.DataFrame]],
        context: Optional[StrategyContext] = None
    ) -> Optional[Signal]:
        """
        执行单根K线
        
        Args:
            bars: K线数据字典
            context: 策略上下文（可选）
            
        Returns:
            Signal: 生成的信号
        """
        if self._state not in (RunnerState.IDLE, RunnerState.RUNNING):
            logger.warning(f"运行器状态异常: {self._state}")
            return None
        
        # 创建或更新上下文
        if context:
            self._context = context
        else:
            self._context = self.create_context(
                bars=bars,
                balance=self._current_equity
            )
        
        # 初始化策略（首次运行）
        if not self.strategy._initialized:
            self.strategy.initialize(self._context)
        
        self._state = RunnerState.RUNNING
        
        try:
            # 执行策略
            signal = self.strategy.on_bar(self._context)
            
            # 处理信号
            if signal:
                self._emit_signal(signal)
            
            # 获取策略发出的待处理信号
            pending_signals = self.strategy.get_pending_signals()
            for s in pending_signals:
                self._emit_signal(s)
            
            return signal
            
        except Exception as e:
            logger.error(f"策略执行失败: {e}")
            self._state = RunnerState.ERROR
            return None
    
    async def backtest(
        self,
        data: Dict[str, Any],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> BacktestResult:
        """
        执行回测
        
        Args:
            data: 历史数据字典 {symbol: DataFrame} 或是 {symbol: {interval: DataFrame}}
            start: 开始时间
            end: 结束时间
            
        Returns:
            BacktestResult: 回测结果
        """
        logger.info(f"开始回测: {self.strategy.name}")
        
        self.config.backtest_mode = True
        self._state = RunnerState.RUNNING
        
        # 初始化
        self._signals.clear()
        self._trades.clear()
        self._equity_curve.clear()
        self._balance = self.config.initial_capital
        self._current_equity = self.config.initial_capital
        
        # 兼容旧格式并标准化 data (统一转成 {symbol: {interval: DataFrame}})
        normalized_data: Dict[str, Dict[str, pd.DataFrame]] = {}
        for k, v in data.items():
            if isinstance(v, pd.DataFrame):
                normalized_data[k] = {self.config.interval: v}
            else:
                normalized_data[k] = v
        data = normalized_data
        
        if not data:
            return BacktestResult(
                strategy_name=self.strategy.name,
                config=self.config,
                metrics=PerformanceMetrics()
            )
        
        first_symbol = list(data.keys())[0]
        # 寻找用来驱动时间的 base_interval DataFrame
        if self.config.interval in data[first_symbol]:
            df = data[first_symbol][self.config.interval]
        else:
            first_int = list(data[first_symbol].keys())[0]
            df = data[first_symbol][first_int]
        
        # 过滤时间范围
        if start:
            df = df[df.index >= start]
        if end:
            df = df[df.index <= end]
        
        actual_start = df.index[0] if len(df) > 0 else None
        actual_end = df.index[-1] if len(df) > 0 else None
        
        # 模拟持仓明细 (包含均价)
        positions_state: Dict[str, Dict[str, float]] = {}
        
        # 遍历每根K线
        for i in range(len(df)):
            # 防止密集计算完全阻塞 AsyncIO 事件循环导致前端 WebSocket 掉线
            if i % 50 == 0:
                await asyncio.sleep(0.001)
                
            # 截取历史数据
            current_bars = {}
            for symbol, symbol_data in data.items():
                current_bars[symbol] = {}
                current_idx = df.index[i]
                for interval_key, symbol_df in symbol_data.items():
                    current_bars[symbol][interval_key] = symbol_df[symbol_df.index <= current_idx]
            
            # 仅传递持仓数量给策略计算上下文
            context_positions = {sym: state["qty"] for sym, state in positions_state.items() if state["qty"] != 0}
            
            # 标记最新价格
            current_prices = {}
            for sym, sym_data in current_bars.items():
                if sym_data:
                    base_int = self.config.interval if self.config.interval in sym_data else list(sym_data.keys())[0]
                    if not sym_data[base_int].empty:
                        current_prices[sym] = float(sym_data[base_int]["close"].iloc[-1])
            
            # 记录当前执行策略前动态权益
            current_equity = self._balance
            for sym, state in positions_state.items():
                if state["qty"] != 0 and sym in current_prices:
                    if state["qty"] > 0:
                        current_equity += (current_prices[sym] - state["avg_price"]) * state["qty"]
                    else:
                        current_equity += (state["avg_price"] - current_prices[sym]) * abs(state["qty"])
            self._current_equity = current_equity
            
            # 创建上下文
            context = StrategyContext(
                positions=context_positions,
                balance=self._balance,
                equity=self._current_equity,
                bars=current_bars,
                current_time=df.index[i],
                is_backtest=True,
                parameters=self.strategy.parameters
            )
            
            # 提取执行前的信号长度，用于捕捉该K线中生成的所有新信号
            prev_signals_count = len(self._signals)
            
            # 执行策略
            await self.run_bar(current_bars, context)
            
            # 获取新增加的信号列表并一次性执行
            new_signals = self._signals[prev_signals_count:]
            for s in new_signals:
                self._simulate_trade(s, context, positions_state)
            
            # 执行后，按更新的持仓和余额再次统计K线周期的结束权益（用以绘制曲线）
            final_equity = self._balance
            for sym, state in positions_state.items():
                if state["qty"] != 0 and sym in current_prices:
                    if state["qty"] > 0:
                        final_equity += (current_prices[sym] - state["avg_price"]) * state["qty"]
                    else:
                        final_equity += (state["avg_price"] - current_prices[sym]) * abs(state["qty"])
            self._current_equity = final_equity
            
            # 记录权益曲线
            self._equity_curve.append({
                "datetime": df.index[i],
                "equity": self._current_equity
            })
        
        self._state = RunnerState.STOPPED
        
        # 计算绩效
        metrics = self._calculate_metrics()
        
        # 生成权益曲线DataFrame
        equity_df = pd.DataFrame(self._equity_curve)
        if not equity_df.empty:
            equity_df.set_index("datetime", inplace=True)
        
        result = BacktestResult(
            strategy_name=self.strategy.name,
            config=self.config,
            metrics=metrics,
            trades=self._trades.copy(),
            equity_curve=equity_df,
            signals=self._signals.copy(),
            start_time=actual_start,
            end_time=actual_end,
            market_data=data
        )
        
        logger.info(f"回测完成: {result.strategy_name}, trades={len(result.trades)}, bars={len(df)}")
        return result
    
    def _simulate_trade(self, signal: Signal, context: StrategyContext, positions_state: Dict[str, Dict[str, float]]) -> None:
        """真实逻辑模拟交易执行"""
        if getattr(signal, 'price', 0) > 0:
            price = signal.price
        else:
            price = context.get_last_price(signal.symbol)
            if not price:
                return
        
        qty = signal.quantity or 0.1
        fee = price * qty * self.config.commission_rate
        
        if signal.symbol not in positions_state:
            positions_state[signal.symbol] = {"qty": 0.0, "avg_price": 0.0}
        pos = positions_state[signal.symbol]
        
        # 真实会计模拟
        realized_pnl = 0.0
        if signal.signal_type == SignalType.BUY:
            if pos["qty"] < 0: # 正在做空，则为买入平空
                close_qty = min(abs(pos["qty"]), qty)
                realized_pnl = (pos["avg_price"] - price) * close_qty
                pos["qty"] += close_qty
                # 剩余的数量转为多头
                rem_qty = qty - close_qty
                if rem_qty > 0:
                    pos["avg_price"] = price # 反手了，新的均价就是现价
                    pos["qty"] += rem_qty
            else:
                # 纯粹加/开多
                new_qty = pos["qty"] + qty
                pos["avg_price"] = (pos["qty"] * pos["avg_price"] + qty * price) / new_qty if new_qty > 0 else 0
                pos["qty"] = new_qty
        
        elif signal.signal_type == SignalType.SELL:
            if pos["qty"] > 0: # 正在做多，则为卖出平多
                close_qty = min(pos["qty"], qty)
                realized_pnl = (price - pos["avg_price"]) * close_qty
                pos["qty"] -= close_qty
                # 剩余的数量转为空头
                rem_qty = qty - close_qty
                if rem_qty > 0:
                    pos["avg_price"] = price
                    pos["qty"] -= rem_qty
            else:
                # 纯粹加/开空
                new_qty = abs(pos["qty"]) + qty
                pos["avg_price"] = (abs(pos["qty"]) * pos["avg_price"] + qty * price) / new_qty if new_qty > 0 else 0
                pos["qty"] -= qty

        elif signal.signal_type == SignalType.CLOSE_LONG:
            if pos["qty"] > 0:
                close_qty = pos["qty"] if qty <= 0 else min(pos["qty"], qty)
                realized_pnl = (price - pos["avg_price"]) * close_qty
                pos["qty"] -= close_qty
                qty = close_qty # 为了记录实际成交量
                
        elif signal.signal_type == SignalType.CLOSE_SHORT:
            if pos["qty"] < 0:
                close_qty = abs(pos["qty"]) if qty <= 0 else min(abs(pos["qty"]), qty)
                realized_pnl = (pos["avg_price"] - price) * close_qty
                pos["qty"] += close_qty
                qty = close_qty
        
        # 余额变更: 扣除手续费并叠加已实现盈亏
        self._balance += (realized_pnl - fee)
        
        trade = {
            "timestamp": context.current_time,
            "symbol": signal.symbol,
            "side": signal.signal_type.value,
            "price": price,
            "quantity": qty,
            "value": price * qty,
            "reason": signal.reason,
            "realized_pnl": realized_pnl,
            "fee": fee
        }
        self._trades.append(trade)
    
    def _calculate_metrics(self) -> PerformanceMetrics:
        """计算绩效指标"""
        metrics = PerformanceMetrics()
        
        if not self._equity_curve:
            return metrics
        
        initial = self.config.initial_capital
        final = self._current_equity
        
        # 总收益
        metrics.total_return = (final - initial) / initial
        
        # 交易统计
        metrics.total_trades = len(self._trades)
        
        # 简单的胜率计算
        if metrics.total_trades > 0:
            # 这里需要更复杂的逻辑来判断盈亏交易
            metrics.winning_trades = sum(1 for t in self._trades if t["side"] == "sell")
            metrics.losing_trades = metrics.total_trades - metrics.winning_trades
            metrics.win_rate = metrics.winning_trades / metrics.total_trades if metrics.total_trades > 0 else 0
        
        # 最大回撤
        if self._equity_curve:
            equities = [e["equity"] for e in self._equity_curve]
            peak = equities[0]
            max_dd = 0
            for eq in equities:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd
            metrics.max_drawdown = max_dd
        
        return metrics
    
    async def stop(self) -> None:
        """停止运行器"""
        if self._state == RunnerState.RUNNING:
            self.strategy.on_stop(self._context)
        
        self._state = RunnerState.STOPPED
        logger.info(f"策略运行器已停止: {self.strategy.name}")
    
    def get_signals(self) -> List[Signal]:
        """获取所有信号"""
        return self._signals.copy()
    
    def get_trades(self) -> List[Dict[str, Any]]:
        """获取所有交易"""
        return self._trades.copy()


class SignalProcessor:
    """
    信号处理器
    
    功能:
    - 聚合多策略信号
    - 信号过滤和验证
    - 信号优先级排序
    """
    
    def __init__(self):
        self._pending_signals: List[Signal] = []
        self._processed_signals: List[Signal] = []
        self._filters: List[Callable[[Signal], bool]] = []
    
    def add_filter(self, filter_func: Callable[[Signal], bool]) -> None:
        """添加信号过滤器"""
        self._filters.append(filter_func)
    
    def submit(self, signal: Signal) -> None:
        """提交信号"""
        self._pending_signals.append(signal)
    
    def process(self) -> List[Signal]:
        """
        处理待处理信号
        
        Returns:
            List[Signal]: 通过过滤的信号列表
        """
        valid_signals = []
        
        for signal in self._pending_signals:
            # 应用所有过滤器
            passed = True
            for filter_func in self._filters:
                try:
                    if not filter_func(signal):
                        passed = False
                        break
                except Exception as e:
                    logger.error(f"过滤器执行失败: {e}")
                    passed = False
            
            if passed:
                valid_signals.append(signal)
        
        # 按置信度排序
        valid_signals.sort(key=lambda s: s.confidence, reverse=True)
        
        # 移动到已处理
        self._processed_signals.extend(valid_signals)
        self._pending_signals.clear()
        
        return valid_signals
    
    def clear(self) -> None:
        """清空所有信号"""
        self._pending_signals.clear()
        self._processed_signals.clear()


# 全局信号处理器
signal_processor = SignalProcessor()
