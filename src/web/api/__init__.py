"""
KlineDock - Web API层

连接NiceGUI前端与后端引擎
"""

from src.web.api.state_manager import AppState, app_state
from src.web.api.engine_api import EngineAPI, engine_api
from src.web.api.strategy_api import StrategyAPI, strategy_api
from src.web.api.market_api import MarketAPI, market_api
from src.web.api.trading_api import TradingAPI, trading_api

__all__ = [
    "AppState",
    "app_state",
    "EngineAPI",
    "engine_api", 
    "StrategyAPI",
    "strategy_api",
    "MarketAPI",
    "market_api",
    "TradingAPI",
    "trading_api",
]

