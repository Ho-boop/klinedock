"""
KlineDock - 风控基类

所有风控模块必须继承此基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from loguru import logger

from src.core.config import RiskConfig, get_config


class RiskLevel(str, Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskAction(str, Enum):
    """风控动作"""
    PASS = "pass"           # 通过
    REDUCE = "reduce"       # 减仓
    REJECT = "reject"       # 拒绝
    CLOSE = "close"         # 平仓
    KILL_SWITCH = "kill"    # 紧急停止


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    passed: bool
    action: RiskAction
    reason: str = ""
    level: RiskLevel = RiskLevel.LOW
    suggested_quantity: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def approve(cls, reason: str = "") -> "RiskCheckResult":
        """创建通过结果"""
        return cls(passed=True, action=RiskAction.PASS, reason=reason)
    
    @classmethod
    def reject(cls, reason: str, level: RiskLevel = RiskLevel.MEDIUM) -> "RiskCheckResult":
        """创建拒绝结果"""
        return cls(passed=False, action=RiskAction.REJECT, reason=reason, level=level)


@dataclass
class Order:
    """订单对象"""
    symbol: str
    side: str  # buy/sell
    quantity: float
    price: Optional[float] = None
    order_type: str = "market"  # market/limit
    order_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """持仓对象"""
    symbol: str
    quantity: float
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price
    
    @property
    def cost(self) -> float:
        return self.quantity * self.avg_price
    
    def update_price(self, price: float) -> None:
        self.current_price = price
        self.unrealized_pnl = (price - self.avg_price) * self.quantity


@dataclass
class RiskContext:
    """风控上下文"""
    # 账户信息
    balance: float = 0.0
    equity: float = 0.0
    available_margin: float = 0.0
    
    # 持仓信息
    positions: Dict[str, Position] = field(default_factory=dict)
    
    # 当日统计
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_volume: float = 0.0
    
    # 历史统计
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    
    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
    
    def get_total_exposure(self) -> float:
        """获取总敞口"""
        return sum(p.market_value for p in self.positions.values())
    
    def get_exposure_ratio(self) -> float:
        """获取敞口比例"""
        if self.equity <= 0:
            return 0.0
        return self.get_total_exposure() / self.equity


class BaseRiskModule(ABC):
    """
    风控模块基类
    
    所有风控模块必须继承此类并实现check_order方法
    """
    
    name: str = "BaseRisk"
    description: str = ""
    priority: int = 0  # 优先级，数字越小优先级越高
    
    def __init__(self, config: Optional[RiskConfig] = None):
        """
        初始化风控模块
        
        Args:
            config: 风控配置
        """
        if config is None:
            config = get_config().risk
        self.config = config
        self._enabled = True
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def enable(self) -> None:
        """启用模块"""
        self._enabled = True
        logger.info(f"风控模块已启用: {self.name}")
    
    def disable(self) -> None:
        """禁用模块"""
        self._enabled = False
        logger.info(f"风控模块已禁用: {self.name}")
    
    @abstractmethod
    def check_order(
        self,
        order: Order,
        context: RiskContext
    ) -> RiskCheckResult:
        """
        检查订单是否符合风控规则
        
        Args:
            order: 待检查订单
            context: 风控上下文
            
        Returns:
            RiskCheckResult: 检查结果
        """
        pass
    
    def on_position_update(self, position: Position) -> None:
        """
        持仓更新回调（可选覆盖）
        
        Args:
            position: 更新后的持仓
        """
        pass
    
    def on_order_filled(self, order: Order) -> None:
        """
        订单成交回调（可选覆盖）
        
        Args:
            order: 成交的订单
        """
        pass
    
    def on_pnl_update(self, pnl: float, equity: float) -> Optional[RiskAction]:
        """
        盈亏更新回调（可选覆盖）
        
        Args:
            pnl: 当前盈亏
            equity: 当前权益
            
        Returns:
            RiskAction: 需要执行的动作，或None
        """
        return None
    
    def __repr__(self) -> str:
        return f"<{self.name} enabled={self.enabled}>"


class RiskEngine:
    """
    风控引擎
    
    管理和协调多个风控模块
    """
    
    def __init__(self):
        self._modules: List[BaseRiskModule] = []
        self._context = RiskContext()
    
    def register(self, module: BaseRiskModule) -> None:
        """注册风控模块"""
        self._modules.append(module)
        # 按优先级排序
        self._modules.sort(key=lambda m: m.priority)
        logger.info(f"已注册风控模块: {module.name}")
    
    def unregister(self, module_name: str) -> bool:
        """取消注册风控模块"""
        for i, m in enumerate(self._modules):
            if m.name == module_name:
                del self._modules[i]
                logger.info(f"已取消注册风控模块: {module_name}")
                return True
        return False
    
    def update_context(self, **kwargs) -> None:
        """更新风控上下文"""
        for key, value in kwargs.items():
            if hasattr(self._context, key):
                setattr(self._context, key, value)
    
    def check_order(self, order: Order) -> RiskCheckResult:
        """
        对订单执行所有风控检查
        
        Args:
            order: 待检查订单
            
        Returns:
            RiskCheckResult: 综合检查结果
        """
        for module in self._modules:
            if not module.enabled:
                continue
            
            result = module.check_order(order, self._context)
            
            if not result.passed:
                logger.warning(
                    f"风控拒绝 [{module.name}]: {order.symbol} {order.side} "
                    f"{order.quantity} - {result.reason}"
                )
                return result
        
        return RiskCheckResult.approve("所有风控检查通过")
    
    def on_position_update(self, position: Position) -> None:
        """通知所有模块持仓更新"""
        # 更新上下文中的持仓
        self._context.positions[position.symbol] = position
        
        for module in self._modules:
            if module.enabled:
                module.on_position_update(position)
    
    def on_order_filled(self, order: Order) -> None:
        """通知所有模块订单成交"""
        for module in self._modules:
            if module.enabled:
                module.on_order_filled(order)
    
    def get_modules(self) -> List[BaseRiskModule]:
        """获取所有已注册模块"""
        return self._modules.copy()


# 全局风控引擎
risk_engine = RiskEngine()
