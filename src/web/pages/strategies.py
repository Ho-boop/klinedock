"""
KlineDock - 策略管理页面

策略列表、参数编辑和控制
"""

from nicegui import ui
import asyncio

# 导入API
from src.web.api import app_state, engine_api, strategy_api, market_api


# 页面状态
_selected_strategy = None


def render():
    """渲染策略管理页面"""
    global _selected_strategy
    
    # 初始化：发现策略
    strategies = strategy_api.list_strategies()
    
    with ui.column().classes("w-full p-4 gap-4"):
        # 页面标题
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("策略管理").classes("text-2xl font-bold text-white")
            with ui.row().classes("gap-2"):
                ui.button(
                    "刷新", 
                    icon="refresh",
                    on_click=lambda: refresh_strategies()
                ).props("flat")
                ui.button("新建策略", icon="add", color="blue").disable().tooltip("请在 plugins/strategies 添加策略插件后刷新")
        
        # ===== 策略列表 =====
        with ui.card().classes("w-full bg-gray-800") as strategy_list_card:
            ui.label("已加载策略").classes("text-lg font-semibold text-white mb-4")
            
            # 动态加载策略卡片
            for strategy in strategies:
                create_strategy_card(
                    name=strategy["name"],
                    version=strategy["version"],
                    description=get_strategy_description(strategy["name"]),
                    status=strategy["status"],
                    params=strategy["parameters"],
                    stats={
                        "trades": strategy["trades_count"],
                        "pnl": strategy["pnl"],
                        "win_rate": strategy["win_rate"]
                    }
                )
                ui.separator().classes("my-4")
        
        # ===== 策略编辑器 =====
        with ui.card().classes("w-full bg-gray-800"):
            ui.label("策略参数编辑").classes("text-lg font-semibold text-white mb-4")
            
            with ui.row().classes("gap-8"):
                # 左侧：参数
                with ui.column().classes("flex-1 gap-4"):
                    # 交易对
                    with ui.row().classes("items-center gap-4"):
                        ui.label("交易对").classes("w-24 text-gray-300")
                        symbols_select = ui.select(
                            market_api.get_available_symbols(), 
                            value=["BTCUSDT"], 
                            multiple=True
                        ).classes("flex-1")
                
                # 右侧：操作
                with ui.column().classes("w-48 gap-2"):
                    

                    
                    ui.button(
                        "高级回测",
                        icon="science",
                        color="green",
                        on_click=lambda: open_backtest_dialog(symbols_select.value)
                    ).classes("w-full")


def create_strategy_card(
    name: str, 
    version: str, 
    description: str,
    status: str, 
    params: dict, 
    stats: dict
):
    """创建策略卡片"""
    
    status_colors = {
        "running": ("green", "运行中", "play_circle"),
        "stopped": ("gray", "已停止", "stop_circle"),
        "error": ("red", "错误", "error"),
    }
    
    color, status_text, icon = status_colors.get(status, ("gray", "未知", "help"))
    
    with ui.card().classes("w-full bg-gray-700 p-4"):
        with ui.row().classes("w-full justify-between items-start"):
            # 策略信息
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(name).classes("text-lg font-semibold text-white")
                    ui.badge(f"v{version}").classes("text-xs")
                
                ui.label(description).classes("text-sm text-gray-400")
                
                # 参数显示
                if params:
                    params_str = ", ".join([f"{k}={v}" for k, v in params.items()])
                    ui.label(f"参数: {params_str}").classes("text-xs text-gray-500")
            
            # 状态和操作
            with ui.column().classes("items-end gap-2"):
                with ui.row().classes("items-center gap-1"):
                    ui.icon(icon, color=color)
                    ui.label(status_text).classes(f"text-{color}-400")
                
                with ui.row().classes("gap-1"):
                    if status == "running":
                        ui.button(
                            icon="stop", 
                            color="red",
                            on_click=lambda n=name: stop_single_strategy(n)
                        ).props("flat dense")
                    else:
                        ui.button(
                            icon="play_arrow", 
                            color="green",
                            on_click=lambda n=name: start_single_strategy(n)
                        ).props("flat dense")
                    ui.button(icon="edit").props("flat dense")
                    ui.button(
                        icon="delete", 
                        color="red"
                    ).props("flat dense")
        
        # 统计信息
        with ui.row().classes("mt-4 gap-8"):
            with ui.column().classes("items-center"):
                ui.label(str(stats["trades"])).classes("text-xl font-bold text-white")
                ui.label("交易次数").classes("text-xs text-gray-400")
            
            with ui.column().classes("items-center"):
                pnl = stats["pnl"]
                pnl_color = "green" if not str(pnl).startswith("-") else "red"
                ui.label(pnl).classes(f"text-xl font-bold text-{pnl_color}-400")
                ui.label("收益率").classes("text-xs text-gray-400")
            
            with ui.column().classes("items-center"):
                ui.label(stats["win_rate"]).classes("text-xl font-bold text-white")
                ui.label("胜率").classes("text-xs text-gray-400")


def get_strategy_description(name: str) -> str:
    """获取策略描述"""
    descriptions = {
        "ma_cross": "双均线交叉策略 - 金叉买入，死叉卖出",
        "rsi_reversal": "RSI超买超卖均值回归策略",
        "momentum": "动量突破策略",
    }
    return descriptions.get(name, "量化交易策略")


# ===== 对话框和流程 =====

def open_create_strategy_dialog():
    """打开新建策略对话框"""
    with ui.dialog() as dialog, ui.card().classes("w-[700px] bg-gray-800"):
        ui.label("新建策略").classes("text-xl font-bold text-white mb-4")
        
        with ui.column().classes("w-full gap-4"):
            # 基本信息
            ui.label("基本信息").classes("text-blue-400 text-sm font-bold")
            with ui.row().classes("w-full gap-4"):
                strategy_name_input = ui.input(
                    label="策略名称 (英文，如 my_strategy)",
                    placeholder="my_strategy",
                    validation={"只能使用字母、数字和下划线": lambda v: v.replace("_", "").isalnum() if v else True}
                ).classes("flex-1").props("filled dark")
                
                strategy_version_input = ui.input(
                    label="版本号",
                    value="1.0.0"
                ).classes("w-32").props("filled dark")
            
            strategy_desc_input = ui.input(
                label="策略描述",
                placeholder="简要描述策略逻辑"
            ).classes("w-full").props("filled dark")
            
            ui.separator().classes("my-2")
            
            # 策略类型选择
            ui.label("策略模板").classes("text-blue-400 text-sm font-bold")
            template_select = ui.select(
                {
                    "ma_cross": "均线交叉策略 (MA Cross)",
                    "rsi": "RSI 超买超卖策略",
                    "momentum": "动量突破策略",
                    "blank": "空白策略 (从零开始)"
                },
                value="blank",
                label="选择模板"
            ).classes("w-full").props("filled dark")
            
            # 模板描述
            template_descriptions = {
                "ma_cross": "基于双均线交叉的趋势跟踪策略。金叉买入，死叉卖出。",
                "rsi": "基于 RSI 指标的均值回归策略。超卖买入，超买卖出。",
                "momentum": "基于价格动量的突破策略。突破阻力位买入，跌破支撑位卖出。",
                "blank": "空白策略骨架，包含必要的接口方法，您可以自由实现逻辑。"
            }
            template_desc_label = ui.label(template_descriptions["blank"]).classes("text-gray-400 text-sm")
            
            def update_template_desc():
                template_desc_label.text = template_descriptions.get(template_select.value, "")
            
            template_select.on("update:model-value", lambda: update_template_desc())
            
            ui.separator().classes("my-2")
            
            # 策略参数配置
            ui.label("默认参数").classes("text-blue-400 text-sm font-bold")
            with ui.row().classes("w-full gap-4"):
                param1_name = ui.input(label="参数1名称", value="period").classes("flex-1").props("filled dark")
                param1_value = ui.input(label="参数1默认值", value="14").classes("flex-1").props("filled dark")
            with ui.row().classes("w-full gap-4"):
                param2_name = ui.input(label="参数2名称", value="threshold").classes("flex-1").props("filled dark")
                param2_value = ui.input(label="参数2默认值", value="0.5").classes("flex-1").props("filled dark")
            
            # 提示
            with ui.card().classes("w-full bg-gray-700 p-3"):
                ui.label("📁 策略文件将创建在:").classes("text-gray-300 text-sm")
                ui.label("src/strategies/<策略名>.py").classes("text-blue-400 text-sm font-mono")
            
            # 按钮区
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=dialog.close).props("flat")
                
                def _on_create():
                    name = strategy_name_input.value
                    if not name:
                        ui.notify("请输入策略名称", type="warning")
                        return
                    
                    # 生成策略文件
                    success = create_strategy_file(
                        name=name,
                        version=strategy_version_input.value,
                        description=strategy_desc_input.value,
                        template=template_select.value,
                        params={
                            param1_name.value: param1_value.value,
                            param2_name.value: param2_value.value
                        }
                    )
                    
                    if success:
                        ui.notify(f"策略 '{name}' 创建成功！", type="positive")
                        dialog.close()
                        # 刷新策略列表
                        refresh_strategies()
                    else:
                        ui.notify("策略创建失败，请检查名称是否重复", type="negative")
                
                ui.button("创建策略", color="green", icon="add", on_click=_on_create)
    
    dialog.open()


def create_strategy_file(name: str, version: str, description: str, template: str, params: dict) -> bool:
    """UI scaffolding is disabled; plugins require a Python module and YAML metadata."""
    return False


def generate_strategy_code(name: str, version: str, description: str, template: str, params: dict) -> str:
    """根据模板生成策略代码"""
    
    # 参数字符串
    params_str = ",\n        ".join([f'"{k}": {v}' for k, v in params.items() if k])
    
    # 根据模板生成不同的逻辑
    if template == "ma_cross":
        logic = '''
    def on_bar(self, bar: dict) -> list:
        """K线数据触发"""
        signals = []
        symbol = bar.get("symbol")
        close = bar.get("close")
        
        # 计算均线 (简化示例)
        fast_period = self.parameters.get("fast_period", 5)
        slow_period = self.parameters.get("slow_period", 20)
        
        # TODO: 实现均线计算逻辑
        # fast_ma = calculate_ma(close_prices, fast_period)
        # slow_ma = calculate_ma(close_prices, slow_period)
        
        # 金叉买入
        # if fast_ma > slow_ma and prev_fast_ma <= prev_slow_ma:
        #     signals.append({"symbol": symbol, "side": "buy", "reason": "金叉"})
        
        # 死叉卖出
        # if fast_ma < slow_ma and prev_fast_ma >= prev_slow_ma:
        #     signals.append({"symbol": symbol, "side": "sell", "reason": "死叉"})
        
        return signals'''
    elif template == "rsi":
        logic = '''
    def on_bar(self, bar: dict) -> list:
        """K线数据触发"""
        signals = []
        symbol = bar.get("symbol")
        
        # RSI 参数
        period = self.parameters.get("period", 14)
        oversold = self.parameters.get("oversold", 30)
        overbought = self.parameters.get("overbought", 70)
        
        # TODO: 实现 RSI 计算逻辑
        # rsi = calculate_rsi(close_prices, period)
        
        # 超卖买入
        # if rsi < oversold:
        #     signals.append({"symbol": symbol, "side": "buy", "reason": f"RSI={rsi:.1f} 超卖"})
        
        # 超买卖出
        # if rsi > overbought:
        #     signals.append({"symbol": symbol, "side": "sell", "reason": f"RSI={rsi:.1f} 超买"})
        
        return signals'''
    elif template == "momentum":
        logic = '''
    def on_bar(self, bar: dict) -> list:
        """K线数据触发"""
        signals = []
        symbol = bar.get("symbol")
        close = bar.get("close")
        high = bar.get("high")
        low = bar.get("low")
        
        # 动量参数
        lookback = self.parameters.get("lookback", 20)
        threshold = self.parameters.get("threshold", 0.02)
        
        # TODO: 实现动量突破逻辑
        # highest = max(highs[-lookback:])
        # lowest = min(lows[-lookback:])
        
        # 突破高点买入
        # if close > highest * (1 + threshold):
        #     signals.append({"symbol": symbol, "side": "buy", "reason": "突破高点"})
        
        # 跌破低点卖出
        # if close < lowest * (1 - threshold):
        #     signals.append({"symbol": symbol, "side": "sell", "reason": "跌破低点"})
        
        return signals'''
    else:  # blank
        logic = '''
    def on_bar(self, bar: dict) -> list:
        """K线数据触发 - 在此实现您的策略逻辑"""
        signals = []
        symbol = bar.get("symbol")
        close = bar.get("close")
        
        # TODO: 实现您的策略逻辑
        # 返回信号列表，每个信号是一个字典：
        # {"symbol": "BTCUSDT", "side": "buy" or "sell", "reason": "信号原因"}
        
        return signals'''
    
    code = f'''"""
{description or name + " 策略"}

自动生成的策略文件
"""

from src.strategy.base_strategy import BaseStrategy


class {name.title().replace("_", "")}Strategy(BaseStrategy):
    """
    {description or name}
    
    版本: {version}
    """
    
    # 策略元数据
    name = "{name}"
    version = "{version}"
    
    # 默认参数
    default_parameters = {{
        {params_str}
    }}
    
    def __init__(self, parameters: dict = None):
        """初始化策略"""
        super().__init__(parameters)
        self.positions = {{}}  # 持仓状态

    def on_init(self):
        """策略初始化"""
        self.logger.info(f"策略 {{self.name}} v{{self.version}} 初始化完成")
        self.logger.info(f"参数: {{self.parameters}}")
{logic}

    def on_trade(self, trade: dict):
        """成交回报"""
        symbol = trade.get("symbol")
        side = trade.get("side")
        price = trade.get("price")
        self.logger.info(f"成交: {{symbol}} {{side}} @ {{price}}")

    def on_stop(self):
        """策略停止"""
        self.logger.info(f"策略 {{self.name}} 已停止")
'''
    return code


def open_backtest_dialog(symbols):
    """打开回测配置对话框 - 支持策略选择"""
    
    # 获取所有已加载的策略
    all_strategies = strategy_api.list_strategies()
    strategy_names = [s["name"] for s in all_strategies] if all_strategies else ["ma_cross"]
    
    with ui.dialog() as dialog, ui.card().classes("w-[600px] bg-gray-800"):
        ui.label("回测配置").classes("text-xl font-bold text-white mb-4")
        
        with ui.column().classes("w-full gap-4"):
            # ===== 策略选择 =====
            ui.label("策略选择").classes("text-blue-400 text-sm font-bold")
            with ui.row().classes("w-full gap-4 items-end"):
                strategy_select = ui.select(
                    strategy_names, 
                    value="ma_cross" if "ma_cross" in strategy_names else strategy_names[0],
                    label="选择回测策略"
                ).classes("flex-1").props("filled dark")
                
                # 策略描述
                strategy_desc = ui.label(get_strategy_description("ma_cross")).classes("text-gray-400 text-xs")
                
                def update_description():
                    strategy_desc.text = get_strategy_description(strategy_select.value)
                
                strategy_select.on("update:model-value", lambda: update_description())
            
            ui.separator().classes("my-2")
            
            # ===== 交易标的 =====
            ui.label("交易标的").classes("text-blue-400 text-sm font-bold")
            symbols_input = ui.select(
                ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", 
                 "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"],
                value=symbols if symbols else ["BTCUSDT"],
                label="选择交易对",
                multiple=True
            ).classes("w-full").props("filled dark use-chips")
            
            ui.separator().classes("my-2")
            
            # ===== 资金设置 =====
            ui.label("资金设置").classes("text-blue-400 text-sm font-bold")
            with ui.row().classes("w-full gap-4"):
                capital_input = ui.number(
                    label="初始资金 ($)", 
                    value=100000, 
                    min=1000,
                    format="%.0f"
                ).classes("flex-1").props("filled dark")
                
                commission_input = ui.number(
                    label="手续费率 (%)", 
                    value=0.1, 
                    min=0, 
                    step=0.01,
                    format="%.2f"
                ).classes("flex-1").props("filled dark")

            ui.separator().classes("my-2")

            # ===== 回测区间 =====
            ui.label("回测区间").classes("text-blue-400 text-sm font-bold")
            with ui.row().classes("w-full gap-4"):
                start_date = ui.input(label="开始日期", value="2024-01-01").props('type="date" filled dark').classes("flex-1")
                end_date = ui.input(label="结束日期", value="2024-12-31").props('type="date" filled dark').classes("flex-1")
            
            ui.separator().classes("my-2")
            
            # ===== 按钮区 =====
            with ui.row().classes("w-full justify-end gap-2 mt-4"):
                ui.button("取消", on_click=dialog.close).props("flat")
                
                async def _on_confirm():
                    dialog.close()
                    # 默认向下兼容传递 base_interval=15m 给回测引擎，供高阶重采样使用
                    await run_strategy_backtest_advanced(
                        strategy_name=strategy_select.value,
                        symbols=list(symbols_input.value) if symbols_input.value else ["BTCUSDT"],
                        capital=capital_input.value,
                        commission=commission_input.value,
                        start_date=start_date.value,
                        end_date=end_date.value,
                        interval="15m"
                    )
                
                ui.button("开始回测", color="green", icon="play_arrow", on_click=_on_confirm)

    dialog.open()

# 全局存储回测结果（用于跨页面传递）
_backtest_result = {"metrics": {}, "trades": [], "market_data": {}}


def show_backtest_report(metrics, trades, market_data):
    """显示回测报告对话框 - 使用全屏覆盖方式"""
    global _backtest_result
    _backtest_result = {"metrics": metrics, "trades": trades, "market_data": market_data}
    
    # 准备图表数据
    chart_options = None
    if market_data:
        symbol = list(market_data.keys())[0]
        klines = market_data[symbol]
        dates = [k["time"] for k in klines]
        values = [[k["open"], k["close"], k["low"], k["high"]] for k in klines]
        
        mark_points = []
        for t in trades:
            if t["symbol"] == symbol:
                color = "#ef4444" if t["side"] == "sell" else "#22c55e"
                mark_points.append({
                    "name": t["side"],
                    "coord": [t["timestamp"], t["price"]],
                    "value": t["side"].upper(),
                    "itemStyle": {"color": color},
                    "label": {"show": False},
                    "tooltip": {"formatter": f"{t['side']} @ {t['price']}<br>{t.get('reason','')}"}
                })

        chart_options = {
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
            "grid": {"left": "5%", "right": "5%", "bottom": "15%"},
            "xAxis": {
                "type": "category", "data": dates, "scale": True, "boundaryGap": False,
                "axisLine": {"onZero": False}, "splitLine": {"show": False},
                "min": "dataMin", "max": "dataMax"
            },
            "yAxis": {"scale": True, "splitArea": {"show": True}},
            "dataZoom": [{"type": "inside", "start": 0, "end": 100}, {"show": True, "type": "slider", "top": "90%"}],
            "series": [{
                "name": symbol, "type": "candlestick", "data": values,
                "itemStyle": {"color": "#22c55e", "color0": "#ef4444", "borderColor": "#22c55e", "borderColor0": "#ef4444"},
                "markPoint": {"data": mark_points, "symbolSize": 20}
            }]
        }

    # 创建全屏覆盖层
    overlay = ui.element('div').classes('fixed inset-0 z-50 bg-gray-900 overflow-auto')
    with overlay:
        with ui.column().classes("w-full h-full p-6"):
            # 顶部栏
            with ui.row().classes("w-full justify-between items-center mb-4"):
                ui.label("回测详细报告").classes("text-2xl font-bold text-white")
                ui.button("关闭报告", icon="close", on_click=lambda: overlay.delete()).props("flat color=white")
            
            with ui.row().classes("w-full flex-1 gap-4") as main_content:
                # 左侧：K线图表
                with ui.column().classes("w-3/4 bg-gray-800 rounded p-4"):
                    if chart_options:
                        ui.echart(options=chart_options).classes("w-full").style("height: 500px")
                    else:
                        ui.label("无图表数据").classes("text-gray-400")
                
                # 右侧：指标和交易列表
                with ui.column().classes("flex-1 gap-4"):
                    # 指标卡片
                    with ui.card().classes("w-full bg-gray-800 p-4"):
                        ui.label("绩效指标").classes("text-lg font-bold text-white mb-2")
                        with ui.grid(columns=2).classes("w-full gap-2"):
                            def _metric_card(label, value, color="white"):
                                with ui.column().classes("bg-gray-700 p-2 rounded"):
                                    ui.label(label).classes("text-xs text-gray-400")
                                    ui.label(str(value)).classes(f"text-md font-bold text-{color}")
                            
                            pnl = metrics.get('total_return', 0)
                            pnl_color = "green-400" if not str(pnl).startswith("-") else "red-400"
                            _metric_card("总收益率", f"{metrics.get('total_return', '0%')}", pnl_color)
                            _metric_card("夏普比率", f"{metrics.get('sharpe_ratio', '0.00')}")
                            _metric_card("最大回撤", f"{metrics.get('max_drawdown', '0%')}", "red-400")
                            _metric_card("胜率", f"{metrics.get('win_rate', '0%')}")
                            _metric_card("总交易数", f"{metrics.get('total_trades', 0)}")
                    
                    # 交易记录列表
                    with ui.card().classes("w-full bg-gray-800 p-4 max-h-96 overflow-auto"):
                        ui.label("最近交易").classes("text-lg font-bold text-white mb-2")
                        if trades:
                            with ui.column().classes("w-full gap-2"):
                                for t in reversed(trades[-20:]): 
                                    color = "green" if t["side"] == "buy" else "red"
                                    with ui.row().classes("w-full justify-between text-xs"):
                                        ui.label(t["timestamp"]).classes("text-gray-400")
                                        ui.label(t["side"].upper()).classes(f"text-{color}-400 font-bold")
                                        ui.label(f"${t['price']:.2f}").classes("text-white")
                        else:
                            ui.label("无交易记录").classes("text-gray-500")


# ===== 事件处理 =====

async def start_single_strategy(name: str):
    """启动单个策略"""
    ui.notify(f"正在启动策略 {name}...", type="info")
    result = await engine_api.start_strategy(name)
    if result["success"]:
        ui.notify(result["message"], type="positive")
        # 刷新页面
        ui.navigate.to("/strategies")
    else:
        ui.notify(result["message"], type="negative")


async def stop_single_strategy(name: str):
    """停止单个策略"""
    ui.notify(f"正在停止策略 {name}...", type="info")
    result = await engine_api.stop_strategy()
    if result["success"]:
        ui.notify(result["message"], type="positive")
        ui.navigate.to("/strategies")
    else:
        ui.notify(result["message"], type="negative")


def refresh_strategies():
    """刷新策略列表"""
    ui.notify("正在刷新策略列表...", type="info")
    strategy_api.discover()
    ui.notify("策略列表已刷新", type="positive")
    ui.navigate.to("/strategies")


def save_parameters(fast: int, slow: int, ma_type: str):
    """保存策略参数"""
    params = {
        "fast_period": int(fast),
        "slow_period": int(slow),
        "ma_type": ma_type
    }
    strategy_api.update_strategy_parameters("ma_cross", params)
    ui.notify(f"参数已保存: {params}", type="positive")


def reset_parameters(fast_slider, slow_slider, ma_type):
    """重置参数为默认值"""
    fast_slider.value = 5
    slow_slider.value = 20
    ma_type.value = "EMA"
    ui.notify("参数已重置为默认值", type="info")


async def run_strategy_backtest_advanced(
    strategy_name: str,
    symbols: list,
    capital: float, 
    commission: float, 
    start_date: str, 
    end_date: str, 
    interval: str,
    **strategy_params
):
    """运行高级回测 - 支持任意策略"""
    ui.notify(f"正在初始化回测环境 [{strategy_name}]...", type="info")
    
    # 回测配置参数
    backtest_params = {
        "initial_capital": float(capital),
        "commission_rate": float(commission) / 100,  # 转换为小数
        "start_date": start_date,
        "end_date": end_date,
        "interval": interval
    }
    
    ui.notify(f"策略: {strategy_name} | 标的: {', '.join(symbols)} | 区间: {start_date} → {end_date}", type="info")
    
    try:
        result = await engine_api.run_backtest(
            strategy_name,  # 动态策略名
            symbols=symbols if symbols else ["BTCUSDT"],
            **strategy_params,  # 策略特定参数
            **backtest_params
        )
        
        if result["success"]:
            ui.notify("回测成功，正在跳转到报告页面...", type="positive")
            metrics = result.get("result", {}).get("metrics", {})
            trades = result.get("result", {}).get("trades", [])
            market_data = result.get("result", {}).get("market_data", {})
            
            ui.notify(f"共 {len(trades)} 笔交易", type="info")

            # 存储结果并跳转到报告页面
            from src.web.pages import backtest_report
            backtest_report.set_result({
                "metrics": metrics,
                "trades": trades,
                "market_data": market_data
            })
            ui.navigate.to("/backtest-report")
            
        else:
            ui.notify(f"回测失败: {result['message']}", type="negative")
            
    except Exception as e:
        ui.notify(f"系统错误: {e}", type="negative")
