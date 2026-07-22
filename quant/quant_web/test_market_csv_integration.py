import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


WEB_ROOT = Path(__file__).resolve().parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from quant_web import batch_backtest
from quant_web import batch_weekly
from quant_web import db_service
from quant_web import import_market_csv
from quant_web import market_store
import report_paths as runtime_report_paths


def market_frame(day_index: int, rows: int = 4) -> pd.DataFrame:
    returns = [1.0, -0.5, 0.8, 0.2]
    return pd.DataFrame({
        "全称": [f"测试股票{i}" for i in range(rows)],
        "代码": [f"{i:06d}.SZ" for i in range(rows)],
        "行业": ["银行", "银行", "科技", "传媒"][:rows],
        "地域": ["深圳", "上海", "北京", "广州"][:rows],
        "准确率": [0.75, 0.72, 0.68, 0.65][:rows],
        "追踪天数": [90] * rows,
        "倍数": ["1.48(5.05)"] * rows,
        "指标历史": [
            f"({value + day_index / 10:+.2f}%)" for value in returns[:rows]
        ],
        "近三日涨幅": ["-"] * rows,
        "今日指标": [1.3, 1.1, 0.9, 1.4][:rows],
        "指标趋势": [0.2, -0.1, 0.1, 0.3][:rows],
    })


class TestCsvMarketPipelineIntegration(unittest.TestCase):
    def test_csv_to_sqlite_backtest_and_weekly_reports_stay_isolated(self):
        full_dates = [f"202607{day:02d}" for day in range(1, 7)]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            market_root = temporary_root / "data" / "market"
            database_path = temporary_root / "market.db"
            reports_root = temporary_root / "reports"
            market_lock = temporary_root / ".locks" / "market.lock"

            with mock.patch.object(db_service, "DB_PATH", str(database_path)), \
                    mock.patch.object(
                        runtime_report_paths, "PROJECT_ROOT", str(temporary_root)
                    ), mock.patch.object(
                        runtime_report_paths, "REPORTS_DIR", str(reports_root)
                    ), mock.patch.object(
                        batch_backtest, "PROJECT_ROOT", str(temporary_root)
                    ), mock.patch.object(
                        batch_weekly, "PROJECT_ROOT", str(temporary_root)
                    ):
                for day_index, full_date in enumerate(full_dates):
                    market_store.write_snapshot(
                        full_date,
                        market_frame(day_index),
                        root=market_root,
                        lock_path=market_lock,
                        min_rows=1,
                    )
                    imported = import_market_csv.import_csv_snapshot(
                        full_date, root=market_root
                    )
                    self.assertEqual(imported, 4)

                self.assertEqual(db_service.get_market_dates(), [
                    "0701", "0702", "0703", "0704", "0705", "0706"
                ])

                self.assertTrue(
                    batch_backtest.run_single_backtest("0702", fix_stale=False)
                )
                backtest_json = reports_root / "0702量化复盘报告.json"
                self.assertTrue(backtest_json.is_file())
                self.assertIn("tracking", json.loads(
                    backtest_json.read_text(encoding="utf-8")
                ))

                # Weekly discovery uses workbook names as eligibility markers;
                # all market data reads still use the isolated SQLite database.
                for legacy_date in ("0703", "0704", "0705", "0706"):
                    (reports_root / f"{legacy_date}量化复盘报告.xlsx").touch()

                self.assertTrue(batch_weekly.run_incremental_weekly("0706"))
                weekly_json = reports_root / "0706的选股策略礼拜攻势.json"
                self.assertTrue(weekly_json.is_file())
                weekly_report = json.loads(
                    weekly_json.read_text(encoding="utf-8")
                )
                self.assertEqual(weekly_report["meta"]["date"], "0706")

            self.assertTrue(database_path.is_file())
            self.assertTrue((temporary_root / "history.json").is_file())
            self.assertTrue((temporary_root / "weekly_trend.json").is_file())
            self.assertTrue(
                (reports_root / "0706的选股策略礼拜攻势.json").is_file()
            )
            self.assertEqual(list(temporary_root.rglob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
