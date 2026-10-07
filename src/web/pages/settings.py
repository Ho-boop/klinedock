"""
KlineDock - 系统设置页面

API配置、风控设置等
"""

from nicegui import ui
from pathlib import Path
import os
import yaml

# 导入API
from src.web.api import app_state, market_api
from src.core.config import get_config, PROJECT_ROOT


# 配置路径
ENV_PATH = PROJECT_ROOT / ".env"
RISK_CONFIG_PATH = PROJECT_ROOT / "configs" / "risk_config.yaml"


def render():
    """渲染设置页面"""
    
    # 加载现有配置
    config = get_config()
    
    with ui.column().classes("w-full p-4 gap-4"):
        # 页面标题
        ui.label("系统设置").classes("text-2xl font-bold text-white")
        
        with ui.row().classes("w-full gap-4"):
            # ===== 左侧：配置项 =====
            with ui.column().classes("flex-1 gap-4"):
                # API配置
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("币安API配置").classes("text-lg font-semibold text-white mb-4")
                    
                    with ui.column().classes("gap-4"):
                        with ui.row().classes("items-center gap-4"):
                            ui.label("API Key").classes("w-28 text-gray-300")
                            api_key_input = ui.input(
                                placeholder="输入API Key",
                                value=config.binance.api_key if config.binance.api_key else ""
                            ).classes("flex-1").props("filled dark")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("API Secret").classes("w-28 text-gray-300")
                            api_secret_input = ui.input(
                                placeholder="输入API Secret", 
                                password=True,
                                value=""  # 不显示实际值
                            ).classes("flex-1").props("filled dark")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("模式").classes("w-28 text-gray-300")
                            mode_toggle = ui.toggle(
                                ["测试网", "实盘"], 
                                value="测试网" if config.binance.testnet else "实盘"
                            ).classes("flex-1")
                        
                        ui.button(
                            "保存并测试连接", 
                            icon="check", 
                            color="blue",
                            on_click=lambda: save_and_test_api(
                                api_key_input.value,
                                api_secret_input.value,
                                mode_toggle.value == "测试网"
                            )
                        )
                
                # 风控设置
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("风控设置").classes("text-lg font-semibold text-white mb-4")
                    
                    # 加载风控配置
                    risk_config = load_risk_config()
                    
                    with ui.column().classes("gap-4"):
                        with ui.row().classes("items-center gap-4"):
                            ui.label("单仓位上限").classes("w-32 text-gray-300")
                            position_limit = ui.slider(
                                min=1, 
                                max=50, 
                                value=risk_config.get("position_limit", 10)
                            ).props("label-always suffix=%").classes("flex-1")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("总敞口上限").classes("w-32 text-gray-300")
                            exposure_limit = ui.slider(
                                min=10, 
                                max=100, 
                                value=risk_config.get("exposure_limit", 80)
                            ).props("label-always suffix=%").classes("flex-1")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("日最大回撤").classes("w-32 text-gray-300")
                            max_drawdown = ui.slider(
                                min=1, 
                                max=20, 
                                value=risk_config.get("max_daily_drawdown", 3)
                            ).props("label-always suffix=%").classes("flex-1")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("策略停止线").classes("w-32 text-gray-300")
                            stop_loss = ui.slider(
                                min=5, 
                                max=50, 
                                value=risk_config.get("strategy_stop_loss", 15)
                            ).props("label-always suffix=%").classes("flex-1")
                        
                        ui.button(
                            "保存风控设置", 
                            icon="save", 
                            color="blue",
                            on_click=lambda: save_risk_config(
                                position_limit.value,
                                exposure_limit.value,
                                max_drawdown.value,
                                stop_loss.value
                            )
                        )
            
            # ===== 右侧：通知和状态 =====
            with ui.column().classes("w-96 gap-4"):
                # Telegram通知
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("Telegram通知").classes("text-lg font-semibold text-white mb-4")
                    
                    with ui.column().classes("gap-4"):
                        with ui.row().classes("items-center gap-4"):
                            ui.label("Bot Token").classes("w-24 text-gray-300")
                            tg_token_input = ui.input(
                                placeholder="Bot Token"
                            ).classes("flex-1").props("filled dark")
                        
                        with ui.row().classes("items-center gap-4"):
                            ui.label("Admin ID").classes("w-24 text-gray-300")
                            tg_id_input = ui.input(
                                placeholder="Telegram ID"
                            ).classes("flex-1").props("filled dark")
                        
                        ui.label("通知类型").classes("text-gray-300")
                        with ui.column().classes("gap-2"):
                            notify_signal = ui.checkbox("交易信号", value=True)
                            notify_order = ui.checkbox("订单成交", value=True)
                            notify_stop = ui.checkbox("止损触发", value=True)
                            notify_error = ui.checkbox("系统异常", value=True)
                        
                        ui.button(
                            "保存并测试", 
                            icon="send", 
                            color="blue",
                            on_click=lambda: save_telegram_config(
                                tg_token_input.value,
                                tg_id_input.value
                            )
                        )
                
                # 系统状态
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("系统状态").classes("text-lg font-semibold text-white mb-4")
                    
                    with ui.column().classes("gap-2"):
                        create_status_row("API连接", 
                            "已连接" if app_state.api_connected else "未连接", 
                            app_state.api_connected)
                        create_status_row("数据同步", 
                            "正常" if app_state.data_synced else "异常", 
                            app_state.data_synced)
                        create_status_row("策略引擎", 
                            "运行中" if app_state.active_strategy else "空闲", 
                            app_state.active_strategy is not None)
                        create_status_row("风控模块", "已启用", True)
                        create_status_row("Telegram", 
                            "已配置" if app_state.telegram_configured else "未配置", 
                            app_state.telegram_configured)


def create_status_row(label: str, status: str, is_ok: bool):
    """创建状态行"""
    color = "green" if is_ok else "gray"
    icon = "check_circle" if is_ok else "cancel"
    
    with ui.row().classes("w-full justify-between items-center"):
        ui.label(label).classes("text-gray-300")
        with ui.row().classes("items-center gap-1"):
            ui.icon(icon, color=color, size="xs")
            ui.label(status).classes(f"text-{color}-400")


def load_risk_config() -> dict:
    """加载风控配置"""
    try:
        if RISK_CONFIG_PATH.exists():
            with open(RISK_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {
        "position_limit": 10,
        "exposure_limit": 80,
        "max_daily_drawdown": 3,
        "strategy_stop_loss": 15
    }


# ===== 事件处理 =====

async def save_and_test_api(api_key: str, api_secret: str, testnet: bool):
    """保存API配置并测试连接"""
    ui.notify("正在保存配置...", type="info")
    
    try:
        # 读取现有.env
        env_content = {}
        if ENV_PATH.exists():
            with open(ENV_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_content[key] = value
        
        # 更新配置
        if api_key:
            env_content['BINANCE_API_KEY'] = api_key
        if api_secret:
            env_content['BINANCE_API_SECRET'] = api_secret
        env_content['BINANCE_TESTNET'] = 'true' if testnet else 'false'
        
        # 写回.env
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")
        
        ui.notify("配置已保存", type="positive")
        
        # 测试连接
        ui.notify("正在测试API连接...", type="info")
        prices = await market_api.get_prices(["BTCUSDT"])
        
        if prices:
            app_state.api_connected = True
            ui.notify(f"API连接成功! BTC价格: ${prices[0]['price']:,.2f}", type="positive")
        else:
            app_state.api_connected = False
            ui.notify("API连接失败，请检查配置", type="negative")
            
    except Exception as e:
        ui.notify(f"保存失败: {e}", type="negative")


def save_risk_config(
    position_limit: float,
    exposure_limit: float,
    max_drawdown: float,
    stop_loss: float
):
    """保存风控配置"""
    try:
        config = {
            "position_limit": int(position_limit),
            "exposure_limit": int(exposure_limit),
            "max_daily_drawdown": int(max_drawdown),
            "strategy_stop_loss": int(stop_loss),
            "updated_at": str(Path("").resolve())  # 简单记录更新
        }
        
        # 确保目录存在
        RISK_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        with open(RISK_CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        ui.notify("风控设置已保存", type="positive")
        
    except Exception as e:
        ui.notify(f"保存失败: {e}", type="negative")


def save_telegram_config(token: str, admin_id: str):
    """保存Telegram配置"""
    if not token or not admin_id:
        ui.notify("请填写完整的Telegram配置", type="warning")
        return
    
    try:
        # 读取现有.env
        env_content = {}
        if ENV_PATH.exists():
            with open(ENV_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_content[key] = value
        
        # 更新配置
        env_content['TELEGRAM_BOT_TOKEN'] = token
        env_content['TELEGRAM_ADMIN_ID'] = admin_id
        
        # 写回.env
        with open(ENV_PATH, 'w', encoding='utf-8') as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")
        
        app_state.telegram_configured = True
        ui.notify("Telegram配置已保存", type="positive")
        
    except Exception as e:
        ui.notify(f"保存失败: {e}", type="negative")
