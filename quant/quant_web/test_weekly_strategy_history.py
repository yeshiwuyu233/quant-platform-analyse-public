import unittest


class TestWeeklyStrategyHistory(unittest.TestCase):
    def test_build_weekly_strategy_history_applies_filter_and_drawdown(self):
        from quant_web.data_service import _build_weekly_strategy_history

        top_up = {
            "代码": "000001.SZ",
            "全称": "A",
            "T+1回报": "+10.00%",
            "T+2回报": "+10.00%",
            "T+3回报": "+10.00%",
            "T+4回报": "+10.00%",
            "T+5回报": "+10.00%",
        }
        top_down = {
            "代码": "000002.SZ",
            "全称": "B",
            "T+1回报": "-10.00%",
            "T+2回报": "-10.00%",
            "T+3回报": "-10.00%",
            "T+4回报": "-10.00%",
            "T+5回报": "-10.00%",
        }
        standard_up = dict(top_up, **{
            "T+1回报": "+5.00%", "T+2回报": "+5.00%", "T+3回报": "+5.00%",
            "T+4回报": "+5.00%", "T+5回报": "+5.00%",
        })
        standard_down = dict(top_down, **{
            "T+1回报": "-5.00%", "T+2回报": "-5.00%", "T+3回报": "-5.00%",
            "T+4回报": "-5.00%", "T+5回报": "-5.00%",
        })
        cold_up = dict(top_up, **{
            "T+1回报": "+2.00%", "T+2回报": "+2.00%", "T+3回报": "+2.00%",
            "T+4回报": "+2.00%", "T+5回报": "+2.00%",
        })
        cold_down = dict(top_down, **{
            "T+1回报": "-2.00%", "T+2回报": "-2.00%", "T+3回报": "-2.00%",
            "T+4回报": "-2.00%", "T+5回报": "-2.00%",
        })

        reports = [
            ("0401", {
                "meta": {"n_available": 5},
                "standard": {"summary": [
                    {"策略分组": "指标大于1.0", "入选股票数": 80, "平均持仓回报": "1.00%"},
                ], "sheets": {"指标大于1.0": {"rows": [standard_up]}}},
                "top_industries": {"summary": [
                    {"策略分组": "机械设备", "入选股票数": 6, "有效收益股票数": 6, "平均持仓回报": "2.00%"},
                    {"策略分组": "汽车", "入选股票数": 4, "有效收益股票数": 4, "平均持仓回报": "-1.00%"},
                ], "sheets": {"机械设备": {"rows": [top_up]}}},
                "cold_industry": {"summary": [
                    {"策略分组": "食品饮料", "入选股票数": 2, "有效收益股票数": 2, "平均持仓回报": "3.00%"},
                ], "sheets": {"食品饮料": {"rows": [cold_up]}}},
            }),
            ("0402", {
                "meta": {"n_available": 5},
                "standard": {"summary": [
                    {"策略分组": "指标大于1.0", "入选股票数": 50, "平均持仓回报": "-2.00%"},
                ], "sheets": {"指标大于1.0": {"rows": [standard_down]}}},
                "top_industries": {"summary": [
                    {"策略分组": "电子", "入选股票数": 5, "有效收益股票数": 5, "平均持仓回报": "-10.00%"},
                ], "sheets": {"电子": {"rows": [top_down]}}},
                "cold_industry": {"summary": [
                    {"策略分组": "传媒", "入选股票数": 1, "有效收益股票数": 1, "平均持仓回报": "-5.00%"},
                ], "sheets": {"传媒": {"rows": [cold_down]}}},
            }),
        ]

        index_rows = [
            {"date": "20260401", "close": 100.0},
            {"date": "20260402", "close": 110.0},
            {"date": "20260403", "close": 121.0},
            {"date": "20260404", "close": 133.1},
            {"date": "20260405", "close": 146.41},
            {"date": "20260406", "close": 161.051},
            {"date": "20260407", "close": 144.9459},
        ]
        date_sequence = ["0401", "0402", "0403", "0404", "0405", "0406", "0407"]

        rows = _build_weekly_strategy_history(
            reports,
            min_gt1_count=60,
            index_rows=index_rows,
            date_sequence=date_sequence,
            accuracy_by_date={"0401": 60.0, "0402": 30.0},
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]['exit_date_raw'], rows[0]['exit_date']), ('0406', '04/06'))
        self.assertEqual((rows[1]['exit_date_raw'], rows[1]['exit_date']), ('0407', '04/07'))
        self.assertAlmostEqual(rows[0]["top_return"], 0.8)
        self.assertAlmostEqual(rows[0]["filtered_top_return"], 0.8)
        self.assertAlmostEqual(rows[0]["futures_timing_return"], 30.5255, places=4)
        self.assertAlmostEqual(rows[0]["stock_timing_return"], 0.8, places=4)
        self.assertEqual(rows[0]["futures_position"], "做多50%")
        self.assertEqual(rows[0]["stock_position"], "做多100%")
        self.assertTrue(rows[0]["passes_filter"])
        self.assertEqual((rows[0]["state_id"], rows[0]["market_state"]), (6, "上行模式"))
        self.assertEqual((rows[1]["state_id"], rows[1]["market_state"]), (3, "系统性暴跌模式"))
        self.assertAlmostEqual(rows[0]["top_nav"], 1.051946, places=6)
        self.assertAlmostEqual(rows[0]["filtered_top_nav"], 1.122102, places=6)
        self.assertAlmostEqual(rows[0]["top_drawdown"], 0.0)
        self.assertAlmostEqual(rows[0]["csi1000_return"], 61.051)
        self.assertAlmostEqual(rows[0]["csi1000_nav"], 1.216778, places=6)
        self.assertAlmostEqual(rows[0]["csi1000_drawdown"], 0.0)

        self.assertAlmostEqual(rows[1]["top_return"], -10.0)
        self.assertAlmostEqual(rows[1]["filtered_top_return"], 0.0)
        self.assertAlmostEqual(rows[1]["futures_timing_return"], -25.4152, places=4)
        self.assertAlmostEqual(rows[1]["stock_timing_return"], 0.0)
        self.assertEqual(rows[1]["futures_position"], "做空80%")
        self.assertEqual(rows[1]["stock_position"], "空仓")
        self.assertFalse(rows[1]["passes_filter"])
        self.assertAlmostEqual(rows[1]["filtered_top_nav"], 1.122102, places=6)
        self.assertGreater(rows[1]["stock_timing_nav"], 1.0)
        self.assertGreater(rows[1]["futures_timing_nav"], 1.0)
        self.assertAlmostEqual(rows[1]["top_nav"], 1.038562, places=6)
        self.assertAlmostEqual(rows[1]["top_drawdown"], -1.2723, places=4)
        self.assertAlmostEqual(rows[1]["cold_drawdown"], -0.3685, places=4)
        self.assertAlmostEqual(rows[1]["csi1000_return"], 31.769, places=4)
        # CSI1000 uses the same rolling 5-day capital schedule as the strategy:
        # a new 20% sleeve opens each signal day and each sleeve holds T+1..T+5.
        self.assertAlmostEqual(rows[1]["csi1000_nav"], 1.186911, places=6)
        self.assertAlmostEqual(rows[1]["csi1000_drawdown"], -2.4546, places=4)

    def test_build_weekly_strategy_history_falls_back_to_summary_when_sheets_missing(self):
        from quant_web.data_service import _build_weekly_strategy_history

        reports = [
            ("0401", {
                "meta": {"n_available": 5},
                "standard": {"summary": [
                    {"策略分组": "指标大于1.0", "入选股票数": 80, "平均持仓回报": "5.00%"},
                ], "sheets": {}},
                "top_industries": {"summary": [
                    {"策略分组": "机械设备", "入选股票数": 10, "有效收益股票数": 10, "平均持仓回报": "10.00%"},
                ], "sheets": {}},
                "cold_industry": {"summary": [
                    {"策略分组": "食品饮料", "入选股票数": 5, "有效收益股票数": 5, "平均持仓回报": "-5.00%"},
                ], "sheets": {}},
            }),
        ]
        index_rows = [
            {"date": "20260401", "close": 100.0},
            {"date": "20260402", "close": 100.0},
            {"date": "20260403", "close": 100.0},
            {"date": "20260404", "close": 100.0},
            {"date": "20260405", "close": 100.0},
            {"date": "20260406", "close": 100.0},
        ]
        rows = _build_weekly_strategy_history(
            reports,
            min_gt1_count=60,
            index_rows=index_rows,
            date_sequence=["0401", "0402", "0403", "0404", "0405", "0406"],
            accuracy_by_date={"0401": 78.0},
        )

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["top_return"], 10.0)
        self.assertAlmostEqual(rows[0]["top_nav"], 1.02)
        self.assertAlmostEqual(rows[0]["standard_nav"], 1.01)
        self.assertAlmostEqual(rows[0]["cold_nav"], 0.99)
        self.assertAlmostEqual(rows[0]["stock_timing_return"], 10.0)
        self.assertEqual(rows[0]["futures_position"], "做多50%")

    def test_all_states_apply_eighty_or_fifty_percent_inside_twenty_percent_sleeve(self):
        from quant_web.data_service import _build_weekly_strategy_history

        dates = [f"040{i}" for i in range(1, 7)]
        index = [{"date": "2026" + d, "close": 100 if i == 0 else 110} for i, d in enumerate(dates)]
        for count, probability, state, expected_return, expected_nav in (
            (10, 12, 1, 8.0, 1.016), (10, 79, 2, -8.0, 0.984),
            (10, 60, 3, -8.0, 0.984), (80, 30, 4, -5.0, 0.990),
            (80, 50, 5, 5.0, 1.010), (80, 60, 6, 5.0, 1.010),
        ):
            report = {"meta": {"n_available": 5}, "standard": {"summary": [
                {"策略分组": "指标大于1.0", "入选股票数": count, "平均持仓回报": "10.0%"}]}}
            with self.subTest(state=state):
                row = _build_weekly_strategy_history(
                    [(dates[0], report)], index_rows=index, date_sequence=dates,
                    accuracy_by_date={dates[0]: probability},
                )[0]
                self.assertEqual(row["state_id"], state)
                self.assertEqual(row["futures_timing_return"], expected_return)
                self.assertEqual(row["futures_timing_nav"], expected_nav)

    def test_timing_thresholds_are_independent_and_missing_accuracy_stays_cash(self):
        from quant_web.data_service import _timing_positions

        self.assertEqual(_timing_positions(59, 60.0, 60), (-0.8, False))
        self.assertEqual(_timing_positions(60, 45.0, 60), (0.5, True))
        self.assertEqual(_timing_positions(60, 45.01, 60), (0.5, True))
        self.assertEqual(_timing_positions(60, 78.0, 60), (0.5, True))
        self.assertEqual(_timing_positions(60, 78.01, 60), (-0.8, False))
        self.assertEqual(_timing_positions(60, None, 60), (0.0, False))


if __name__ == "__main__":
    unittest.main()
