import unittest
from unittest.mock import patch


class TestRunPipelineIndexRefresh(unittest.TestCase):
    def test_refresh_index_cache_updates_csi1000_only(self):
        from quant_web import run_pipeline

        with patch("quant_web.index_service.update_index_cache", return_value={"sh000852": 3}) as update:
            ok = run_pipeline.refresh_index_cache()

        self.assertTrue(ok)
        update.assert_called_once_with(symbols=["sh000852"])

    def test_refresh_index_cache_is_best_effort(self):
        from quant_web import run_pipeline

        with patch("quant_web.index_service.update_index_cache", side_effect=RuntimeError("network down")):
            ok = run_pipeline.refresh_index_cache()

        self.assertFalse(ok)


class TestRunPipelineMarketRefresh(unittest.TestCase):
    def test_refresh_market_cache_calls_shared_refresher_with_full_date(self):
        from quant_web import run_pipeline

        with patch.dict("os.environ", {"MARKET_STORAGE_MODE": "csv"}), patch(
            "quant_web.refresh_market_cache.refresh_market_cache", return_value=4123
        ) as refresh, self.assertLogs(run_pipeline.log, level="INFO") as logs:
            ok = run_pipeline.refresh_market_cache("20260714")

        self.assertTrue(ok)
        refresh.assert_called_once_with("20260714")
        self.assertIn("mode=csv date=20260714 rows=4123", "\n".join(logs.output))

    def test_refresh_market_cache_is_best_effort(self):
        from quant_web import run_pipeline

        with patch(
            "quant_web.refresh_market_cache.refresh_market_cache",
            side_effect=RuntimeError("cache down"),
        ):
            ok = run_pipeline.refresh_market_cache("20260714")

        self.assertFalse(ok)

    def test_main_aborts_postprocessing_when_market_refresh_fails(self):
        from quant_web import run_pipeline

        with patch.object(
            run_pipeline, "is_trading_day", return_value=True
        ), patch.object(
            run_pipeline, "crawl_today", return_value="ok"
        ), patch.object(
            run_pipeline, "refresh_market_cache", return_value=False
        ), patch.object(
            run_pipeline, "run_backtest"
        ) as backtest, patch.object(
            run_pipeline, "run_weekly"
        ) as weekly, patch.object(
            run_pipeline, "refresh_index_cache"
        ) as index_refresh, patch.object(
            run_pipeline, "_gather_email_data", return_value={}
        ), patch.object(
            run_pipeline, "send_notification"
        ) as notify:
            result = run_pipeline.main()

        self.assertEqual(result, 1)
        backtest.assert_not_called()
        weekly.assert_not_called()
        index_refresh.assert_not_called()
        self.assertFalse(notify.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
