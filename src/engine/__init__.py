"""
KlineDock - 引擎层模块

提供回测、模拟盘和实盘交易引擎
"""

from src.engine.backtest_runner import (
    BacktestRunner,
    BacktestConfig,
    LEANOrchestrator,
    backtest_runner,
    lean_orchestrator
)
from src.engine.paper_engine import (
    PaperEngine,
    EngineState,
    VirtualAccount,
    paper_engine
)
from src.engine.live_engine import (
    LiveEngine,
    OrderResult,
    live_engine
)

__all__ = [
    # 回测
    "BacktestRunner",
    "BacktestConfig",
    "LEANOrchestrator",
    "backtest_runner",
    "lean_orchestrator",
    
    # 模拟盘
    "PaperEngine",
    "EngineState",
    "VirtualAccount",
    "paper_engine",
    
    # 实盘
    "LiveEngine",
    "OrderResult",
    "live_engine",
]
