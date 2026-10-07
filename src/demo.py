"""Deterministic synthetic OHLCV data and a real local strategy run."""
import numpy as np
import pandas as pd
from src.strategy import StrategyLoader, StrategyRunner, RunnerConfig

def synthetic_bars(count=180):
    t = np.arange(count, dtype=float)
    close = 100 + 0.02*t + 8*np.sin(t/7)
    frame = pd.DataFrame({"open":close-.1,"high":close+.5,"low":close-.5,"close":close,"volume":1000+t}, index=pd.date_range("2026-01-01",periods=count,freq="h"))
    return {"DEMO":frame}

async def run_demo(fast_period=5, slow_period=12):
    if not 1 <= fast_period < slow_period:
        raise ValueError("Require 1 <= fast_period < slow_period")
    strategy = StrategyLoader().load_strategy("ma_cross",fast_period=fast_period,slow_period=slow_period)
    if strategy is None:
        raise RuntimeError("ma_cross plugin could not be loaded")
    runner = StrategyRunner(strategy,RunnerConfig(backtest_mode=True,paper_mode=False,symbols=["DEMO"],emit_events=False,initial_capital=10000))
    return await runner.backtest(synthetic_bars())
