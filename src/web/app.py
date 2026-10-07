"""
KlineDock - Web UI 主应用

使用NiceGUI构建的量化交易管理界面
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nicegui import ui, app
from pathlib import Path
from datetime import datetime

# 导入页面模块
from src.web.pages import dashboard, strategies, market, settings, trading, backtest_report

# 导入API
from src.web.api import market_api


# ===== 全局样式 =====
DARK_THEME = {
    "primary": "#3B82F6",     # 蓝色
    "secondary": "#10B981",   # 绿色
    "accent": "#F59E0B",      # 橙色
    "dark": "#1F2937",        # 深灰
    "positive": "#10B981",    # 盈利绿
    "negative": "#EF4444",    # 亏损红
}


def create_header():
    """创建顶部导航栏"""
    with ui.header().classes("bg-gray-900 text-white items-center justify-between px-4"):
        # Logo和标题
        with ui.row().classes("items-center gap-2"):
            ui.icon("show_chart", size="md").classes("text-blue-400")
            ui.label("KlineDock").classes("text-xl font-bold")
        
        # 导航菜单
        with ui.row().classes("gap-1"):
            ui.button("仪表盘", icon="dashboard", on_click=lambda: ui.navigate.to("/")).props("flat")
            ui.button("交易", icon="swap_horiz", on_click=lambda: ui.navigate.to("/trading")).props("flat")
            ui.button("策略", icon="psychology", on_click=lambda: ui.navigate.to("/strategies")).props("flat")
            ui.button("行情", icon="candlestick_chart", on_click=lambda: ui.navigate.to("/market")).props("flat")
            ui.button("设置", icon="settings", on_click=lambda: ui.navigate.to("/settings")).props("flat")
        
        # 状态指示
        with ui.row().classes("items-center gap-4"):
            # WebSocket 状态
            ws_status = "🟢 实时" if market_api.is_streaming else "🔴 离线"
            ui.badge(ws_status, color="green" if market_api.is_streaming else "gray").classes("text-xs")
            ui.badge("模拟盘", color="blue").classes("text-xs")
            ui.label(datetime.now().strftime("%H:%M:%S")).classes("text-sm text-gray-400")


def create_footer():
    """创建底部状态栏"""
    with ui.footer().classes("bg-gray-800 text-gray-400 text-xs py-2 px-4"):
        with ui.row().classes("w-full justify-between"):
            ui.label("KlineDock v0.2.0")
            with ui.row().classes("gap-4"):
                ui.label("API: ✅ 已连接")
                ui.label("数据: ✅ 正常")
                ws_text = "WebSocket: ✅ 实时" if market_api.is_streaming else "WebSocket: ⚪ 轮询"
                ui.label(ws_text)


# ===== 页面路由 =====
@ui.page("/")
def index_page():
    """主页/仪表盘"""
    create_header()
    dashboard.render()
    create_footer()


@ui.page("/trading")
def trading_page():
    """交易页面"""
    create_header()
    trading.render()
    create_footer()


@ui.page("/strategies")
def strategies_page():
    """策略管理页面"""
    create_header()
    strategies.render()
    create_footer()


@ui.page("/market")
def market_page():
    """行情监控页面"""
    create_header()
    market.render()
    create_footer()


@ui.page("/settings")
def settings_page():
    """系统设置页面"""
    create_header()
    settings.render()
    create_footer()


@ui.page("/backtest-report")
def backtest_report_page():
    """回测报告页面"""
    backtest_report.render()


# ===== 应用生命周期 =====
@app.on_startup
async def on_startup():
    """应用启动时初始化"""
    print("[启动] 正在启动 WebSocket 实时行情推送...")
    try:
        await market_api.start_websocket_stream()
        print("[成功] WebSocket 已启动")
    except Exception as e:
        print(f"[警告] WebSocket 启动失败: {e}，将使用轮询模式")


@app.on_shutdown
async def on_shutdown():
    """应用关闭时清理"""
    print("[关闭] 正在关闭连接...")
    try:
        await market_api.close()
        print("[成功] 连接已关闭")
    except Exception as e:
        print(f"[警告] 关闭连接时出错: {e}")


# ===== 应用配置 =====
app.native.window_args["size"] = (1400, 900)
app.native.start_args["debug"] = False


def main():
    """启动Web应用"""
    print("\n" + "=" * 50)
    print("   KlineDock - Web UI v0.2.0")
    print("=" * 50)
    print(f"   启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   访问地址: http://localhost:8888")
    print("=" * 50)
    print("   新功能: 交易页面、WebSocket实时行情、真实订单簿")
    print("=" * 50 + "\n")
    
    ui.run(
        title="KlineDock",
        host="127.0.0.1",
        port=8888,
        reload=False,
        show=True,
        dark=True
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()

