"""
KlineDock - 配置管理模块

使用 Pydantic Settings 进行类型安全的配置管理
"""

import os
from pathlib import Path
from typing import Optional
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录 (config.py -> core -> src -> root)
PROJECT_ROOT = Path(__file__).parent.parent.parent


class BinanceConfig(BaseSettings):
    """币安API配置"""
    
    model_config = SettingsConfigDict(env_prefix="BINANCE_")
    
    api_key: str = Field(default="", description="币安API Key")
    api_secret: str = Field(default="", description="币安API Secret")
    testnet: bool = Field(default=False, description="是否使用测试网")
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置API密钥"""
        return bool(self.api_key and self.api_secret)


class DatabaseConfig(BaseSettings):
    """数据库配置"""
    
    model_config = SettingsConfigDict(env_prefix="DATABASE_")
    
    url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT}/data/hydra.db",
        description="数据库连接URL"
    )
    echo: bool = Field(default=False, description="是否打印SQL语句")


class TelegramConfig(BaseSettings):
    """Telegram通知配置"""
    
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")
    
    bot_token: str = Field(default="", description="Telegram Bot Token")
    admin_id: str = Field(default="", description="管理员Telegram ID")
    
    @property
    def is_configured(self) -> bool:
        """检查是否已配置"""
        return bool(self.bot_token and self.admin_id)


class WebConfig(BaseSettings):
    """Web服务配置"""
    
    model_config = SettingsConfigDict(env_prefix="WEB_")
    
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8080, description="监听端口")
    debug: bool = Field(default=False, description="调试模式")


class LogConfig(BaseSettings):
    """日志配置"""
    
    model_config = SettingsConfigDict(env_prefix="LOG_")
    
    level: str = Field(default="INFO", description="日志级别")
    file: Optional[str] = Field(default=None, description="日志文件路径")
    
    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"日志级别必须是: {valid_levels}")
        return v


class RiskConfig(BaseSettings):
    """风控配置"""
    
    model_config = SettingsConfigDict(env_prefix="RISK_")
    
    # 仓位控制
    max_single_position_pct: float = Field(default=0.1, description="单标的最大仓位比例")
    max_total_exposure_pct: float = Field(default=0.8, description="总敞口最大比例")
    max_leverage: float = Field(default=1.0, description="最大杠杆")
    
    # 回撤控制
    daily_max_drawdown_pct: float = Field(default=0.03, description="日最大回撤")
    weekly_max_drawdown_pct: float = Field(default=0.08, description="周最大回撤")
    strategy_kill_drawdown_pct: float = Field(default=0.15, description="策略停止线")
    
    # 订单控制
    max_order_value_usdt: float = Field(default=10000, description="单笔订单最大金额")
    max_orders_per_minute: int = Field(default=20, description="每分钟最大订单数")
    max_slippage_pct: float = Field(default=0.005, description="最大滑点")


class HydraConfig(BaseSettings):
    """KlineDock 主配置"""
    
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # 子配置
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    
    # 路径配置
    project_root: Path = Field(default=PROJECT_ROOT)
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    plugins_dir: Path = Field(default=PROJECT_ROOT / "plugins")
    configs_dir: Path = Field(default=PROJECT_ROOT / "configs")
    
    def ensure_directories(self) -> None:
        """确保必要的目录存在"""
        dirs = [
            self.data_dir / "market",
            self.data_dir / "lean_data",
            self.data_dir / "results",
            self.plugins_dir / "strategies",
            self.plugins_dir / "indicators",
            self.plugins_dir / "risk",
            self.plugins_dir / "ai_models",
            PROJECT_ROOT / "logs",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_config() -> HydraConfig:
    """获取全局配置（单例）"""
    config = HydraConfig()
    config.ensure_directories()
    return config


# 便捷访问
config = get_config()
