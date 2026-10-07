# KlineDock

[![Checks](https://github.com/Ho-boop/klinedock/actions/workflows/ci.yml/badge.svg)](https://github.com/Ho-boop/klinedock/actions/workflows/ci.yml)

**模块化交易与回测平台 · A modular trading and backtest workbench**

An independently developed Python web application: market-data adapters, plugin-based strategies, local backtesting, simulated positions and interactive reports. The project was originally named Hydra Quant in the local workspace; this portfolio release uses KlineDock consistently.

## Run the offline demo

```bash
git clone https://github.com/Ho-boop/klinedock.git KlineDock
cd KlineDock
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
klinedock
```

Open http://127.0.0.1:8888. Select moving-average parameters, run a synthetic backtest and inspect the price chart, trade markers and equity curve. The default demo uses generated OHLCV data and the same plugin loader, strategy runner and report component as the full workbench. No account or API key is needed.

```bash
python -m src.cli --no-browser --port 8890
python -m unittest discover -s tests -v
```

## Implemented modules

| Layer | Implementation |
|---|---|
| Web | NiceGUI dashboard, market, strategy, trading, settings and backtest-report pages |
| Data | Async REST/WebSocket market adapters, OHLCV conversion, TTL cache and quality checks |
| Strategy | YAML metadata, discovery, dynamic Python loading and configurable parameters |
| Execution | Local strategy runner, fee-aware simulated trades, equity tracking and JSON result export |
| Risk | Position/exposure limits and stop-loss components |
| Coordination | Typed events and application state management |

The offline demo exposes plugin discovery and a complete local backtest/report flow. `klinedock --live-market` opens the original multi-page market workbench; it requires reachable exchange endpoints. It is a separate mode, not required by tests. Docker/LEAN orchestration code is retained as an integration module but is not covered by the offline release checks.

## Architecture

```text
NiceGUI pages → business API/state → data adapters + strategy plugins
                                          ↓
                               local runner / paper engine
                                          ↓
                                JSON result → chart report
```

`src/demo.py` creates reproducible sample data. `plugins/strategies` contains the strategy implementations and metadata. `src/core`, `src/data`, `src/strategy`, `src/risk`, `src/engine` and `src/web` hold the original application modules.

## AI Coding workflow

See [AI_WORKFLOW.md](AI_WORKFLOW.md): requirements, module contracts, implementation, integration debugging and verification. AI assisted implementation; architecture choices, integration and result validation remained the developer's responsibility.

## Current limits

- The original UI strategy-scaffolding button is disabled in this release; add a Python/YAML plugin under `plugins/strategies` instead.
- Installation is currently supported from a source checkout with `pip install -e .`; a standalone wheel does not bundle root-level plugins/configs.
- This is a local development and portfolio application. It has no production authentication or multi-user state isolation.
- The runner uses a simplified leveraged-position accounting model. Win-rate and Sharpe fields in the original UI are incomplete/provisional; do not use them to evaluate investment performance.
- Offline checks do not validate live trading, exchange connectivity, Docker/LEAN execution or production reliability.
- Research datasets, credentials and personal runtime paths are not part of this release.

MIT license applies to this repository's own source code. Third-party engines and libraries remain under their respective licenses.
