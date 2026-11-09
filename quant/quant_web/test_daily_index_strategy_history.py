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
        self.assertEqual(rows[0]["position"], "做空80%")
        self.assertAlmostEqual(rows[0]["strategy_return"], -4.8)
        self.assertEqual(rows[1]["position"], "做多50%")  # exactly 45% is oscillation
        self.assertAlmostEqual(rows[1]["strategy_return"], -6.0)
        self.assertEqual(rows[2]["position"], "做多50%")
        self.assertAlmostEqual(rows[2]["strategy_return"], 3.0)
        self.assertEqual(rows[3]["position"], "做多50%")  # exactly 78% remains long
        self.assertAlmostEqual(rows[3]["strategy_return"], -3.0)
        self.assertEqual(rows[4]["position"], "做空80%")
        self.assertAlmostEqual(rows[4]["strategy_return"], -2.4)
        self.assertEqual(rows[5]["position"], "空仓（缺少前日准确率）")
        self.assertAlmostEqual(rows[5]["strategy_return"], 0.0)
        self.assertEqual(rows[5]["nav"], rows[4]["nav"])
        self.assertIsNone(rows[6]["index_return"])
        self.assertIsNone(rows[6]["strategy_return"])
        self.assertIsNone(rows[6]["nav"])
        self.assertIsNone(rows[6]["drawdown"])
        expected_nav = 1.0
        for row, pnl, exposure in zip(rows, (-4.8, -6, 3, -3, -2.4, 0), (-4.8, 3, 3, 3, -4.8, 0)):
            expected_nav *= 1 + pnl / 100
            self.assertEqual(row["nav"], round(expected_nav, 6))
            self.assertEqual(row["effective_exposure"], exposure)


    def test_boundary_rules(self):
        from quant_web.data_service import _daily_index_position

        self.assertEqual(_daily_index_position(59, None), (-1, "做空80%"))
        self.assertEqual(_daily_index_position(60, 45.0), (1, "做多50%"))
        self.assertEqual(_daily_index_position(60, 45.01), (1, "做多50%"))
        self.assertEqual(_daily_index_position(60, 78.0), (1, "做多50%"))
        self.assertEqual(_daily_index_position(60, 78.01), (-1, "做空80%"))
        self.assertEqual(_daily_index_position(60, None), (0, "空仓（缺少前日准确率）"))

class TestLowProbabilityTiming(unittest.TestCase):
    def test_probability_ranges_and_count_priority(self):
        from quant_web import data_service as ds

        for count in (0, 59, 60, 200):
            for probability, expected in ((0.0, 1), (21.99, 1), (22.0, -1),
                                          (45.0, 1), (45.01, 1), (78.0, 1),
                                          (78.01, -1), (100.0, -1)):
                direction = expected if probability < 22 or count >= 60 else -1
                with self.subTest(count=count, probability=probability):
                    self.assertEqual(ds._daily_index_position(count, probability)[0], direction)
                    self.assertEqual(ds._timing_positions(count, probability, 60),
                                     (direction * (0.8 if probability < 22 or probability > 78 or count < 60 else 0.5), direction == 1))
        self.assertEqual(ds._daily_index_position(None, 12.85)[0], 0)

    def test_prediction_uses_previous_exchange_day_and_ignores_todays_accuracy(self):
        from quant_web import data_service as ds

        index_rows = [{"date": "20261023"}, {"date": "20261026"}]
        with patch.object(ds, "market_db", _FakeMarketDB()), \
             patch.object(ds, "_read_index_cache_rows", return_value=index_rows), \
             patch.object(ds, "_get_exchange_sessions", return_value=["20261023", "20261026"]), \
             patch.object(ds, "_count_qualified_stocks", return_value=10) as count, \
             patch.object(ds, "_read_previous_prediction_accuracy",
                          return_value={"1023": 12.85, "1026": 99.0}):
            row = ds.get_daily_index_prediction("20261026")
        self.assertEqual(row["signal_date_raw"], "20261023")
        self.assertEqual(row["date_raw"], "20261026")
        self.assertEqual(row["position"], "做多80%")
        self.assertEqual((row["state_id"], row["market_state"]), (1, "超跌反弹模式"))
        self.assertEqual(row["prediction_accuracy"], 12.85)
        self.assertNotIn("strategy_return", row)
        count.assert_called_once_with("20261023")

    def test_missing_inputs_and_unknown_today_hide_prediction(self):
        from quant_web import data_service as ds

        for today, count, accuracy in (("20261028", 179, 64.71),
                                       ("20261027", None, 64.71),
                                       ("20261027", 179, None),
                                       ("20261025", 179, 64.71)):
            with self.subTest(today=today, count=count, accuracy=accuracy), \
                 patch.object(ds, "market_db", _FakeMarketDB()), \
                 patch.object(ds, "_read_index_cache_rows", return_value=[
                     {"date": "20261026"}, {"date": "20261027"}]), \
                 patch.object(ds, "_get_exchange_sessions", return_value=["20261026", "20261027"]), \
                 patch.object(ds, "_count_qualified_stocks", return_value=count), \
                 patch.object(ds, "_read_previous_prediction_accuracy", return_value={"1026": accuracy}):
                self.assertIsNone(ds.get_daily_index_prediction(today))

    def test_low_probability_changes_next_day_pnl_and_nav(self):
        import importlib
        from quant_web import data_service
        ds = importlib.reload(data_service)
        with patch.object(ds, "market_db", _FakeMarketDB()), \
             patch.object(ds, "_read_index_cache_rows", return_value=[
                 {"date": "20260401", "open": 100, "close": 100},
                 {"date": "20260402", "open": 100, "close": 101}]), \
             patch.object(ds, "_read_previous_prediction_accuracy", return_value={"20260401": 12.85}):
            rows = ds.get_daily_index_strategy_history()
        self.assertEqual(rows[0]["position"], "做多80%")
        self.assertEqual(rows[0]["strategy_return"], 4.8)
        self.assertEqual(rows[0]["nav"], 1.048)


class TestSixMarketStates(unittest.TestCase):
    def test_ordered_six_states_and_exact_boundaries(self):
        from quant_web import data_service as ds
        for count in (0, 59, 60, 200):
            for p in (0, 21.999, 22, 44.999, 45, 45.001, 55, 55.001, 78, 78.001, 100):
                if p < 22:
                    expected_id, direction = 1, 1
                elif p > 78:
                    expected_id, direction = 2, -1
                elif count < 60:
                    expected_id, direction = 3, -1
                elif p < 45:
                    expected_id, direction = 4, -1
                elif p <= 55:
                    expected_id, direction = 5, 1
                else:
                    expected_id, direction = 6, 1
                with self.subTest(count=count, p=p):
                    signal = ds._market_timing_signal(count, p)
                    self.assertEqual(signal["state_id"], expected_id)
                    self.assertEqual(signal["direction"], direction)
                    self.assertEqual(signal["allocation"], 0.8 if expected_id <= 3 else 0.5)
                    self.assertEqual(ds._daily_index_position(count, p)[0], direction)
                    self.assertEqual(ds._timing_positions(count, p, 60), (direction * (0.8 if expected_id <= 3 else 0.5), direction > 0))

    def test_states_one_and_two_win_over_count_below_sixty(self):
        from quant_web import data_service as ds
        self.assertEqual(ds._market_timing_signal(10, 12.85)["state_id"], 1)
        self.assertEqual(ds._market_timing_signal(10, 79)["state_id"], 2)
        self.assertEqual(ds._market_timing_signal(10, 60)["state_id"], 3)
        self.assertEqual(ds._market_timing_signal(60, 30)["state_id"], 4)
        self.assertEqual(ds._market_timing_signal(60, 50)["state_id"], 5)
        self.assertEqual(ds._market_timing_signal(60, 60)["state_id"], 6)

    def test_invalid_probability_does_not_create_trade(self):
        from quant_web import data_service as ds
        for p in (float("nan"), float("inf"), -1, 101):
            self.assertEqual(ds._market_timing_signal(60, p)["direction"], 0)
            self.assertIsNone(ds._market_timing_signal(60, p)["state_id"])



if __name__ == "__main__":
    unittest.main()
