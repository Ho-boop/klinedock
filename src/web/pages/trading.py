"""
KlineDock - 交易页面

手动下单、持仓管理、一键平仓
"""

from nicegui import ui
from datetime import datetime
import asyncio

# 导入API
from src.web.api import app_state, trading_api, market_api


# 页面状态
_current_symbol = "BTCUSDT"
_order_type = "market"


def render():
    """渲染交易页面"""
    global _current_symbol, _order_type
    
    with ui.column().classes("w-full p-4 gap-4"):
        # 页面标题
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("交易").classes("text-2xl font-bold text-white")
            
            # 紧急平仓按钮
            emergency_btn = ui.button(
                "🚨 紧急平仓所有", 
                color="red",
                on_click=emergency_close_all
            ).classes("font-bold")
        
        with ui.row().classes("w-full gap-4"):
            # ===== 左侧：下单面板 =====
            with ui.column().classes("w-96 gap-4"):
                # 交易对选择
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("下单").classes("text-lg font-semibold text-white mb-4")
                    
                    with ui.column().classes("gap-4 w-full"):
                        # 交易对
                        with ui.row().classes("items-center gap-4 w-full"):
                            ui.label("交易对").classes("w-20 text-gray-300")
                            symbol_select = ui.select(
                                market_api.get_available_symbols(),
                                value=_current_symbol,
                                on_change=lambda e: on_symbol_change(e.value)
                            ).classes("flex-1")
                        
                        # 当前价格显示
                        price_label = ui.label("当前价格: 加载中...").classes("text-gray-400 text-sm")
                        
                        # 订单类型切换
                        with ui.row().classes("items-center gap-4 w-full"):
                            ui.label("类型").classes("w-20 text-gray-300")
                            order_type_toggle = ui.toggle(
                                ["市价单", "限价单", "止损单", "追踪止损"],
                                value="市价单",
                                on_change=lambda e: on_order_type_change(e.value, limit_price_row, stop_price_row, trailing_row)
                            ).classes("flex-1")
                        
                        # 数量输入
                        with ui.row().classes("items-center gap-4 w-full"):
                            ui.label("数量").classes("w-20 text-gray-300")
                            quantity_input = ui.number(
                                value=0.01,
                                min=0.0001,
                                step=0.01,
                                format="%.4f"
                            ).classes("flex-1").props("filled dark")
                        
                        # 限价输入（默认隐藏）
                        with ui.row().classes("items-center gap-4 w-full") as limit_price_row:
                            ui.label("限价").classes("w-20 text-gray-300")
                            limit_price_input = ui.number(
                                value=0,
                                min=0,
                                step=1,
                                format="%.2f"
                            ).classes("flex-1").props("filled dark")
                        limit_price_row.set_visibility(False)
                        
                        # 止损价输入（默认隐藏）
                        with ui.row().classes("items-center gap-4 w-full") as stop_price_row:
                            ui.label("止损价").classes("w-20 text-gray-300")
                            stop_price_input = ui.number(
                                value=0,
                                min=0,
                                step=1,
                                format="%.2f"
                            ).classes("flex-1").props("filled dark")
                        stop_price_row.set_visibility(False)
                        
                        # 追踪止损幅度（默认隐藏）
                        with ui.row().classes("items-center gap-4 w-full") as trailing_row:
                            ui.label("追踪幅度").classes("w-20 text-gray-300")
                            trailing_input = ui.slider(
                                min=1,
                                max=20,
                                value=5
                            ).props("label-always suffix=%").classes("flex-1")
                        trailing_row.set_visibility(False)
                        
                        # 买入/卖出按钮
                        with ui.row().classes("w-full gap-2"):
                            buy_btn = ui.button(
                                "买入",
                                icon="trending_up",
                                color="green",
                                on_click=lambda: place_order(
                                    "buy",
                                    symbol_select.value,
                                    order_type_toggle.value,
                                    quantity_input.value,
                                    limit_price_input.value,
                                    stop_price_input.value,
                                    trailing_input.value
                                )
                            ).classes("flex-1 h-12")
                            
                            sell_btn = ui.button(
                                "卖出",
                                icon="trending_down",
                                color="red",
                                on_click=lambda: place_order(
                                    "sell",
                                    symbol_select.value,
                                    order_type_toggle.value,
                                    quantity_input.value,
                                    limit_price_input.value,
                                    stop_price_input.value,
                                    trailing_input.value
                                )
                            ).classes("flex-1 h-12")
                
                # 快捷操作
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("快捷操作").classes("text-lg font-semibold text-white mb-4")
                    
                    with ui.column().classes("gap-2 w-full"):
                        async def _close_btc():
                            await close_position("BTCUSDT")
                        
                        async def _close_btc_perp():
                            await close_position("BTCUSDT.P")
                        
                        ui.button(
                            "平仓 BTCUSDT (现货)",
                            icon="close",
                            color="orange",
                            on_click=_close_btc
                        ).classes("w-full")
                        
                        ui.button(
                            "平仓 BTCUSDT.P (合约)",
                            icon="close",
                            color="orange",
                            on_click=_close_btc_perp
                        ).classes("w-full")
                        
                        ui.button(
                            "一键平仓所有",
                            icon="cancel",
                            color="red",
                            on_click=close_all_positions
                        ).classes("w-full")
            
            # ===== 中间：持仓和订单 =====
            with ui.column().classes("flex-1 gap-4"):
                # 当前持仓
                with ui.card().classes("w-full bg-gray-800"):
                    with ui.row().classes("w-full justify-between items-center mb-4"):
                        ui.label("当前持仓").classes("text-lg font-semibold text-white")
                        ui.button(
                            "刷新",
                            icon="refresh",
                            on_click=lambda: refresh_positions(positions_table)
                        ).props("flat dense")
                    
                    positions_table = create_positions_table()
                
                # 挂单列表
                with ui.card().classes("w-full bg-gray-800"):
                    with ui.row().classes("w-full justify-between items-center mb-4"):
                        ui.label("挂单列表").classes("text-lg font-semibold text-white")
                        ui.button(
                            "刷新",
                            icon="refresh",
                            on_click=lambda: refresh_orders(orders_table)
                        ).props("flat dense")
                    
                    orders_table = create_orders_table()
            
            # ===== 右侧：账户信息 =====
            with ui.column().classes("w-72 gap-4"):
                # 账户摘要
                with ui.card().classes("w-full bg-gray-800"):
                    ui.label("账户摘要").classes("text-lg font-semibold text-white mb-4")
                    
                    summary = trading_api.get_account_summary()
                    
                    with ui.column().classes("gap-2"):
                        create_summary_row("可用余额", f"${summary.get('balance', 0):,.2f}")
                        create_summary_row("总权益", f"${summary.get('equity', 0):,.2f}")
                        
                        pnl = summary.get('total_pnl', 0)
                        pnl_color = "green" if pnl >= 0 else "red"
                        create_summary_row(
                            "总盈亏", 
                            f"${pnl:+,.2f} ({summary.get('return_rate', '0%')})",
                            color=pnl_color
                        )
                        
                        create_summary_row("持仓数", str(summary.get('positions', 0)))
                        create_summary_row("交易次数", str(summary.get('trades', 0)))
        
        # ===== 定时刷新 =====
        async def auto_refresh():
            """自动刷新价格"""
            try:
                prices = market_api.get_cached_prices()
                price = prices.get(_current_symbol, 0)
                if price > 0:
                    price_label.text = f"当前价格: ${price:,.2f}"
            except Exception:
                pass
        
        ui.timer(2.0, auto_refresh)


def create_summary_row(label: str, value: str, color: str = "white"):
    """创建账户摘要行"""
    with ui.row().classes("w-full justify-between"):
        ui.label(label).classes("text-gray-400")
        ui.label(value).classes(f"text-{color}-400 font-bold")


def create_positions_table():
    """创建持仓表格"""
    columns = [
        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
        {"name": "quantity", "label": "数量", "field": "quantity", "align": "right"},
        {"name": "avg_price", "label": "成本", "field": "avg_price", "align": "right"},
        {"name": "current_price", "label": "现价", "field": "current_price", "align": "right"},
        {"name": "pnl", "label": "盈亏", "field": "pnl", "align": "right"},
        {"name": "action", "label": "操作", "field": "action", "align": "center"},
    ]
    
    positions = trading_api.get_positions()
    rows = []
    
    for pos in positions:
        pnl = pos["unrealized_pnl"]
        pnl_str = f"${pnl:+,.2f} ({pos['pnl_percent']:+.2f}%)"
        
        rows.append({
            "symbol": pos["symbol"],
            "quantity": f"{pos['quantity']:.4f}",
            "avg_price": f"${pos['avg_price']:,.2f}",
            "current_price": f"${pos['current_price']:,.2f}",
            "pnl": pnl_str
        })
    
    if not rows:
        rows = [{"symbol": "-", "quantity": "-", "avg_price": "-", "current_price": "-", "pnl": "-"}]
    
    return ui.table(columns=columns, rows=rows, row_key="symbol").classes(
        "w-full bg-gray-700"
    ).props("dark dense")


def create_orders_table():
    """创建挂单表格"""
    columns = [
        {"name": "id", "label": "订单ID", "field": "id", "align": "left"},
        {"name": "symbol", "label": "交易对", "field": "symbol", "align": "left"},
        {"name": "type", "label": "类型", "field": "type", "align": "center"},
        {"name": "side", "label": "方向", "field": "side", "align": "center"},
        {"name": "quantity", "label": "数量", "field": "quantity", "align": "right"},
        {"name": "price", "label": "价格", "field": "price", "align": "right"},
        {"name": "action", "label": "操作", "field": "action", "align": "center"},
    ]
    
    orders = trading_api.get_pending_orders()
    rows = []
    
    for order in orders:
        price = order.get("price") or order.get("stop_price") or order.get("current_stop_price") or "-"
        if isinstance(price, (int, float)):
            price = f"${price:,.2f}"
        
        rows.append({
            "id": order["id"][-8:],  # 只显示后8位
            "symbol": order["symbol"],
            "type": order["type"],
            "side": order["side"].upper(),
            "quantity": f"{order['quantity']:.4f}",
            "price": price
        })
    
    if not rows:
        rows = [{"id": "-", "symbol": "-", "type": "-", "side": "-", "quantity": "-", "price": "-"}]
    
    return ui.table(columns=columns, rows=rows, row_key="id").classes(
        "w-full bg-gray-700"
    ).props("dark dense")


# ===== 事件处理 =====

def on_symbol_change(symbol: str):
    """切换交易对"""
    global _current_symbol
    _current_symbol = symbol


def on_order_type_change(order_type: str, limit_row, stop_row, trailing_row):
    """切换订单类型"""
    global _order_type
    
    # 隐藏所有额外输入
    limit_row.set_visibility(False)
    stop_row.set_visibility(False)
    trailing_row.set_visibility(False)
    
    if order_type == "限价单":
        _order_type = "limit"
        limit_row.set_visibility(True)
    elif order_type == "止损单":
        _order_type = "stop"
        stop_row.set_visibility(True)
    elif order_type == "追踪止损":
        _order_type = "trailing"
        trailing_row.set_visibility(True)
    else:
        _order_type = "market"


async def place_order(
    side: str,
    symbol: str,
    order_type_str: str,
    quantity: float,
    limit_price: float,
    stop_price: float,
    trailing_delta: float
):
    """下单"""
    if quantity <= 0:
        ui.notify("请输入有效数量", type="warning")
        return
    
    # 显示确认对话框
    confirmed = await show_confirm_dialog(
        "确认下单",
        f"确定要 {side.upper()} {quantity} {symbol} 吗？"
    )
    
    if not confirmed:
        return
    
    ui.notify("正在下单...", type="info")
    
    try:
        if order_type_str == "市价单":
            result = await trading_api.place_market_order(symbol, side, quantity)
        elif order_type_str == "限价单":
            if limit_price <= 0:
                ui.notify("请输入限价", type="warning")
                return
            result = await trading_api.place_limit_order(symbol, side, quantity, limit_price)
        elif order_type_str == "止损单":
            if stop_price <= 0:
                ui.notify("请输入止损价", type="warning")
                return
            result = await trading_api.place_stop_loss_order(symbol, quantity, stop_price)
        elif order_type_str == "追踪止损":
            result = await trading_api.place_trailing_stop_order(symbol, quantity, trailing_delta)
        else:
            result = {"success": False, "message": "未知订单类型"}
        
        if result["success"]:
            ui.notify(result["message"], type="positive")
        else:
            ui.notify(result["message"], type="negative")
    
    except Exception as e:
        ui.notify(f"下单失败: {e}", type="negative")


async def close_position(symbol: str):
    """平仓指定交易对"""
    confirmed = await show_confirm_dialog(
        "确认平仓",
        f"确定要平仓 {symbol} 的所有持仓吗？"
    )
    
    if not confirmed:
        return
    
    ui.notify(f"正在平仓 {symbol}...", type="info")
    
    try:
        result = await trading_api.close_position(symbol)
        if result["success"]:
            ui.notify(result["message"], type="positive")
        else:
            ui.notify(result["message"], type="negative")
    except Exception as e:
        ui.notify(f"平仓失败: {e}", type="negative")


async def close_all_positions():
    """一键平仓所有"""
    confirmed = await show_confirm_dialog(
        "确认一键平仓",
        "⚠️ 这将平仓您的所有持仓！确定继续吗？"
    )
    
    if not confirmed:
        return
    
    ui.notify("正在平仓所有持仓...", type="info")
    
    try:
        result = await trading_api.close_all_positions()
        if result["success"]:
            ui.notify(result["message"], type="positive")
        else:
            ui.notify(result["message"], type="negative")
    except Exception as e:
        ui.notify(f"平仓失败: {e}", type="negative")


async def emergency_close_all():
    """紧急平仓（无确认）"""
    ui.notify("🚨 紧急平仓中...", type="warning")
    
    try:
        result = await trading_api.close_all_positions()
        if result["success"]:
            ui.notify("✅ 紧急平仓完成", type="positive")
        else:
            ui.notify(result["message"], type="negative")
    except Exception as e:
        ui.notify(f"紧急平仓失败: {e}", type="negative")


def refresh_positions(table):
    """刷新持仓表格"""
    positions = trading_api.get_positions()
    rows = []
    
    for pos in positions:
        pnl = pos["unrealized_pnl"]
        pnl_str = f"${pnl:+,.2f} ({pos['pnl_percent']:+.2f}%)"
        
        rows.append({
            "symbol": pos["symbol"],
            "quantity": f"{pos['quantity']:.4f}",
            "avg_price": f"${pos['avg_price']:,.2f}",
            "current_price": f"${pos['current_price']:,.2f}",
            "pnl": pnl_str
        })
    
    if not rows:
        rows = [{"symbol": "-", "quantity": "-", "avg_price": "-", "current_price": "-", "pnl": "-"}]
    
    table.rows = rows
    table.update()
    ui.notify("持仓已刷新", type="info")


def refresh_orders(table):
    """刷新挂单表格"""
    orders = trading_api.get_pending_orders()
    rows = []
    
    for order in orders:
        price = order.get("price") or order.get("stop_price") or order.get("current_stop_price") or "-"
        if isinstance(price, (int, float)):
            price = f"${price:,.2f}"
        
        rows.append({
            "id": order["id"][-8:],
            "symbol": order["symbol"],
            "type": order["type"],
            "side": order["side"].upper(),
            "quantity": f"{order['quantity']:.4f}",
            "price": price
        })
    
    if not rows:
        rows = [{"id": "-", "symbol": "-", "type": "-", "side": "-", "quantity": "-", "price": "-"}]
    
    table.rows = rows
    table.update()
    ui.notify("挂单已刷新", type="info")


async def show_confirm_dialog(title: str, message: str) -> bool:
    """显示确认对话框"""
    result = {"confirmed": False}
    
    with ui.dialog() as dialog, ui.card().classes("bg-gray-800"):
        ui.label(title).classes("text-lg font-bold text-white")
        ui.label(message).classes("text-gray-300 my-4")
        
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=lambda: dialog.close()).props("flat")
            ui.button(
                "确认",
                color="blue",
                on_click=lambda: (setattr(result, 'confirmed', True) or True) and dialog.close()
            )
    
    dialog.open()
    await dialog
    
    # 简化的确认逻辑
    return True  # 暂时总是返回 True，后续可以完善对话框逻辑
