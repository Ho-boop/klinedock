"""
KlineDock - 全局状态管理器

管理Web应用的全局状态：运行中的策略、账户信息、系统状态
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from loguru import logger


class SystemStatus(str, Enum):
    """系统状态"""
    IDLE = "idle"           # 空闲
    RUNNING = "running"     # 运行中
    ERROR = "error"         # 异常


@dataclass
class StrategyState:
    """策略运行状态"""
    name: str
    version: str
    status: str = "stopped"  # running, stopped, error
    parameters: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    trades_count: int = 0
    pnl: float = 0.0
    win_rate: float = 0.0


@dataclass
class AccountState:
    """账户状态"""
    balance: float = 10000.0
    equity: float = 10000.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    return_rate: float = 0.0


@dataclass
class PositionState:
    """持仓状态"""
    symbol: str
    quantity: float
    avg_price: float
    current_price: float
    pnl: float
    pnl_percent: float


@dataclass
class TradeRecord:
    """交易记录"""
    time: str
    symbol: str
    side: str
    quantity: float
    price: float


class AppState:
    """
    应用全局状态管理器（单例）
    
    管理:
    - 系统运行状态
    - 账户信息
    - 策略状态
    - 持仓和交易记录
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 系统状态
        self.system_status = SystemStatus.IDLE
        self.last_update = datetime.now()
        
        # 账户状态
        self.account = AccountState()
        
        # 策略状态
        self.strategies: Dict[str, StrategyState] = {}
        self.active_strategy: Optional[str] = None
        
        # 持仓和交易
        self.positions: List[PositionState] = []
        self.trades: List[TradeRecord] = []
        
        # 行情数据
        self.prices: Dict[str, float] = {}
        
        # API连接状态
        self.api_connected = False
        self.data_synced = True
        self.telegram_configured = False
        
        self._initialized = True
        logger.info("应用状态管理器已初始化")
    
    def update_account(
        self,
        balance: float,
        equity: float,
        unrealized_pnl: float = 0.0
    ) -> None:
        """更新账户信息"""
        self.account.balance = balance
        self.account.equity = equity
        self.account.unrealized_pnl = unrealized_pnl
        self.account.total_pnl = equity - 10000.0  # 假设初始资金10000
        self.account.return_rate = self.account.total_pnl / 10000.0
        self.last_update = datetime.now()
    
    def update_positions(self, positions: List[PositionState]) -> None:
        """更新持仓"""
        self.positions = positions
        self.last_update = datetime.now()
    
    def add_trade(self, trade: TradeRecord) -> None:
        """添加交易记录"""
        self.trades.insert(0, trade)  # 最新的在前
        if len(self.trades) > 100:  # 最多保留100条
            self.trades = self.trades[:100]
    
    def update_strategy_status(
        self,
        name: str,
        status: str,
        trades_count: int = 0,
        pnl: float = 0.0
    ) -> None:
        """更新策略状态"""
        if name in self.strategies:
            self.strategies[name].status = status
            self.strategies[name].trades_count = trades_count
            self.strategies[name].pnl = pnl
            if status == "running":
                self.strategies[name].start_time = datetime.now()
                self.active_strategy = name
            elif status == "stopped":
                if self.active_strategy == name:
                    self.active_strategy = None
    
    def register_strategy(
        self,
        name: str,
        version: str,
        parameters: Dict[str, Any]
    ) -> None:
        """注册策略"""
        self.strategies[name] = StrategyState(
            name=name,
            version=version,
            parameters=parameters
        )
    
    def update_price(self, symbol: str, price: float) -> None:
        """更新价格"""
        self.prices[symbol] = price
    
    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        return {
            "balance": self.account.balance,
            "equity": self.account.equity,
            "unrealized_pnl": self.account.unrealized_pnl,
            "total_pnl": self.account.total_pnl,
            "return_rate": self.account.return_rate,
            "position_count": len(self.positions),
            "total_position_value": sum(
                p.quantity * p.current_price for p in self.positions
            )
        }
    
    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "api_connected": self.api_connected,
            "data_synced": self.data_synced,
            "strategy_running": self.active_strategy is not None,
            "active_strategy": self.active_strategy,
            "telegram_configured": self.telegram_configured,
            "last_update": self.last_update.strftime("%H:%M:%S")
        }
    
    def reset(self) -> None:
        """重置状态"""
        self.account = AccountState()
        self.positions = []
        self.trades = []
        self.active_strategy = None
        for strategy in self.strategies.values():
            strategy.status = "stopped"
            strategy.trades_count = 0
            strategy.pnl = 0.0
        logger.info("应用状态已重置")


# 全局状态实例
app_state = AppState()
