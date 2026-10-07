"""
KlineDock - 回测报告页面

显示回测结果的K线图、交易标记和绩效指标
"""

from nicegui import ui
import json

# 全局存储回测结果
_backtest_result = None


def set_result(result: dict):
    """设置回测结果"""
    global _backtest_result
    _backtest_result = result


def get_result():
    """获取回测结果"""
    return _backtest_result


def render():
    """渲染回测报告页面"""
    global _backtest_result
    
    if not _backtest_result:
        with ui.column().classes("w-full h-screen items-center justify-center bg-gray-900"):
            ui.label("暂无回测数据").classes("text-2xl text-gray-400")
            ui.button("返回策略页", icon="arrow_back", on_click=lambda: ui.navigate.to("/strategies")).classes("mt-4")
        return
    
    metrics = _backtest_result.get("metrics", {})
    trades = _backtest_result.get("trades", [])
    market_data = _backtest_result.get("market_data", {})
    
    # 准备图表数据
    chart_options = None
    symbol = "N/A"
    if market_data:
        symbol = list(market_data.keys())[0]
        klines = market_data[symbol]
        dates = [k["time"] for k in klines]
        values = [[k["open"], k["close"], k["low"], k["high"]] for k in klines]
        
        # 准备交易标记
        mark_points = []
        for t in trades:
            if t["symbol"] == symbol:
                color = "#ef4444" if t["side"] == "sell" else "#22c55e"
                mark_points.append({
                    "name": t["side"],
                    "coord": [t["timestamp"], t["price"]],
                    "value": t["side"].upper(),
                    "itemStyle": {"color": color},
                    "symbol": "arrow" if t["side"] == "buy" else "pin",
                    "symbolRotate": 0 if t["side"] == "buy" else 180,
                })

        chart_options = {
            "backgroundColor": "#1f2937",
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
            "grid": {"left": "3%", "right": "3%", "bottom": "15%", "top": "5%", "containLabel": True},
            "xAxis": {
                "type": "category", 
                "data": dates, 
                "scale": True, 
                "boundaryGap": False,
                "axisLine": {"onZero": False, "lineStyle": {"color": "#6b7280"}},
                "splitLine": {"show": False},
                "axisLabel": {"color": "#9ca3af"},
            },
            "yAxis": {
                "scale": True, 
                "splitArea": {"show": True, "areaStyle": {"color": ["#1f2937", "#111827"]}},
                "axisLine": {"lineStyle": {"color": "#6b7280"}},
                "axisLabel": {"color": "#9ca3af"},
                "splitLine": {"lineStyle": {"color": "#374151"}},
            },
            "dataZoom": [
                {"type": "inside", "start": 50, "end": 100},
                {"show": True, "type": "slider", "bottom": "5%", "start": 50, "end": 100,
                 "borderColor": "#374151", "fillerColor": "rgba(59, 130, 246, 0.3)"}
            ],
            "series": [{
                "name": symbol, 
                "type": "candlestick", 
                "data": values,
                "itemStyle": {
                    "color": "#22c55e",      # 涨
                    "color0": "#ef4444",     # 跌
                    "borderColor": "#22c55e",
                    "borderColor0": "#ef4444"
                },
                "markPoint": {
                    "data": mark_points, 
                    "symbolSize": 30,
                    "label": {"show": False}
                }
            }]
        }

    # 页面布局
    with ui.column().classes("w-full min-h-screen bg-gray-900 p-6"):
        # 顶部导航栏
        with ui.row().classes("w-full justify-between items-center mb-6"):
            with ui.row().classes("items-center gap-4"):
                ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/strategies")).props("flat color=white")
                ui.label("回测详细报告").classes("text-2xl font-bold text-white")
                ui.badge(symbol).classes("text-lg")
            
            with ui.row().classes("gap-2"):
                def export_report():
                    if not _backtest_result:
                        ui.notify("暂无可导出的数据", type="warning")
                        return
                    
                    metrics = _backtest_result.get("metrics", {})
                    trades = _backtest_result.get("trades", [])
                    
                    # 生成清晰的中文文本报告
                    lines = []
                    lines.append("==================================================")
                    lines.append("          KlineDock - 量化回测报告")
                    lines.append("==================================================")
                    lines.append("")
                    
                    lines.append("【一、核心绩效指标】")
                    lines.append("-" * 30)
                    lines.append(f"总收益率   : {metrics.get('total_return', '0%')}")
                    lines.append(f"夏普比率   : {metrics.get('sharpe_ratio', '0.00')}")
                    lines.append(f"最大回撤   : {metrics.get('max_drawdown', '0%')}")
                    lines.append(f"交易胜率   : {metrics.get('win_rate', '0%')}")
                    lines.append(f"总交易次数 : {metrics.get('total_trades', 0)} 次")
                    lines.append("")
                    
                    lines.append("【二、交易流水明细】")
                    lines.append("-" * 30)
                    if not trades:
                        lines.append("本次回测暂无任何交易触发。")
                    else:
                        for idx, t in enumerate(trades, 1):
                            time_str = t.get("timestamp", "未知时间")
                            symbol = t.get("symbol", "-")
                            side = t.get("side", "").upper()
                            action_cn = "买入(做多)" if side == "BUY" else "卖出(做空/平仓)" if side == "SELL" else side
                            price = t.get("price", 0.0)
                            qty = t.get("quantity", 0.0)
                            reason = t.get("reason", "")
                            
                            detail = f"[{idx:03d}] 时间: {time_str} | 标的: {symbol} | 操作: {action_cn} | 价格: ${price:,.2f} | 数量: {qty:.4f}"
                            if reason:
                                detail += f" | 原因: {reason}"
                            lines.append(detail)
                    
                    lines.append("")
                    lines.append("==================================================")
                    lines.append("注：该报告由系统根据历史行情数据推演生成，不构成投资建议。")
                    
                    # 加入 UTF-8 BOM 防止 Windows 下记事本乱码
                    report_text = "\n".join(lines)
                    ui.download(report_text.encode('utf-8-sig'), filename="回测统计报告.txt")
                    ui.notify("中文报告已生成并下载", type="positive")

                ui.button("导出报告", icon="download", on_click=export_report).props("flat color=blue")
                ui.button("重新回测", icon="refresh", on_click=lambda: ui.navigate.to("/strategies")).props("flat color=green")
        
        # 主内容区
        with ui.row().classes("w-full gap-6"):
            # 左侧：K线图表 (占据大部分宽度)
            with ui.card().classes("flex-1 bg-gray-800 p-4"):
                ui.label(f"K线图 - {symbol}").classes("text-lg font-bold text-white mb-2")
                if chart_options:
                    ui.echart(options=chart_options).classes("w-full").style("height: 500px")
                else:
                    ui.label("无图表数据").classes("text-gray-400")
            
            # 右侧：指标面板
            with ui.column().classes("w-80 gap-4"):
                # 绩效指标卡片
                with ui.card().classes("w-full bg-gray-800 p-4"):
                    ui.label("绩效指标").classes("text-lg font-bold text-white mb-4")
                    
                    # 总收益率 - 大字显示
                    pnl = metrics.get('total_return', '0%')
                    pnl_color = "green-400" if not str(pnl).startswith("-") else "red-400"
                    ui.label(f"{pnl}").classes(f"text-4xl font-bold text-{pnl_color} mb-2")
                    ui.label("总收益率").classes("text-sm text-gray-400 mb-4")
                    
                    ui.separator().classes("my-2")
                    
                    # 其他指标
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        def metric_item(label, value, color="white"):
                            with ui.column().classes("bg-gray-700 p-3 rounded"):
                                ui.label(str(value)).classes(f"text-xl font-bold text-{color}")
                                ui.label(label).classes("text-xs text-gray-400")
                        
                        metric_item("夏普比率", metrics.get('sharpe_ratio', '0.00'))
                        metric_item("最大回撤", metrics.get('max_drawdown', '0%'), "red-400")
                        metric_item("胜率", metrics.get('win_rate', '0%'))
                        metric_item("总交易数", metrics.get('total_trades', 0))
                
                # 交易记录
                with ui.card().classes("w-full bg-gray-800 p-4 max-h-80 overflow-auto"):
                    ui.label(f"交易记录 ({len(trades)} 笔)").classes("text-lg font-bold text-white mb-4")
                    
                    if trades:
                        for t in reversed(trades[-15:]):
                            side_color = "green" if t["side"] == "buy" else "red"
                            with ui.row().classes("w-full justify-between items-center py-2 border-b border-gray-700"):
                                with ui.column().classes("gap-0"):
                                    ui.label(t["side"].upper()).classes(f"text-{side_color}-400 font-bold text-sm")
                                    ui.label(t["timestamp"]).classes("text-xs text-gray-500")
                                ui.label(f"${t['price']:,.2f}").classes("text-white font-mono")
                    else:
                        ui.label("无交易记录").classes("text-gray-500")
