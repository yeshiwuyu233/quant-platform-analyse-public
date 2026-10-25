import unittest
from unittest.mock import patch


class TestIndexService(unittest.TestCase):
    def test_history_index_trend_aligns_exact_dates_without_forward_fill(self):
        from quant_web import data_service

        records = [{"date_raw": "20260701"}, {"date_raw": "20260702"}]
        rows = {
            "sh000905": [{"date": "20260701", "close": "6000.12"}],
            "sh000852": [{"date": "20260702", "close": "7000.34"}],
        }
        with patch.object(data_service, "_read_index_cache_rows", side_effect=rows.get):
            trend = data_service.get_history_index_trend(records)

        self.assertEqual(trend["csi500"], [6000.12, None])
        self.assertEqual(trend["csi1000"], [None, 7000.34])

    def test_parse_eastmoney_klines(self):
        from quant_web.index_service import parse_eastmoney_klines

        payload = {
            "data": {
                "klines": [
                    "2026-07-01,4000.00,4010.00,4020.00,3990.00,100,200,0.75,0.25",
                    "2026-07-02,4010.00,3990.00,4030.00,3980.00,120,220,1.25,-0.50",
                ]
            }
        }

        rows = parse_eastmoney_klines(payload)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "20260701")
        self.assertEqual(rows[0]["close"], 4010.00)
        self.assertEqual(rows[1]["pct_chg"], -0.50)

    def test_window_return_uses_first_and_last_close(self):
        from quant_web.index_service import window_return

        rows = [
            {"date": "20260701", "close": 100.0},
            {"date": "20260702", "close": 103.0},
            {"date": "20260703", "close": 105.0},
        ]

        self.assertAlmostEqual(window_return(rows, "20260701", "20260703"), 0.05)

    def test_window_return_returns_none_for_missing_dates(self):
        from quant_web.index_service import window_return

        rows = [{"date": "20260701", "close": 100.0}]

        self.assertIsNone(window_return(rows, "20260701", "20260703"))

    def test_parse_tencent_klines(self):
        from quant_web.index_service import parse_tencent_klines

        payload = {
            "data": {
                "sh000001": {
                    "day": [
                        ["2026-07-01", "4000.000", "4010.000", "4020.000", "3990.000", "100"],
                        ["2026-07-02", "4010.000", "3990.000", "4030.000", "3980.000", "120"],
                    ]
                }
            }
        }

        rows = parse_tencent_klines(payload, "sh000001")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["date"], "20260701")
        self.assertEqual(rows[0]["close"], 4010.0)
        self.assertAlmostEqual(rows[1]["pct_chg"], -0.49875311720698257)


if __name__ == "__main__":
    unittest.main()
