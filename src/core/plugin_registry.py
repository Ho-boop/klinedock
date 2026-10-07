"""
KlineDock - 插件注册中心

实现策略、指标、风控、AI模型的热插拔机制
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type, Any, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum
import yaml
from loguru import logger

from .config import config


class PluginType(str, Enum):
    """插件类型枚举"""
    STRATEGY = "strategy"
    INDICATOR = "indicator"
    RISK = "risk"
    AI_MODEL = "ai_model"


@dataclass
class PluginMeta:
    """插件元数据"""
    name: str
    version: str
    plugin_type: PluginType
    description: str = ""
    author: str = ""
    entry_point: str = ""
    path: Path = field(default_factory=Path)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "PluginMeta":
        """从plugin.yaml加载插件元数据"""
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        return cls(
            name=data.get("name", yaml_path.parent.name),
            version=data.get("version", "0.1.0"),
            plugin_type=PluginType(data.get("type", "strategy")),
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", ""),
            path=yaml_path.parent,
            dependencies=data.get("dependencies", {}),
            parameters=data.get("parameters", {}),
            enabled=data.get("enabled", True),
        )


T = TypeVar("T")


class PluginRegistry(Generic[T]):
    """插件注册中心（泛型）"""
    
    def __init__(self, plugin_type: PluginType):
        self.plugin_type = plugin_type
        self._plugins: Dict[str, PluginMeta] = {}
        self._instances: Dict[str, T] = {}
        self._classes: Dict[str, Type[T]] = {}
    
    @property
    def plugins_dir(self) -> Path:
        """获取插件目录"""
        type_dirs = {
            PluginType.STRATEGY: "strategies",
            PluginType.INDICATOR: "indicators",
            PluginType.RISK: "risk",
            PluginType.AI_MODEL: "ai_models",
        }
        return config.plugins_dir / type_dirs[self.plugin_type]
    
    def scan(self) -> List[PluginMeta]:
        """扫描插件目录"""
        self._plugins.clear()
        plugins = []
        
        if not self.plugins_dir.exists():
            logger.warning(f"插件目录不存在: {self.plugins_dir}")
            return plugins
        
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            
            yaml_path = plugin_dir / "plugin.yaml"
            if not yaml_path.exists():
                logger.debug(f"跳过无配置的目录: {plugin_dir}")
                continue
            
            try:
                meta = PluginMeta.from_yaml(yaml_path)
                if meta.enabled:
                    self._plugins[meta.name] = meta
                    plugins.append(meta)
                    logger.info(f"发现插件: {meta.name} v{meta.version}")
                else:
                    logger.debug(f"插件已禁用: {meta.name}")
            except Exception as e:
                logger.error(f"加载插件元数据失败 {yaml_path}: {e}")
        
        return plugins
    
    def load(self, name: str) -> Optional[Type[T]]:
        """动态加载插件类"""
        if name in self._classes:
            return self._classes[name]
        
        if name not in self._plugins:
            logger.error(f"插件未注册: {name}")
            return None
        
        meta = self._plugins[name]
        
        try:
            # 解析入口点 (e.g., "strategy.MACrossStrategy")
            module_name, class_name = meta.entry_point.rsplit(".", 1)
            module_path = meta.path / f"{module_name.replace('.', '/')}.py"
            
            # 动态导入模块
            spec = importlib.util.spec_from_file_location(
                f"plugins.{self.plugin_type.value}.{name}.{module_name}",
                module_path
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载模块: {module_path}")
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            # 获取类
            plugin_class = getattr(module, class_name)
            self._classes[name] = plugin_class
            
            logger.info(f"加载插件类成功: {name}.{class_name}")
            return plugin_class
            
        except Exception as e:
            logger.error(f"加载插件失败 {name}: {e}")
            return None
    
    def get_instance(self, name: str, **kwargs) -> Optional[T]:
        """获取插件实例"""
        if name in self._instances:
            return self._instances[name]
        
        plugin_class = self.load(name)
        if plugin_class is None:
            return None
        
        try:
            # 合并默认参数和传入参数
            meta = self._plugins[name]
            params = {
                k: v.get("default") 
                for k, v in meta.parameters.items() 
                if "default" in v
            }
            params.update(kwargs)
            
            instance = plugin_class(**params)
            self._instances[name] = instance
            
            logger.info(f"创建插件实例: {name}")
            return instance
            
        except Exception as e:
            logger.error(f"创建插件实例失败 {name}: {e}")
            return None
    
    def list_plugins(self) -> List[str]:
        """列出所有已注册的插件名"""
        return list(self._plugins.keys())
    
    def get_meta(self, name: str) -> Optional[PluginMeta]:
        """获取插件元数据"""
        return self._plugins.get(name)
    
    def reload(self, name: str) -> bool:
        """重新加载插件（热更新）"""
        if name in self._instances:
            del self._instances[name]
        if name in self._classes:
            del self._classes[name]
        
        # 重新扫描并加载
        self.scan()
        return self.load(name) is not None


# 全局注册中心实例
strategy_registry: PluginRegistry = PluginRegistry(PluginType.STRATEGY)
indicator_registry: PluginRegistry = PluginRegistry(PluginType.INDICATOR)
risk_registry: PluginRegistry = PluginRegistry(PluginType.RISK)
ai_model_registry: PluginRegistry = PluginRegistry(PluginType.AI_MODEL)


def init_all_registries() -> None:
    """初始化所有注册中心"""
    logger.info("初始化插件注册中心...")
    strategy_registry.scan()
    indicator_registry.scan()
    risk_registry.scan()
    ai_model_registry.scan()
    logger.info("插件注册中心初始化完成")
