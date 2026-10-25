import unittest
from unittest.mock import patch

import pandas as pd


class _FakeMarketDB:
    def get_market_dates(self):
        return [f"2026040{i}" for i in range(1, 9)]

    def read_market_sheet(self, trade_date):
        if len(trade_date) == 4:
            trade_date = "2026" + trade_date
        counts = {
            "20260401": 59,
            "20260402": 60,
            "20260403": 60,
            "20260404": 60,
            "20260405": 60,
            "20260406": 60,
            "20260407": 60,
        }
        count = counts.get(trade_date, 0)
        return pd.DataFrame({
            "准确率": [0.61] * count + [0.60, 0.90],
            "今日指标": [1.01] * count + [1.50, 1.00],
        })


class TestDailyIndexStrategyHistory(unittest.TestCase):
    def test_prior_day_signals_open_close_proxy_and_six_times_leverage(self):
        from quant_web import data_service as ds

        dates = [f"2026040{i}" for i in range(1, 8)]
        opens = [100, 100, 100, 100, 100, 100, 100]
        closes = [100, 101, 98, 101, 99, 100.5, 100]
        index_rows = [
            {"date": d, "open": o, "close": c}
            for d, o, c in zip(dates, opens, closes)
        ]
        index_rows.append({"date": "20260408", "open": 0, "close": 100})
        accuracy = {
            "20260401": 60.0,
            "20260402": 45.0,
            "20260403": 45.01,
            "20260404": 78.0,
            "20260405": 78.01,
            # 20260406 intentionally missing: at least 60 stocks => flat.
        }
        with patch.object(ds, "market_db", _FakeMarketDB()), \
             patch.object(ds, "_read_index_cache_rows", return_value=index_rows), \
             patch.object(ds, "_read_previous_prediction_accuracy", return_value=accuracy):
            rows = ds.get_daily_index_strategy_history()

        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[0]["signal_date_raw"], "20260401")
        self.assertEqual(rows[0]["gt1_count"], 59)
        self.assertEqual(rows[0]["position"], "做空50%")
        self.assertAlmostEqual(rows[0]["strategy_return"], -3.0)
        self.assertEqual(rows[1]["position"], "做空50%")  # exactly 45% is short
        self.assertAlmostEqual(rows[1]["strategy_return"], 6.0)
        self.assertEqual(rows[2]["position"], "做多50%")
        self.assertAlmostEqual(rows[2]["strategy_return"], 3.0)
        self.assertEqual(rows[3]["position"], "做多50%")  # exactly 78% remains long
        self.assertAlmostEqual(rows[3]["strategy_return"], -3.0)
        self.assertEqual(rows[4]["position"], "做空50%")
        self.assertAlmostEqual(rows[4]["strategy_return"], -1.5)
        self.assertEqual(rows[5]["position"], "空仓（缺少前日准确率）")
        self.assertAlmostEqual(rows[5]["strategy_return"], 0.0)
        self.assertEqual(rows[5]["nav"], rows[4]["nav"])
        self.assertIsNone(rows[6]["index_return"])
        self.assertIsNone(rows[6]["strategy_return"])
        self.assertIsNone(rows[6]["nav"])
        self.assertIsNone(rows[6]["drawdown"])

    def test_boundary_rules(self):
        from quant_web.data_service import _daily_index_position

        self.assertEqual(_daily_index_position(59, None), (-1, "做空50%"))
        self.assertEqual(_daily_index_position(60, 45.0), (-1, "做空50%"))
        self.assertEqual(_daily_index_position(60, 45.01), (1, "做多50%"))
        self.assertEqual(_daily_index_position(60, 78.0), (1, "做多50%"))
        self.assertEqual(_daily_index_position(60, 78.01), (-1, "做空50%"))
        self.assertEqual(_daily_index_position(60, None), (0, "空仓（缺少前日准确率）"))


if __name__ == "__main__":
    unittest.main()
