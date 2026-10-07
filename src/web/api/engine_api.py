"""
KlineDock - 引擎API

封装模拟盘引擎和策略运行器操作
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger

from src.engine.paper_engine import PaperEngine, paper_engine, EngineState
from src.strategy import StrategyLoader, strategy_loader, BaseStrategy
from src.strategy.strategy_runner import StrategyRunner, RunnerConfig, BacktestResult
from src.data.binance_fetcher import BinanceFetcher
from src.web.api.state_manager import app_state, StrategyState, PositionState, TradeRecord


class EngineAPI:
    """
    引擎控制API
    
    功能:
    - 启动/停止策略
    - 运行回测
    - 查询账户和持仓
    """
    
    def __init__(self):
        self._engine = paper_engine
        self._loader = strategy_loader
        self._current_strategy: Optional[BaseStrategy] = None
        self._runner: Optional[StrategyRunner] = None
        self._data_task: Optional[asyncio.Task] = None
        self._fetcher: Optional[BinanceFetcher] = None
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._engine.is_running
    
    async def start_strategy(
        self,
        strategy_name: str,
        symbols: List[str] = None,
        **parameters
    ) -> Dict[str, Any]:
        """
        启动策略
        
        Args:
            strategy_name: 策略名称
            symbols: 交易对列表
            **parameters: 策略参数
            
        Returns:
            Dict: 启动结果
        """
        if self._engine.is_running:
            return {"success": False, "message": "已有策略在运行中"}
        
        symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        
        try:
            # 加载策略
            strategy = self._loader.load_strategy(strategy_name, **parameters)
            if not strategy:
                return {"success": False, "message": f"无法加载策略: {strategy_name}"}
            
            self._current_strategy = strategy
            
            # 启动引擎
            await self._engine.start(strategy, symbols)
            
            # 更新状态
            app_state.update_strategy_status(strategy_name, "running")
            app_state.system_status = "running"
            
            # 启动数据推送任务
            self._start_data_feed(symbols)
            
            logger.info(f"策略已启动: {strategy_name}")
            return {
                "success": True,
                "message": f"策略 {strategy_name} 已启动",
                "strategy": strategy_name,
                "symbols": symbols
            }
            
        except Exception as e:
            logger.error(f"启动策略失败: {e}")
            return {"success": False, "message": str(e)}
    
    async def stop_strategy(self) -> Dict[str, Any]:
        """停止当前运行的策略"""
        if not self._engine.is_running:
            return {"success": False, "message": "没有运行中的策略"}
        
        try:
            # 停止数据推送
            self._stop_data_feed()
            
            # 停止引擎
            await self._engine.stop()
            
            # 更新状态
            if self._current_strategy:
                app_state.update_strategy_status(
                    self._current_strategy.name,
                    "stopped",
                    trades_count=len(self._engine.get_trade_history()),
                    pnl=self._engine.account.total_pnl
                )
            
            app_state.system_status = "idle"
            self._current_strategy = None
            
            logger.info("策略已停止")
            return {"success": True, "message": "策略已停止"}
            
        except Exception as e:
            logger.error(f"停止策略失败: {e}")
            return {"success": False, "message": str(e)}
    
    async def run_backtest(
        self,
        strategy_name: str,
        symbols: List[str] = None,
        start_date: str = None,
        end_date: str = None,
        initial_capital: float = 100000.0,
        commission_rate: float = 0.001,
        interval: str = "1h",
        **parameters
    ) -> Dict[str, Any]:
        """
        运行高级回测
        
        Args:
            strategy_name: 策略名称
            symbols: 交易对
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            initial_capital: 初始资金
            commission_rate: 手续费率
            interval: K线周期
            **parameters: 策略参数
        """
        symbols = symbols or ["BTCUSDT"]
        
        try:
            # 解析日期
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()
            # 默认回测30天
            start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else (end_dt - timedelta(days=30))
            
            # 加载策略
            strategy = self._loader.load_strategy(
                strategy_name,
                force_reload=True,
                **parameters
            )
            if not strategy:
                return {"success": False, "message": f"无法加载策略: {strategy_name}"}
            
            # 获取历史数据
            fetcher = BinanceFetcher()
            data = {}
            
            logger.info(f"获取回测数据: {symbols} {start_date} -> {end_date} ({interval})")
            
            for symbol in symbols:
                df = await fetcher.fetch_klines(
                    symbol=symbol,
                    interval=interval,
                    start_time=start_dt,
                    end_time=end_dt
                )
                if not df.empty:
                    data[symbol] = df
                else:
                    logger.warning(f"{symbol} 未获取到数据")
            
            await fetcher.close()
            
            if not data:
                return {"success": False, "message": "无法获取历史数据，请检查日期范围或网络"}
            
            # 创建运行器并配置
            config = RunnerConfig(
                backtest_mode=True,
                symbols=symbols,
                initial_capital=initial_capital,
                commission_rate=commission_rate
            )
            
            runner = StrategyRunner(strategy, config)
            
            # 执行回测
            result = await runner.backtest(data, start_dt, end_dt)
            
            logger.info(f"回测完成: {result.to_dict()}")
            
            return {
                "success": True,
                "message": "回测完成",
                "result": result.to_dict()
            }
            
        except Exception as e:
            logger.error(f"回测失败: {e}")
            return {"success": False, "message": str(e)}
    
    def _start_data_feed(self, symbols: List[str]) -> None:
        """启动数据推送"""
        async def data_loop():
            fetcher = BinanceFetcher()
            self._fetcher = fetcher
            
            try:
                while self._engine.is_running:
                    for symbol in symbols:
                        # 获取最新K线
                        df = await fetcher.fetch_klines(
                            symbol=symbol,
                            interval="1m",
                            days_back=1,
                            limit=5
                        )
                        
                        if not df.empty:
                            # 推送最新K线到引擎
                            latest_bar = df.iloc[-1]
                            await self._engine.on_bar(symbol, latest_bar)
                            
                            # 更新价格
                            price = float(latest_bar["close"])
                            app_state.update_price(symbol, price)
                    
                    # 同步账户状态
                    self._sync_account_state()
                    
                    await asyncio.sleep(60)  # 每分钟更新一次
                    
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"数据推送异常: {e}")
            finally:
                await fetcher.close()
        
        self._data_task = asyncio.create_task(data_loop())
    
    def _stop_data_feed(self) -> None:
        """停止数据推送"""
        if self._data_task and not self._data_task.done():
            self._data_task.cancel()
            self._data_task = None
    
    def _sync_account_state(self) -> None:
        """同步账户状态到全局状态"""
        account = self._engine.account
        
        # 更新账户
        app_state.update_account(
            balance=account.balance,
            equity=account.equity,
            unrealized_pnl=account.unrealized_pnl
        )
        
        # 更新持仓
        positions = []
        for symbol, pos in account.positions.items():
            positions.append(PositionState(
                symbol=symbol,
                quantity=pos.quantity,
                avg_price=pos.avg_price,
                current_price=pos.current_price,
                pnl=pos.unrealized_pnl,
                pnl_percent=(pos.current_price - pos.avg_price) / pos.avg_price * 100
                if pos.avg_price > 0 else 0
            ))
        app_state.update_positions(positions)
        
        # 更新交易记录
        for order in account.filled_orders[-10:]:
            trade = TradeRecord(
                time=order.timestamp.strftime("%H:%M:%S") if order.timestamp else "",
                symbol=order.symbol,
                side=order.side.upper(),
                quantity=order.quantity,
                price=order.price
            )
            if trade not in [t.__dict__ for t in app_state.trades[:10]]:
                app_state.add_trade(trade)
    
    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        return self._engine.get_summary()
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """获取持仓列表"""
        positions = []
        for symbol, pos in self._engine.get_virtual_positions().items():
            positions.append({
                "symbol": symbol,
                "quantity": f"{pos.quantity:.4f}",
                "avg_price": f"${pos.avg_price:,.2f}",
                "current_price": f"${pos.current_price:,.2f}",
                "pnl": f"{'+' if pos.unrealized_pnl >= 0 else ''}{pos.unrealized_pnl:.2f} "
                       f"({'+' if pos.unrealized_pnl >= 0 else ''}"
                       f"{(pos.current_price - pos.avg_price) / pos.avg_price * 100:.2f}%)"
            })
        return positions
    
    def get_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近交易"""
        trades = []
        for order in self._engine.get_trade_history()[-limit:]:
            trades.append({
                "time": order.timestamp.strftime("%H:%M:%S") if order.timestamp else "",
                "symbol": order.symbol,
                "side": order.side.upper(),
                "quantity": f"{order.quantity:.4f}",
                "price": f"${order.price:,.2f}"
            })
        return trades[::-1]  # 最新在前
    
    def reset(self) -> None:
        """重置引擎"""
        self._stop_data_feed()
        self._engine.reset()
        app_state.reset()


# 全局引擎API实例
engine_api = EngineAPI()
