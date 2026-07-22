import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_web import data_service
from quant_web import app as market_app


def clear_ttl_cache(function):
    for cell in function.__closure__ or ():
        value = cell.cell_contents
        if isinstance(value, dict):
            value.clear()


class TestCsvMarketFallbacks(unittest.TestCase):
    def setUp(self):
        for function in (
            data_service.get_available_dates,
            data_service.get_screener_count,
            data_service._read_market_sheet,
            data_service.get_all_industries,
        ):
            clear_ttl_cache(function)
        self.frame = pd.DataFrame({
            "代码": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "全称": ["甲", "乙", "丙"],
            "行业": ["银行", "科技", "银行"],
            "准确率": ["0.7", "0.8", "0.9"],
            "今日指标": ["1.1", "1.2", "1.3"],
            "指标历史": ["", "", ""],
        })

    def test_available_dates_falls_back_to_csv_dates(self):
        with mock.patch.object(
            data_service.market_db, "get_market_dates", return_value=[]
        ), mock.patch.object(
            data_service.market_store,
            "list_legacy_dates",
            return_value=["0713", "0714"],
        ), mock.patch.object(
            data_service.pd,
            "ExcelFile",
            side_effect=AssertionError("opened production workbook"),
        ):
            self.assertEqual(data_service.get_available_dates(), ["0713", "0714"])

    def test_market_sheet_falls_back_to_csv_dataframe(self):
        with mock.patch.object(
            data_service.market_db, "read_market_sheet", return_value=None
        ), mock.patch.object(
            data_service.market_store, "read_snapshot", return_value=self.frame.copy()
        ) as read_snapshot, mock.patch.object(
            data_service.pd,
            "read_excel",
            side_effect=AssertionError("opened production workbook"),
        ):
            result = data_service._read_market_sheet("0714")

        read_snapshot.assert_called_once_with("0714")
        self.assertEqual(result.shape, self.frame.shape)
        self.assertTrue(pd.api.types.is_numeric_dtype(result["准确率"]))
        self.assertTrue(pd.api.types.is_numeric_dtype(result["今日指标"]))

    def test_screener_count_falls_back_to_csv_row_count(self):
        with mock.patch.object(
            data_service.market_db, "count_market_rows", return_value=None
        ), mock.patch.object(
            data_service.market_store, "read_snapshot", return_value=self.frame.copy()
        ), mock.patch.object(
            data_service.pd,
            "read_excel",
            side_effect=AssertionError("opened production workbook"),
        ):
            self.assertEqual(data_service.get_screener_count("0714"), 3)

    def test_industries_fall_back_to_sorted_csv_values(self):
        with mock.patch.object(
            data_service.market_db, "get_market_dates", return_value=[]
        ), mock.patch.object(
            data_service.market_db, "get_industries", return_value=[]
        ), mock.patch.object(
            data_service.market_store, "list_legacy_dates", return_value=["0714"]
        ), mock.patch.object(
            data_service.market_store, "read_snapshot", return_value=self.frame.copy()
        ), mock.patch.object(
            data_service.pd,
            "read_excel",
            side_effect=AssertionError("opened production workbook"),
        ):
            self.assertEqual(data_service.get_all_industries(), ["科技", "银行"])


class TestMarketUploadPipeline(unittest.TestCase):
    def test_pipeline_persists_full_date_before_refreshing_same_date(self):
        frame = pd.DataFrame({"代码": ["000001.SZ"], "准确率": [0.7]})
        calls = []

        def persist(full_date, actual):
            calls.append(("persist", full_date))
            pd.testing.assert_frame_equal(actual, frame)

        def refresh(full_date):
            calls.append(("refresh", full_date))
            return len(frame)

        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            temp_csv = os.path.join(tmp, "upload.csv")
            frame.to_csv(temp_csv, index=False)
            with mock.patch.object(
                market_app, "_read_pipeline_status", return_value={"history": []}
            ), mock.patch.object(
                market_app, "_write_pipeline_status"
            ), mock.patch.object(
                market_app.market_writer,
                "persist_market_dataframe",
                side_effect=persist,
            ), mock.patch.object(
                market_app.market_cache_refresher,
                "refresh_market_cache",
                side_effect=refresh,
            ), mock.patch.object(
                market_app.subprocess, "run", return_value=completed
            ) as run, mock.patch.object(
                market_app, "_build_pipeline_email", return_value="body"
            ), mock.patch.object(market_app, "_send_pipeline_notification"):
                market_app._run_pipeline_for_date("20260714", temp_csv)

        self.assertEqual(calls, [("persist", "20260714"), ("refresh", "20260714")])
        self.assertEqual(run.call_count, 2)

    def test_pipeline_aborts_reports_when_cache_refresh_fails(self):
        frame = pd.DataFrame({"代码": ["000001.SZ"], "准确率": [0.7]})
        written_statuses = []

        with tempfile.TemporaryDirectory() as tmp:
            temp_csv = os.path.join(tmp, "upload.csv")
            frame.to_csv(temp_csv, index=False)
            with mock.patch.object(
                market_app, "_read_pipeline_status", return_value={"history": []}
            ), mock.patch.object(
                market_app,
                "_write_pipeline_status",
                side_effect=lambda status: written_statuses.append(status.copy()),
            ), mock.patch.object(
                market_app.market_writer, "persist_market_dataframe"
            ), mock.patch.object(
                market_app.market_cache_refresher,
                "refresh_market_cache",
                side_effect=RuntimeError("cache down"),
            ), mock.patch.object(
                market_app.subprocess, "run"
            ) as run, mock.patch.object(
                market_app, "_send_pipeline_notification"
            ) as notify:
                market_app._run_pipeline_for_date("20260714", temp_csv)

            self.assertFalse(os.path.exists(temp_csv))

        run.assert_not_called()
        self.assertEqual(written_statuses[-1]["stage"], "failed")
        self.assertIn("cache", written_statuses[-1]["error"])
        notify.assert_called_once()
        self.assertFalse(notify.call_args.args[0])


class TestMarketNotifications(unittest.TestCase):
    def test_five_day_settlement_uses_sqlite_date_order(self):
        dates = ["0707", "0701", "0706", "0702", "0705", "0703", "0704"]
        reports = [f"/reports/{date}量化复盘报告.xlsx" for date in dates]
        with mock.patch.object(
            market_app.dbs, "get_market_dates", return_value=dates
        ), mock.patch.object(
            market_app, "glob_reports", return_value=reports
        ), mock.patch.object(
            market_app, "resolve_report", side_effect=lambda name: f"/missing/{name}"
        ), mock.patch.object(
            market_app.os.path, "exists", return_value=False
        ), mock.patch.object(
            market_app.pd,
            "ExcelFile",
            side_effect=AssertionError("opened production workbook"),
        ):
            body = market_app._build_pipeline_email("0707", True, True, 1)

        self.assertIn("礼拜攻势 07/02 结仓: 无数据", body)


class TestMarketAdminActions(unittest.TestCase):
    def invoke(self, action):
        with market_app.app.test_request_context("/admin/health/action/" + action):
            return market_app.admin_health_action.__wrapped__(action)

    def test_incremental_rebuild_refreshes_latest_configured_storage(self):
        with mock.patch.object(market_app.subprocess, "Popen") as popen:
            self.invoke("rebuild_sqlite")

        popen.assert_called_once_with([
            "python3",
            "/var/www/quant/quant_web/refresh_market_cache.py",
            "--latest",
        ])

    def test_full_rebuild_imports_all_csv_snapshots_in_csv_mode(self):
        with mock.patch.object(
            market_app.market_store,
            "get_storage_mode",
            return_value=market_app.market_store.StorageMode.CSV,
        ), mock.patch.object(market_app.subprocess, "Popen") as popen:
            self.invoke("rebuild_sqlite_all")

        popen.assert_called_once_with([
            "python3",
            "/var/www/quant/quant_web/import_market_csv.py",
            "--all",
        ])

    def test_full_rebuild_is_unavailable_outside_csv_mode(self):
        with mock.patch.object(
            market_app.market_store,
            "get_storage_mode",
            return_value=market_app.market_store.StorageMode.XLSX,
        ), mock.patch.object(market_app.subprocess, "Popen") as popen:
            self.invoke("rebuild_sqlite_all")

        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
