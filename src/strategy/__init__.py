"""
KlineDock - 策略层模块

提供策略基类、加载器和运行器
"""

from src.strategy.base_strategy import (
    BaseStrategy,
    StrategyContext,
    Signal,
    SignalType
)
from src.strategy.strategy_loader import (
    StrategyLoader,
    StrategyMeta,
    strategy_loader
)
from src.strategy.strategy_runner import (
    StrategyRunner,
    RunnerConfig,
    RunnerState,
    BacktestResult,
    PerformanceMetrics,
    SignalProcessor,
    signal_processor
)

__all__ = [
    # 基类
    "BaseStrategy",
    "StrategyContext",
    "Signal",
    "SignalType",
    
    # 加载器
    "StrategyLoader",
    "StrategyMeta",
    "strategy_loader",
    
    # 运行器
    "StrategyRunner",
    "RunnerConfig",
    "RunnerState",
    "BacktestResult",
    "PerformanceMetrics",
    
    # 信号处理
    "SignalProcessor",
    "signal_processor",
]
