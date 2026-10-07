"""
KlineDock - 策略加载器

动态发现和加载策略插件，支持热插拔
"""

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Type, Any
import yaml
from loguru import logger

from src.core.config import get_config
from src.strategy.base_strategy import BaseStrategy


@dataclass
class StrategyMeta:
    """策略元信息"""
    name: str
    version: str
    description: str
    author: str
    plugin_path: Path
    entry_point: str
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "StrategyMeta":
        """从plugin.yaml加载"""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        return cls(
            name=data.get("name", yaml_path.parent.name),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "Unknown"),
            plugin_path=yaml_path.parent,
            entry_point=data.get("entry_point", "strategy.Strategy"),
            dependencies=data.get("dependencies", {}),
            parameters=data.get("parameters", {})
        )


class StrategyLoader:
    """
    策略加载器
    
    功能:
    - 自动发现plugins/strategies目录下的策略
    - 解析plugin.yaml获取策略元信息
    - 动态加载策略类
    - 支持策略热重载
    """
    
    def __init__(self, plugins_dir: Optional[Path] = None):
        """
        初始化加载器
        
        Args:
            plugins_dir: 插件目录，默认使用配置
        """
        config = get_config()
        self.plugins_dir = plugins_dir or (config.plugins_dir / "strategies")
        
        # 策略缓存
        self._meta_cache: Dict[str, StrategyMeta] = {}
        self._class_cache: Dict[str, Type[BaseStrategy]] = {}
        self._instance_cache: Dict[str, BaseStrategy] = {}
    
    def discover_strategies(self, force_refresh: bool = False) -> List[StrategyMeta]:
        """
        发现所有可用策略
        
        Args:
            force_refresh: 是否强制刷新缓存
            
        Returns:
            List[StrategyMeta]: 策略元信息列表
        """
        if not force_refresh and self._meta_cache:
            return list(self._meta_cache.values())
        
        self._meta_cache.clear()
        strategies = []
        
        if not self.plugins_dir.exists():
            logger.warning(f"策略插件目录不存在: {self.plugins_dir}")
            return strategies
        
        # 遍历策略目录
        for strategy_dir in self.plugins_dir.iterdir():
            if not strategy_dir.is_dir():
                continue
            
            yaml_path = strategy_dir / "plugin.yaml"
            if not yaml_path.exists():
                # 尝试plugin.yml
                yaml_path = strategy_dir / "plugin.yml"
                if not yaml_path.exists():
                    logger.debug(f"跳过目录（无plugin.yaml）: {strategy_dir.name}")
                    continue
            
            try:
                meta = StrategyMeta.from_yaml(yaml_path)
                self._meta_cache[meta.name] = meta
                strategies.append(meta)
                logger.debug(f"发现策略: {meta.name} v{meta.version}")
            except Exception as e:
                logger.error(f"解析策略配置失败 {yaml_path}: {e}")
                continue
        
        logger.info(f"共发现 {len(strategies)} 个策略")
        return strategies
    
    def get_strategy_meta(self, name: str) -> Optional[StrategyMeta]:
        """获取策略元信息"""
        if not self._meta_cache:
            self.discover_strategies()
        
        return self._meta_cache.get(name)
    
    def load_strategy_class(
        self,
        name: str,
        force_reload: bool = False
    ) -> Optional[Type[BaseStrategy]]:
        """
        加载策略类
        
        Args:
            name: 策略名称
            force_reload: 是否强制重新加载
            
        Returns:
            Type[BaseStrategy]: 策略类
        """
        # 检查缓存
        if not force_reload and name in self._class_cache:
            return self._class_cache[name]
        
        # 获取元信息
        meta = self.get_strategy_meta(name)
        if not meta:
            logger.error(f"未找到策略: {name}")
            return None
        
        try:
            # 解析入口点
            module_name, class_name = self._parse_entry_point(meta)
            
            # 动态加载模块
            strategy_class = self._load_module_class(
                meta.plugin_path,
                module_name,
                class_name,
                force_reload
            )
            
            # 验证策略类
            if not self._validate_strategy_class(strategy_class):
                logger.error(f"策略类验证失败: {name}")
                return None
            
            # 缓存
            self._class_cache[name] = strategy_class
            logger.info(f"已加载策略类: {name}")
            
            return strategy_class
            
        except Exception as e:
            logger.error(f"加载策略类失败 {name}: {e}")
            return None
    
    def _parse_entry_point(self, meta: StrategyMeta) -> tuple:
        """解析入口点"""
        parts = meta.entry_point.rsplit(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        else:
            return "strategy", parts[0]
    
    def _load_module_class(
        self,
        plugin_path: Path,
        module_name: str,
        class_name: str,
        force_reload: bool = False
    ) -> Type:
        """动态加载模块中的类"""
        # 构建模块路径
        module_path = plugin_path / f"{module_name}.py"
        
        if not module_path.exists():
            raise FileNotFoundError(f"模块文件不存在: {module_path}")
        
        # 生成唯一模块名
        unique_module_name = f"hydra_plugins.{plugin_path.name}.{module_name}"
        
        # 如果强制重载，移除已加载的模块
        if force_reload and unique_module_name in sys.modules:
            del sys.modules[unique_module_name]
        
        # 加载模块
        spec = importlib.util.spec_from_file_location(
            unique_module_name,
            module_path
        )
        
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载模块: {module_path}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_module_name] = module
        spec.loader.exec_module(module)
        
        # 获取类
        if not hasattr(module, class_name):
            raise AttributeError(f"模块中未找到类: {class_name}")
        
        return getattr(module, class_name)
    
    def _validate_strategy_class(self, cls: Type) -> bool:
        """验证策略类"""
        # 检查是否继承自BaseStrategy
        if not issubclass(cls, BaseStrategy):
            logger.error(f"{cls.__name__} 必须继承自 BaseStrategy")
            return False
        
        # 检查是否实现了on_bar方法
        if not hasattr(cls, "on_bar"):
            logger.error(f"{cls.__name__} 必须实现 on_bar 方法")
            return False
        
        return True
    
    def load_strategy(
        self,
        name: str,
        force_reload: bool = False,
        **parameters
    ) -> Optional[BaseStrategy]:
        """
        加载策略实例
        
        Args:
            name: 策略名称
            force_reload: 是否强制重载
            **parameters: 策略参数
            
        Returns:
            BaseStrategy: 策略实例
        """
        # 加载类
        strategy_class = self.load_strategy_class(name, force_reload)
        if not strategy_class:
            return None
        
        # 获取元信息中的默认参数
        meta = self.get_strategy_meta(name)
        default_params = {}
        
        if meta and meta.parameters:
            for param_name, param_config in meta.parameters.items():
                if isinstance(param_config, dict) and "default" in param_config:
                    default_params[param_name] = param_config["default"]
        
        # 合并参数（用户参数优先）
        final_params = {**default_params, **parameters}
        
        try:
            # 创建实例
            instance = strategy_class(**final_params)
            
            # 设置元信息
            if meta:
                instance.name = meta.name
                instance.version = meta.version
                instance.description = meta.description
                instance.author = meta.author
            
            logger.info(f"已创建策略实例: {name} (参数: {final_params})")
            return instance
            
        except Exception as e:
            logger.error(f"创建策略实例失败 {name}: {e}")
            return None
    
    def reload_strategy(self, name: str, **parameters) -> Optional[BaseStrategy]:
        """
        热重载策略
        
        Args:
            name: 策略名称
            **parameters: 策略参数
            
        Returns:
            BaseStrategy: 新的策略实例
        """
        # 清除缓存
        if name in self._class_cache:
            del self._class_cache[name]
        if name in self._instance_cache:
            del self._instance_cache[name]
        
        # 刷新元信息
        self.discover_strategies(force_refresh=True)
        
        # 重新加载
        return self.load_strategy(name, force_reload=True, **parameters)
    
    def list_strategies(self) -> List[Dict[str, Any]]:
        """
        列出所有策略
        
        Returns:
            List[Dict]: 策略信息列表
        """
        strategies = self.discover_strategies()
        return [
            {
                "name": s.name,
                "version": s.version,
                "description": s.description,
                "author": s.author,
                "parameters": s.parameters
            }
            for s in strategies
        ]
    
    def get_loaded_strategies(self) -> List[str]:
        """获取已加载的策略名称"""
        return list(self._class_cache.keys())


# 全局策略加载器
strategy_loader = StrategyLoader()
