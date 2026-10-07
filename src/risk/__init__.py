"""
KlineDock - 风控模块

提供多层风控保护
"""

from src.risk.base_risk import (
    BaseRiskModule,
    RiskEngine,
    RiskCheckResult,
    RiskAction,
    RiskLevel,
    RiskContext,
    Order,
    Position,
    risk_engine
)
from src.risk.stop_loss import (
    StopLossModule,
    StopOrder,
    StopType,
    create_stop_loss_module
)
from src.risk.position_control import (
    PositionControl,
    DrawdownControl,
    create_position_control,
    create_drawdown_control
)

__all__ = [
    # 基类
    "BaseRiskModule",
    "RiskEngine",
    "RiskCheckResult",
    "RiskAction",
    "RiskLevel",
    "RiskContext",
    "Order",
    "Position",
    "risk_engine",
    
    # 止损
    "StopLossModule",
    "StopOrder",
    "StopType",
    "create_stop_loss_module",
    
    # 仓位控制
    "PositionControl",
    "DrawdownControl",
    "create_position_control",
    "create_drawdown_control",
]
