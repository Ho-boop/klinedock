import asyncio
import json
import math
import unittest
from src.demo import run_demo, synthetic_bars
from src.strategy import StrategyLoader
from src.core.config import RiskConfig
from src.risk.position_control import PositionControl
from src.risk.base_risk import Order, RiskContext

class OfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_backtest_report_contract(self):
        result=await run_demo()
        report=result.to_dict()
        self.assertGreater(len(report["trades"]),0)
        self.assertEqual(len(report["market_data"]["DEMO"]),180)
        self.assertEqual(len(report["equity_curve"]),180)
        self.assertTrue(all(math.isfinite(p["value"]) for p in report["equity_curve"]))
        self.assertGreaterEqual(result.metrics.max_drawdown,0)
        self.assertEqual(report["period"]["start"],"2026-01-01T00:00:00")
        json.dumps(report,allow_nan=False)
    async def test_repeated_run_is_deterministic(self):
        first=await run_demo();second=await run_demo()
        self.assertEqual(first.to_dict(),second.to_dict())
    async def test_bad_parameter_order(self):
        with self.assertRaises(ValueError):
            await run_demo(12,5)
    def test_plugins_are_discoverable(self):
        self.assertIn("ma_cross",[s.name for s in StrategyLoader().discover_strategies()])
    def test_risk_rejects_large_order(self):
        risk=PositionControl(RiskConfig(max_order_value_usdt=100))
        result=risk.check_order(Order("DEMO","buy",10,100),RiskContext(balance=10000,equity=10000))
        self.assertFalse(result.passed)

if __name__=="__main__":
    unittest.main()
