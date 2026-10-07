"""Offline UI using the actual plugin loader, runner and report component."""
from nicegui import ui
from src.demo import run_demo
from src.strategy import StrategyLoader
from src.web.pages import backtest_report

def main(port=8888, show=True):
    @ui.page("/")
    def index():
        with ui.column().classes("w-full max-w-5xl mx-auto p-8"):
            ui.label("KlineDock").classes("text-3xl font-bold")
            ui.label("Offline strategy and backtest workbench · synthetic OHLCV data")
            ui.label("Plugin discovery → parameter configuration → backtest → report")
            rows=[{"name":s.name,"version":s.version,"description":s.description} for s in StrategyLoader().discover_strategies()]
            ui.table(columns=[{"name":k,"label":k.title(),"field":k} for k in ["name","version","description"]],rows=rows,row_key="name").classes("w-full")
            fast=ui.number("Fast period",value=5,min=1,max=50)
            slow=ui.number("Slow period",value=12,min=2,max=100)
            status=ui.label("Ready. No account, API key or exchange connection required.")
            async def execute():
                button.disable()
                status.set_text("Running local backtest...")
                try:
                    result=await run_demo(int(fast.value),int(slow.value))
                    backtest_report.set_result(result.to_dict())
                    ui.navigate.to("/report")
                except Exception as exc:
                    status.set_text(str(exc))
                finally:
                    button.enable()
            button=ui.button("Run synthetic backtest",on_click=execute)
    @ui.page("/report")
    def report():
        ui.link("Back to KlineDock","/")
        backtest_report.render()
    ui.run(title="KlineDock",host="127.0.0.1",port=port,reload=False,show=show,dark=True)
