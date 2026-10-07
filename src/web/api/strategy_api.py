"""
KlineDock - 策略API

封装策略加载器操作
"""

from typing import Dict, List, Optional, Any
from loguru import logger

from src.strategy import StrategyLoader, strategy_loader
from src.web.api.state_manager import app_state


class StrategyAPI:
    """
    策略管理API
    
    功能:
    - 列出可用策略
    - 获取策略详情和参数
    - 加载/重载策略
    """
    
    def __init__(self):
        self._loader = strategy_loader
        self._discovered = False
    
    def discover(self) -> List[Dict[str, Any]]:
        """发现并返回所有可用策略"""
        strategies = self._loader.discover_strategies(force_refresh=True)
        self._discovered = True
        
        result = []
        for meta in strategies:
            strategy_info = {
                "name": meta.name,
                "version": meta.version,
                "description": meta.description,
                "author": meta.author,
                "parameters": meta.parameters
            }
            result.append(strategy_info)
            
            # 注册到全局状态
            app_state.register_strategy(
                name=meta.name,
                version=meta.version,
                parameters=meta.parameters
            )
        
        logger.info(f"发现 {len(result)} 个策略")
        return result
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """列出所有策略及其状态"""
        if not self._discovered:
            self.discover()
        
        strategies = []
        
        # 从状态管理器获取策略信息
        for name, state in app_state.strategies.items():
            strategies.append({
                "name": state.name,
                "version": state.version,
                "status": state.status,
                "parameters": state.parameters,
                "trades_count": state.trades_count,
                "pnl": f"{'+' if state.pnl >= 0 else ''}{state.pnl:.2f}",
                "pnl_percent": f"{'+' if state.pnl >= 0 else ''}{state.pnl / 100:.2%}" 
                    if state.pnl != 0 else "0%",
                "win_rate": f"{state.win_rate:.0%}" if state.win_rate > 0 else "-"
            })
        
        # 如果状态管理器为空，从加载器获取
        if not strategies:
            for info in self._loader.list_strategies():
                strategies.append({
                    "name": info["name"],
                    "version": info["version"],
                    "status": "stopped",
                    "parameters": info.get("parameters", {}),
                    "trades_count": 0,
                    "pnl": "$0",
                    "pnl_percent": "0%",
                    "win_rate": "-"
                })
        
        return strategies
    
    def get_strategy_details(self, name: str) -> Optional[Dict[str, Any]]:
        """获取策略详细信息"""
        meta = self._loader.get_strategy_meta(name)
        if not meta:
            return None
        
        # 获取运行状态
        state = app_state.strategies.get(name)
        
        return {
            "name": meta.name,
            "version": meta.version,
            "description": meta.description,
            "author": meta.author,
            "entry_point": meta.entry_point,
            "parameters": meta.parameters,
            "dependencies": meta.dependencies,
            "status": state.status if state else "stopped",
            "trades_count": state.trades_count if state else 0,
            "pnl": state.pnl if state else 0.0
        }
    
    def get_strategy_parameters(self, name: str) -> Dict[str, Any]:
        """获取策略参数定义"""
        meta = self._loader.get_strategy_meta(name)
        if not meta:
            return {}
        return meta.parameters
    
    def update_strategy_parameters(
        self,
        name: str,
        parameters: Dict[str, Any]
    ) -> bool:
        """更新策略参数（仅更新状态，不持久化）"""
        if name in app_state.strategies:
            app_state.strategies[name].parameters.update(parameters)
            logger.info(f"策略 {name} 参数已更新: {parameters}")
            return True
        return False


# 全局策略API实例
strategy_api = StrategyAPI()
