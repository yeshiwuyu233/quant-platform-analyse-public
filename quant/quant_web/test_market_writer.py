import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_web import market_writer


class TestPersistMarketDataframe(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({"代码": ["000001.SZ"]})

    def test_xlsx_mode_writes_only_excel(self):
        with mock.patch.object(market_writer, "write_excel_snapshot") as write_excel:
            with mock.patch.object(market_writer, "write_snapshot") as write_csv:
                with mock.patch.object(market_writer, "compare_csv_with_excel") as compare:
                    result = market_writer.persist_market_dataframe(
                        "20260714", self.df, mode="xlsx"
                    )

        write_excel.assert_called_once_with(self.df, market_writer.MASTER_FILE, "0714")
        write_csv.assert_not_called()
        compare.assert_not_called()
        self.assertEqual(
            result,
            {"mode": "xlsx", "full_date": "20260714", "legacy_date": "0714"},
        )

    def test_shadow_mode_writes_excel_then_csv_and_compares(self):
        calls = []

        def record_excel(*_args):
            calls.append("excel")

        def record_csv(*_args):
            calls.append("csv")
            return SimpleNamespace(rows=1)

        def record_compare(*_args):
            calls.append("compare")

        with mock.patch.object(market_writer, "write_excel_snapshot", side_effect=record_excel):
            with mock.patch.object(market_writer, "write_snapshot", side_effect=record_csv):
                with mock.patch.object(
                    market_writer, "compare_csv_with_excel", side_effect=record_compare
                ):
                    result = market_writer.persist_market_dataframe(
                        "20260714", self.df, mode="shadow"
                    )

        self.assertEqual(calls, ["excel", "csv", "compare"])
        self.assertEqual(result["csv_rows"], 1)
        self.assertTrue(result["shadow_ok"])

    def test_shadow_mode_reports_csv_failure_without_raising(self):
        with mock.patch.object(market_writer, "write_excel_snapshot") as write_excel:
            with mock.patch.object(
                market_writer, "write_snapshot", side_effect=RuntimeError("csv failed")
            ):
                with mock.patch.object(market_writer, "compare_csv_with_excel") as compare:
                    result = market_writer.persist_market_dataframe(
                        "20260714", self.df, mode="shadow"
                    )

        write_excel.assert_called_once()
        compare.assert_not_called()
        self.assertFalse(result["shadow_ok"])
        self.assertEqual(result["shadow_error"], "csv failed")

    def test_csv_mode_writes_only_csv(self):
        with mock.patch.object(market_writer, "write_excel_snapshot") as write_excel:
            with mock.patch.object(
                market_writer,
                "write_snapshot",
                return_value=SimpleNamespace(rows=1),
            ) as write_csv:
                with mock.patch.object(market_writer, "compare_csv_with_excel") as compare:
                    result = market_writer.persist_market_dataframe(
                        "20260714", self.df, mode="csv"
                    )

        write_excel.assert_not_called()
        write_csv.assert_called_once_with("20260714", self.df)
        compare.assert_not_called()
        self.assertEqual(result["csv_rows"], 1)

    def test_csv_mode_propagates_write_failure(self):
        with mock.patch.object(market_writer, "write_excel_snapshot") as write_excel:
            with mock.patch.object(
                market_writer, "write_snapshot", side_effect=RuntimeError("csv failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "csv failed"):
                    market_writer.persist_market_dataframe("20260714", self.df, mode="csv")

        write_excel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
