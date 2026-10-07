"""
KlineDock - 行情监控页面

K线图表和实时价格
"""

from nicegui import ui
from datetime import datetime
import asyncio

# 导入API
from src.web.api import market_api, app_state


# 页面状态
_current_symbol = "BTCUSDT"
_current_interval = "1h"


def render():
    """渲染行情监控页面"""
    global _current_symbol, _current_interval
    
    with ui.column().classes("w-full p-4 gap-4"):
        # 页面标题
        ui.label("行情监控").classes("text-2xl font-bold text-white")
        
        # ===== 快速价格卡片 =====
        with ui.row().classes("w-full gap-4"):
            btc_price_label = create_price_card("BTCUSDT")
            btc_perp_price_label = create_price_card("BTCUSDT.P")
            eth_perp_price_label = create_price_card("ETHUSDT.P")
            sol_perp_price_label = create_price_card("SOLUSDT.P")
        
        # ===== K线图表 =====
        with ui.card().classes("w-full bg-gray-800"):
            with ui.row().classes("justify-between items-center mb-4"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("K线图表").classes("text-lg font-semibold text-white")
                    chart_symbol_label = ui.label(f"({_current_symbol})").classes("text-gray-400")
                
                with ui.row().classes("gap-2 items-end"):
                    # 交易对选择
                    symbol_select = ui.select(
                        market_api.get_available_symbols(), 
                        value=_current_symbol,
                        label="交易对"
                    ).classes("w-32")
                    
                    # 添加交易对
                    new_symbol_input = ui.input(placeholder="添加如 PEPEUSDT").classes("w-32").props("dense")
                    ui.button(icon="add", on_click=lambda: add_new_symbol(new_symbol_input, symbol_select)).props("flat dense")
                    
                    # 周期选择
                    interval_select = ui.select(
                        ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
                        value=_current_interval,
                        label="周期"
                    ).classes("w-24")
                    
                    # 加载按钮
                    load_btn = ui.button(
                        "加载K线",
                        icon="refresh",
                        color="blue",
                        on_click=lambda: load_klines(
                            symbol_select.value,
                            interval_select.value,
                            chart,
                            chart_symbol_label,
                            load_btn
                        )
                    )
            
            # K线图
            chart = create_empty_chart()
            
            # 加载提示
            ui.label("点击「加载K线」按钮获取数据").classes("text-gray-500 text-sm mt-2")
        
        # ===== 订单簿 =====
        with ui.row().classes("w-full gap-4"):
            with ui.card().classes("flex-1 bg-gray-800"):
                with ui.row().classes("justify-between items-center mb-2"):
                    ui.label("买盘深度").classes("text-lg font-semibold text-white")
                    ui.badge("实时", color="green").classes("text-xs")
                bids_table = create_orderbook_table("bids")
            
            with ui.card().classes("flex-1 bg-gray-800"):
                with ui.row().classes("justify-between items-center mb-2"):
                    ui.label("卖盘深度").classes("text-lg font-semibold text-white")
                    ui.badge("实时", color="red").classes("text-xs")
                asks_table = create_orderbook_table("asks")
        
        # ===== 定时刷新订单簿 =====
        async def refresh_orderbook():
            """刷新订单簿数据"""
            try:
                orderbook = await market_api.get_orderbook(_current_symbol, limit=8)
                
                # 更新买盘
                bids_rows = [
                    {"price": bid["price"], "quantity": bid["quantity"], "total": bid.get("total", "-")}
                    for bid in orderbook.get("bids", [])
                ]
                if bids_rows:
                    bids_table.rows = bids_rows
                    bids_table.update()
                
                # 更新卖盘
                asks_rows = [
                    {"price": ask["price"], "quantity": ask["quantity"], "total": ask.get("total", "-")}
                    for ask in orderbook.get("asks", [])
                ]
                if asks_rows:
                    asks_table.rows = asks_rows
                    asks_table.update()
                    
            except Exception as e:
                pass  # 静默处理
        
        # 每2秒刷新订单簿
        ui.timer(2.0, refresh_orderbook)
        
        # ===== 定时刷新价格 =====
        async def refresh_prices():
            """刷新价格数据"""
            try:
                prices = await market_api.get_prices()
            except Exception:
                pass
        
        ui.timer(10.0, refresh_prices)
        
        # 页面加载时自动获取一次K线
        async def init_load():
            await asyncio.sleep(1)  # 等待页面渲染
            await load_klines(
                _current_symbol,
                _current_interval,
                chart,
                chart_symbol_label,
                load_btn
            )
        
        ui.timer(0.1, init_load, once=True)


def create_price_card(symbol: str):
    """创建价格卡片"""
    cached = market_api.get_cached_prices()
    price = cached.get(symbol, 0)
    
    # 默认价格
    default_prices = {
        "BTCUSDT": 95044.04,
        "BTCUSDT.P": 95100.00,
        "ETHUSDT": 3319.83,
        "ETHUSDT.P": 3320.50,
        "BNBUSDT": 947.68,
        "SOLUSDT": 142.21,
        "SOLUSDT.P": 142.50
    }
    
    if price == 0:
        price = default_prices.get(symbol, 0)
    
    with ui.card().classes("flex-1 bg-gray-800 cursor-pointer") as card:
        with ui.column().classes("gap-1"):
            ui.label(symbol).classes("text-sm text-gray-400")
            price_label = ui.label(f"${price:,.2f}").classes("text-xl font-bold text-white")
            ui.label("0.00%").classes("text-sm text-gray-400")
    
    return price_label


def create_empty_chart():
    """创建空白K线图"""
    chart_options = {
        "backgroundColor": "transparent",
        "grid": {
            "top": 40,
            "right": 50,
            "bottom": 30,
            "left": 60
        },
        "xAxis": {
            "type": "category",
            "data": ["等待加载..."],
            "axisLine": {"lineStyle": {"color": "#666"}},
            "axisLabel": {"color": "#999"}
        },
        "yAxis": {
            "type": "value",
            "scale": True,
            "axisLine": {"lineStyle": {"color": "#666"}},
            "axisLabel": {"color": "#999", "formatter": "${value}"},
            "splitLine": {"lineStyle": {"color": "#333"}}
        },
        "series": [{
            "type": "candlestick",
            "data": [],
            "itemStyle": {
                "color": "#10B981",
                "color0": "#EF4444",
                "borderColor": "#10B981",
                "borderColor0": "#EF4444"
            }
        }],
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
            "backgroundColor": "#333",
            "borderColor": "#555",
            "textStyle": {"color": "#fff"}
        }
    }
    
    return ui.echart(chart_options).classes("w-full h-80")


def create_orderbook_table(side: str):
    """创建订单簿表格"""
    columns = [
        {"name": "price", "label": "价格", "field": "price", "align": "left"},
        {"name": "quantity", "label": "数量", "field": "quantity", "align": "right"},
        {"name": "total", "label": "总额", "field": "total", "align": "right"},
    ]
    
    rows = [{"price": "加载中...", "quantity": "-", "total": "-"}]
    
    return ui.table(columns=columns, rows=rows, row_key="price").classes(
        "w-full bg-gray-700"
    ).props("dark dense")


# ===== 事件处理 =====

async def load_klines(symbol: str, interval: str, chart, label, button):
    """加载K线数据"""
    global _current_symbol, _current_interval
    
    _current_symbol = symbol
    _current_interval = interval
    
    # 禁用按钮显示加载状态
    button.disable()
    button.text = "加载中..."
    
    ui.notify(f"正在加载 {symbol} {interval} K线...", type="info")
    
    try:
        klines = await market_api.get_klines(symbol, interval, limit=100)
        
        if klines and len(klines) > 0:
            # 取最近50条
            display_klines = klines[-50:]
            
            # 更新图表
            chart.options["xAxis"]["data"] = [k["time"] for k in display_klines]
            chart.options["series"][0]["data"] = [
                [k["open"], k["close"], k["low"], k["high"]]
                for k in display_klines
            ]
            chart.update()
            
            # 更新标签
            label.text = f"({symbol} - {interval})"
            
            ui.notify(f"✅ 已加载 {len(display_klines)} 条 {interval} K线", type="positive")
        else:
            ui.notify("⚠️ 未获取到K线数据，请检查网络", type="warning")
            
    except Exception as e:
        ui.notify(f"❌ 加载失败: {e}", type="negative")
    finally:
        # 恢复按钮
        button.enable()
        button.text = "加载K线"


def add_new_symbol(input_elem, select_elem):
    """添加新交易对"""
    symbol = input_elem.value.strip().upper()
    if not symbol:
        return
        
    if market_api.add_symbol(symbol):
        ui.notify(f"已添加交易对: {symbol}", type="positive")
        # 刷新下拉框
        select_elem.options = market_api.get_available_symbols()
        select_elem.update()
        input_elem.value = ""
    else:
        ui.notify(f"交易对已存在或无法添加: {symbol}", type="warning")
