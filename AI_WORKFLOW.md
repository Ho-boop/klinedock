# AI Coding development workflow

KlineDock was built independently with AI-assisted coding. The workflow is grounded in the code modules and debugging/verification artifacts retained from the original project.

1. **Define the usable flow.** Market data, strategy parameters, execution and a readable report form the main user journey. Write down required input/output shapes before adding pages.
2. **Separate module contracts.** `BaseStrategy`, `StrategyContext`, `Signal`, `RunnerConfig` and `BacktestResult` define the boundaries. Ask AI to implement or modify one layer with these contracts in context.
3. **Integrate and debug.** Inspect event-loop behavior, price/position state, nested OHLCV formats and JSON serialization when connecting UI and runner. Keep execution logs for failures instead of accepting generated code by appearance.
4. **Verify the result path.** The original `test_backtest_flow.py` checked result transfer into the report component. The public release adds a deterministic, offline plugin→runner→report contract check without exchange availability or credentials.
5. **Publish a reproducible entry.** Package dependencies and entry points, replace absolute workstation paths and explain unsupported modules honestly. AI tool names describe the development method; the application does not require an LLM API at runtime.

No productivity speedup is claimed without a measured baseline. The synthetic offline demo was added during portfolio packaging and is not presented as an earlier production deployment.
