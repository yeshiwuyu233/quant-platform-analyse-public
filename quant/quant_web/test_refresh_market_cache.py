import datetime
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


class TestRefreshMarketCache(unittest.TestCase):
    def test_csv_imports_full_date_snapshot(self):
        from quant_web import refresh_market_cache

        with patch(
            "quant_web.refresh_market_cache.import_market_csv.import_csv_snapshot",
            return_value=4123,
        ) as importer:
            rows = refresh_market_cache.refresh_market_cache("20260714", mode="csv")

        self.assertEqual(rows, 4123)
        importer.assert_called_once_with("20260714")

    def test_xlsx_and_shadow_import_legacy_sheet(self):
        from quant_web import refresh_market_cache

        for mode in ("xlsx", "shadow"):
            with self.subTest(mode=mode), patch(
                "quant_web.refresh_market_cache.import_market_xlsx.import_workbook",
                return_value=[("0714", 4100)],
            ) as importer:
                rows = refresh_market_cache.refresh_market_cache("20260714", mode=mode)

            self.assertEqual(rows, 4100)
            importer.assert_called_once_with(
                str(refresh_market_cache.PROJECT_ROOT / "Whole Market.xlsx"),
                sheet_names=["0714"],
            )

    def test_invalid_mode_raises(self):
        from quant_web import refresh_market_cache

        with self.assertRaisesRegex(ValueError, "MARKET_STORAGE_MODE"):
            refresh_market_cache.refresh_market_cache("20260714", mode="invalid")

    def test_latest_csv_uses_newest_stored_full_date(self):
        from quant_web import refresh_market_cache

        with patch.dict("os.environ", {"MARKET_STORAGE_MODE": "csv"}), patch(
            "quant_web.refresh_market_cache.market_store.list_full_dates",
            return_value=["20260711", "20260714"],
        ), patch(
            "quant_web.refresh_market_cache.refresh_market_cache", return_value=4123
        ) as refresh:
            output = io.StringIO()
            with redirect_stdout(output):
                result = refresh_market_cache.main(["--latest"])

        self.assertEqual(result, 0)
        refresh.assert_called_once_with("20260714", mode="csv")
        self.assertEqual(output.getvalue().strip(), "mode=csv date=20260714 rows=4123")

    def test_latest_xlsx_uses_today_full_date(self):
        from quant_web import refresh_market_cache

        fixed_now = datetime.datetime(2026, 7, 15, 9, 30)
        with patch.dict("os.environ", {"MARKET_STORAGE_MODE": "xlsx"}), patch(
            "quant_web.refresh_market_cache.datetime"
        ) as clock, patch(
            "quant_web.refresh_market_cache.refresh_market_cache", return_value=4100
        ) as refresh:
            clock.now.return_value = fixed_now
            output = io.StringIO()
            with redirect_stdout(output):
                result = refresh_market_cache.main(["--latest"])

        self.assertEqual(result, 0)
        refresh.assert_called_once_with("20260715", mode="xlsx")
        self.assertEqual(output.getvalue().strip(), "mode=xlsx date=20260715 rows=4100")

    def test_cli_returns_nonzero_on_import_failure(self):
        from quant_web import refresh_market_cache

        with patch.dict("os.environ", {"MARKET_STORAGE_MODE": "csv"}), patch(
            "quant_web.refresh_market_cache.refresh_market_cache",
            side_effect=RuntimeError("broken snapshot"),
        ):
            error = io.StringIO()
            with redirect_stderr(error):
                result = refresh_market_cache.main(["--date", "20260714"])

        self.assertEqual(result, 1)
        self.assertIn("broken snapshot", error.getvalue())


if __name__ == "__main__":
    unittest.main()
