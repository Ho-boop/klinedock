"""
KlineDock - 仪表盘页面

显示账户概览、持仓和交易信息
"""

from nicegui import ui
from datetime import datetime
import asyncio

# 导入API
from src.web.api import app_state, engine_api, market_api, trading_api


def render():
    """渲染仪表盘页面"""
    
    with ui.column().classes("w-full p-4 gap-4"):
        # 页面标题
        ui.label("仪表盘").classes("text-2xl font-bold text-white")
        
        # ===== 统计卡片行 =====
        with ui.row().classes("w-full gap-4") as stat_row:
            balance_card = create_stat_card(
                "账户余额", 
                f"${app_state.account.balance:,.2f}", 
                "USDT可用", 
                "account_balance_wallet", 
                "blue"
            )
            equity_card = create_stat_card(
                "总权益", 
                f"${app_state.account.equity:,.2f}", 
                f"{app_state.account.return_rate:+.2%}", 
                "trending_up", 
                "green"
            )
            pnl_card = create_stat_card(
                "今日盈亏", 
                f"${app_state.account.total_pnl:+,.2f}", 
                "已实现", 
                "swap_vert", 
                "red" if app_state.account.total_pnl < 0 else "green"
            )
            position_value = sum(p.quantity * p.current_price for p in app_state.positions)
            pos_card = create_stat_card(
                "持仓价值", 
                f"${position_value:,.2f}", 
                f"{len(app_state.positions)} 个持仓", 
                "pie_chart", 
                "purple"
            )
        
        # ===== 主要内容区 =====
        with ui.row().classes("w-full gap-4"):
            # 左侧：权益曲线
            with ui.card().classes("flex-1 bg-gray-800"):
                ui.label("权益曲线").classes("text-lg font-semibold text-white mb-2")
                equity_chart = create_equity_chart()
            
            # 右侧：快速操作
            with ui.card().classes("w-80 bg-gray-800"):
                ui.label("快速操作").classes("text-lg font-semibold text-white mb-4")
                
                with ui.column().classes("gap-2 w-full"):
                    start_btn = ui.button(
                        "启动策略", 
                        icon="play_arrow", 
                        color="green",
                        on_click=start_strategy
                    ).classes("w-full")
                    
                    stop_btn = ui.button(
                        "停止所有", 
                        icon="stop", 
                        color="red",
                        on_click=stop_strategy
                    ).classes("w-full")
                    
                    backtest_btn = ui.button(
                        "运行回测", 
                        icon="history", 
                        color="blue",
                        on_click=run_backtest
                    ).classes("w-full")
                    
                    refresh_btn = ui.button(
                        "刷新数据", 
                        icon="refresh", 
                        color="gray",
                        on_click=refresh_data
                    ).classes("w-full")
                    
                    ui.separator().classes("my-2")
                    
                    # 交易入口
                    ui.button(
                        "手动交易", 
                        icon="swap_horiz", 
                        color="purple",
                        on_click=lambda: ui.navigate.to("/trading")
                    ).classes("w-full")
                    
                    # 一键平仓
                    ui.button(
                        "🚨 一键平仓", 
                        icon="cancel", 
                        color="orange",
                        on_click=emergency_close_all
                    ).classes("w-full")
        
        # ===== 持仓和交易表格 =====
        with ui.row().classes("w-full gap-4"):
            # 当前持仓
            with ui.card().classes("flex-1 bg-gray-800"):
                ui.label("当前持仓").classes("text-lg font-semibold text-white mb-2")
                positions_table = create_positions_table()
            
            # 最近交易
            with ui.card().classes("flex-1 bg-gray-800"):
                ui.label("最近交易").classes("text-lg font-semibold text-white mb-2")
                trades_table = create_trades_table()
        
        # 状态通知区
        status_label = ui.label("").classes("text-sm text-gray-400")
        
        # ===== 定时刷新 =====
        async def auto_refresh():
            """自动刷新数据"""
            try:
                # 刷新价格
                prices = await market_api.get_prices()
                
                # 同步引擎状态
                if engine_api.is_running:
                    summary = engine_api.get_account_summary()
                    app_state.update_account(
                        balance=summary.get("balance", 10000),
                        equity=summary.get("equity", 10000),
                        unrealized_pnl=summary.get("unrealized_pnl", 0)
                    )
                
            except Exception as e:
                pass  # 静默处理刷新错误
        
        # 每30秒刷新一次
        ui.timer(30.0, auto_refresh)


def create_stat_card(title: str, value: str, subtitle: str, icon: str, color: str):
    """创建统计卡片"""
    color_classes = {
        "blue": "from-blue-600 to-blue-800",
        "green": "from-green-600 to-green-800",
        "red": "from-red-600 to-red-800",
        "purple": "from-purple-600 to-purple-800",
    }
    
    with ui.card().classes(f"flex-1 bg-gradient-to-br {color_classes.get(color, 'from-gray-600 to-gray-800')} text-white"):
        with ui.row().classes("items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label(title).classes("text-sm text-gray-200")
                ui.label(value).classes("text-2xl font-bold")
                ui.label(subtitle).classes("text-xs text-gray-300")
            ui.icon(icon, size="xl").classes("opacity-50")


def create_equity_chart():
    """创建权益曲线图表"""
    # 使用ECharts绘制
    chart_options = {
        "backgroundColor": "transparent",
        "grid": {
            "top": 20,
            "right": 20,
            "bottom": 30,
            "left": 60
        },
        "xAxis": {
            "type": "category",
            "data": ["1/12", "1/13", "1/14", "1/15", "1/16", "1/17", "1/18"],
            "axisLine": {"lineStyle": {"color": "#666"}},
            "axisLabel": {"color": "#999"}
        },
        "yAxis": {
            "type": "value",
            "min": 9800,
            "max": 10200,
            "axisLine": {"lineStyle": {"color": "#666"}},
            "axisLabel": {"color": "#999", "formatter": "${value}"},
            "splitLine": {"lineStyle": {"color": "#333"}}
        },
        "series": [{
            "type": "line",
            "data": [10000, 10050, 10020, 9980, 10010, 9990, 9997],
            "smooth": True,
            "areaStyle": {
                "color": {
                    "type": "linear",
                    "x": 0, "y": 0, "x2": 0, "y2": 1,
                    "colorStops": [
                        {"offset": 0, "color": "rgba(59, 130, 246, 0.5)"},
                        {"offset": 1, "color": "rgba(59, 130, 246, 0.05)"}
                    ]
                }
            },
            "lineStyle": {"color": "#3B82F6", "width": 2},
            "itemStyle": {"color": "#3B82F6"}
        }],
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": "#333",
            "borderColor": "#555",
            "textStyle": {"color": "#fff"}
        }
    }
    
    return ui.echart(chart_options).classes("w-full h-64")


def create_positions_table():
    """创建持仓表格"""
    columns = [
        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
        {"name": "quantity", "label": "数量", "field": "quantity", "align": "right"},
        {"name": "avg_price", "label": "成本价", "field": "avg_price", "align": "right"},
        {"name": "current_price", "label": "现价", "field": "current_price", "align": "right"},
        {"name": "pnl", "label": "盈亏", "field": "pnl", "align": "right"},
    ]
    
    # 从API获取数据
    rows = engine_api.get_positions()
    if not rows:
        rows = [{"symbol": "-", "quantity": "-", "avg_price": "-", "current_price": "-", "pnl": "-"}]
    
    return ui.table(columns=columns, rows=rows, row_key="symbol").classes(
        "w-full bg-gray-700"
    ).props("dark dense")


def create_trades_table():
    """创建交易表格"""
    columns = [
        {"name": "time", "label": "时间", "field": "time", "align": "left"},
        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
        {"name": "side", "label": "方向", "field": "side", "align": "center"},
        {"name": "quantity", "label": "数量", "field": "quantity", "align": "right"},
        {"name": "price", "label": "价格", "field": "price", "align": "right"},
    ]
    
    # 从API获取数据
    rows = engine_api.get_trades(limit=5)
    if not rows:
        rows = [{"time": "-", "symbol": "-", "side": "-", "quantity": "-", "price": "-"}]
    
    return ui.table(columns=columns, rows=rows, row_key="time").classes(
        "w-full bg-gray-700"
    ).props("dark dense")


# ===== 按钮事件处理 =====

async def start_strategy():
    """启动策略"""
    ui.notify("正在启动策略...", type="info")
    result = await engine_api.start_strategy("ma_cross")
    if result["success"]:
        ui.notify(result["message"], type="positive")
    else:
        ui.notify(result["message"], type="negative")


async def stop_strategy():
    """停止策略"""
    ui.notify("正在停止策略...", type="info")
    result = await engine_api.stop_strategy()
    if result["success"]:
        ui.notify(result["message"], type="positive")
    else:
        ui.notify(result["message"], type="negative")


async def run_backtest():
    """运行回测"""
    ui.notify("正在运行回测...", type="info")
    result = await engine_api.run_backtest("ma_cross", days=30)
    if result["success"]:
        metrics = result.get("result", {}).get("metrics", {})
        msg = f"回测完成! 收益: {metrics.get('total_return', '0%')}, 胜率: {metrics.get('win_rate', '-')}"
        ui.notify(msg, type="positive")
    else:
        ui.notify(result["message"], type="negative")


async def refresh_data():
    """刷新数据"""
    ui.notify("正在刷新数据...", type="info")
    try:
        prices = await market_api.get_prices()
        ui.notify(f"数据已刷新，获取 {len(prices)} 个价格", type="positive")
    except Exception as e:
        ui.notify(f"刷新失败: {e}", type="negative")


async def emergency_close_all():
    """紧急一键平仓"""
    ui.notify("🚨 正在执行紧急平仓...", type="warning")
    try:
        result = await trading_api.close_all_positions()
        if result["success"]:
            ui.notify("✅ 平仓完成", type="positive")
        else:
            ui.notify(result["message"], type="negative")
    except Exception as e:
        ui.notify(f"平仓失败: {e}", type="negative")

