"""
KlineDock - 回测运行器

本地回测和LEAN Docker回测编排
"""

import asyncio
import json
import subprocess
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd
from loguru import logger

from src.core.config import get_config
from src.strategy import BaseStrategy, StrategyRunner, RunnerConfig, BacktestResult


@dataclass
class BacktestConfig:
    """回测配置"""
    # 时间范围
    start_date: datetime
    end_date: datetime
    
    # 标的
    symbols: List[str]
    
    # 资金
    initial_capital: float = 100000.0
    
    # 数据
    resolution: str = "minute"  # minute/hour/daily
    
    # 手续费
    commission_rate: float = 0.001  # 0.1%
    slippage_rate: float = 0.0005   # 0.05%
    
    # LEAN配置
    use_lean: bool = False
    lean_image: str = "quantconnect/lean:latest"


class BacktestRunner:
    """
    回测运行器
    
    功能:
    - 本地快速回测
    - LEAN Docker集成回测
    - 结果解析和绩效计算
    """
    
    def __init__(self):
        self.config = get_config()
        self.data_dir = self.config.data_dir
        self.results_dir = self.data_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    async def run_local(
        self,
        strategy: BaseStrategy,
        data: Dict[str, Any],
        config: Optional[BacktestConfig] = None
    ) -> BacktestResult:
        """
        运行本地回测
        
        Args:
            strategy: 策略实例
            data: 历史数据: {symbol: DataFrame} 或是 {symbol: {interval: DataFrame}}
            config: 回测配置
            
        Returns:
            BacktestResult: 回测结果
        """
        logger.info(f"开始本地回测: {strategy.name}")
        
        # 创建运行器配置
        runner_config = RunnerConfig(
            backtest_mode=True,
            paper_mode=False,
            symbols=list(data.keys()),
            initial_capital=config.initial_capital if config else 100000.0
        )
        
        # 创建运行器
        runner = StrategyRunner(strategy, runner_config)
        
        # 执行回测
        result = await runner.backtest(
            data=data,
            start=config.start_date if config else None,
            end=config.end_date if config else None
        )
        
        # 保存结果
        self._save_result(result)
        
        return result
    
    def _save_result(self, result: BacktestResult) -> Path:
        """保存回测结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{result.strategy_name}_{timestamp}.json"
        filepath = self.results_dir / filename
        
        # 转换为可序列化格式
        data = {
            "strategy_name": result.strategy_name,
            "metrics": {
                "total_return": result.metrics.total_return,
                "sharpe_ratio": result.metrics.sharpe_ratio,
                "max_drawdown": result.metrics.max_drawdown,
                "win_rate": result.metrics.win_rate,
                "total_trades": result.metrics.total_trades
            },
            "period": {
                "start": result.start_time.isoformat() if result.start_time else None,
                "end": result.end_time.isoformat() if result.end_time else None
            },
            "trades": result.trades,
            "timestamp": datetime.now().isoformat()
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(f"回测结果已保存: {filepath}")
        return filepath
    
    def list_results(self) -> List[Dict[str, Any]]:
        """列出所有回测结果"""
        results = []
        for file in self.results_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data["file"] = str(file)
                    results.append(data)
            except Exception as e:
                logger.error(f"读取结果失败 {file}: {e}")
        
        return sorted(results, key=lambda x: x.get("timestamp", ""), reverse=True)


class LEANOrchestrator:
    """
    LEAN Docker编排器
    
    功能:
    - 启动/停止LEAN容器
    - 配置管理
    - 回测执行
    - 结果解析
    """
    
    def __init__(self):
        self.config = get_config()
        self.lean_config_dir = self.config.project_root / "docker" / "lean"
        self.data_dir = self.config.data_dir / "lean_data"
        self.results_dir = self.config.data_dir / "results" / "lean"
        
        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # 容器状态
        self._container_id: Optional[str] = None
    
    def is_docker_available(self) -> bool:
        """检查Docker是否可用"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    async def run_backtest(
        self,
        algorithm_file: Path,
        config: BacktestConfig
    ) -> Optional[Dict[str, Any]]:
        """
        运行LEAN回测
        
        Args:
            algorithm_file: 算法文件路径
            config: 回测配置
            
        Returns:
            Dict: 回测结果
        """
        if not self.is_docker_available():
            logger.error("Docker不可用，无法运行LEAN回测")
            return None
        
        logger.info(f"启动LEAN回测: {algorithm_file.name}")
        
        # 准备配置文件
        lean_config = self._prepare_config(algorithm_file, config)
        config_path = self.lean_config_dir / "backtest_config.json"
        
        with open(config_path, "w") as f:
            json.dump(lean_config, f, indent=2)
        
        # 运行Docker命令
        try:
            cmd = [
                "docker", "run", "--rm",
                "-v", f"{self.data_dir}:/Lean/Data",
                "-v", f"{self.results_dir}:/Results",
                "-v", f"{algorithm_file.parent}:/Lean/Algorithm",
                "-v", f"{config_path}:/Lean/Launcher/config.json",
                config.lean_image,
                "--backtest"
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"LEAN回测失败: {stderr.decode()}")
                return None
            
            # 解析结果
            return self._parse_results()
            
        except Exception as e:
            logger.error(f"运行LEAN回测异常: {e}")
            return None
    
    def _prepare_config(
        self,
        algorithm_file: Path,
        config: BacktestConfig
    ) -> Dict[str, Any]:
        """准备LEAN配置"""
        return {
            "environment": "backtesting",
            "algorithm-type-name": algorithm_file.stem,
            "algorithm-language": "Python",
            "algorithm-location": f"/Lean/Algorithm/{algorithm_file.name}",
            "data-folder": "/Lean/Data",
            "results-destination-folder": "/Results",
            "log-handler": "QuantConnect.Logging.CompositeLogHandler",
            "results-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
            "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
            "period-start": config.start_date.strftime("%Y-%m-%d"),
            "period-finish": config.end_date.strftime("%Y-%m-%d"),
            "cash-amount": config.initial_capital
        }
    
    def _parse_results(self) -> Optional[Dict[str, Any]]:
        """解析LEAN回测结果"""
        # 查找最新的结果文件
        result_files = list(self.results_dir.glob("*.json"))
        if not result_files:
            logger.warning("未找到LEAN回测结果文件")
            return None
        
        latest_file = max(result_files, key=lambda f: f.stat().st_mtime)
        
        try:
            with open(latest_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"解析LEAN结果失败: {e}")
            return None
    
    async def start_container(self) -> Optional[str]:
        """启动LEAN容器（用于实时交易）"""
        if not self.is_docker_available():
            return None
        
        # 这里简化实现，实际需要更复杂的容器管理
        logger.info("LEAN容器启动功能待完善")
        return None
    
    async def stop_container(self) -> bool:
        """停止LEAN容器"""
        if not self._container_id:
            return False
        
        try:
            subprocess.run(
                ["docker", "stop", self._container_id],
                capture_output=True
            )
            self._container_id = None
            return True
        except Exception as e:
            logger.error(f"停止容器失败: {e}")
            return False


# 全局实例
backtest_runner = BacktestRunner()
lean_orchestrator = LEANOrchestrator()
