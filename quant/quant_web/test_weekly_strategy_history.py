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
        )

        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["top_return"], 0.8)
        self.assertAlmostEqual(rows[0]["filtered_top_return"], 0.8)
        self.assertAlmostEqual(rows[0]["long_short_top_return"], 12.8502, places=4)
        self.assertTrue(rows[0]["passes_filter"])
        self.assertAlmostEqual(rows[0]["top_nav"], 1.051946, places=6)
        self.assertAlmostEqual(rows[0]["filtered_top_nav"], 1.122102, places=6)
        self.assertAlmostEqual(rows[0]["top_drawdown"], 0.0)
        self.assertAlmostEqual(rows[0]["csi1000_return"], 61.051)
        self.assertAlmostEqual(rows[0]["csi1000_nav"], 1.216778, places=6)
        self.assertAlmostEqual(rows[0]["csi1000_drawdown"], 0.0)

        self.assertAlmostEqual(rows[1]["top_return"], -10.0)
        self.assertAlmostEqual(rows[1]["filtered_top_return"], 0.0)
        self.assertAlmostEqual(rows[1]["long_short_top_return"], -31.769, places=4)
        self.assertFalse(rows[1]["passes_filter"])
        self.assertAlmostEqual(rows[1]["filtered_top_nav"], 1.122102, places=6)
        self.assertAlmostEqual(rows[1]["long_short_top_nav"], 1.057293, places=6)
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
        )

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["top_return"], 10.0)
        self.assertAlmostEqual(rows[0]["top_nav"], 1.02)
        self.assertAlmostEqual(rows[0]["standard_nav"], 1.01)
        self.assertAlmostEqual(rows[0]["cold_nav"], 0.99)


if __name__ == "__main__":
    unittest.main()
