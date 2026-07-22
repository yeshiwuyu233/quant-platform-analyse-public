import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from quant_web import market_store
from quant_web.test_market_store import sample_market


class TestMarketWorkbookMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.xlsx = self.base / "market.xlsx"
        self.root = self.base / "market"

    def tearDown(self):
        self.tmp.cleanup()

    def write_workbook(self, sheets):
        with pd.ExcelWriter(self.xlsx) as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)

    def test_migrates_date_sheets_in_order_and_skips_summary(self):
        from quant_web import migrate_market_xlsx_to_csv as migration

        march = sample_market()
        april = sample_market()
        april.loc[0, "全称"] = "四月股票"
        self.write_workbook({
            "0401": april,
            "Summary": pd.DataFrame({"note": ["not a snapshot"]}),
            "0331": march,
        })

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            metas = migration.migrate_workbook(
                self.xlsx, year=2026, root=self.root, min_rows=1
            )

        self.assertEqual(
            [meta.full_date for meta in metas], ["20260331", "20260401"]
        )
        for full_date, source in (("20260331", march), ("20260401", april)):
            path = self.root / "2026" / f"{full_date}.csv"
            self.assertTrue(path.is_file())
            market_store.compare_frames(
                source, market_store.read_snapshot(full_date, root=self.root)
            )
        report = output.getvalue()
        self.assertRegex(
            report,
            r"20260331 rows=3 bytes=\d+ write_seconds=\d+\.\d{6} "
            r"validation_seconds=\d+\.\d{6}",
        )
        self.assertRegex(
            report,
            r"total snapshots=2 rows=6 bytes=\d+ write_seconds=\d+\.\d{6} "
            r"validation_seconds=\d+\.\d{6}",
        )

    def test_rejects_invalid_numeric_mmdd_before_writing(self):
        from quant_web import migrate_market_xlsx_to_csv as migration

        self.write_workbook({"0331": sample_market(), "0230": sample_market()})

        with self.assertRaisesRegex(ValueError, "invalid MMDD sheet"):
            migration.migrate_workbook(
                self.xlsx, year=2026, root=self.root, min_rows=1
            )

        self.assertFalse((self.root / "2026" / "20260331.csv").exists())

    def test_validate_only_compares_existing_csv_without_writing(self):
        from quant_web import migrate_market_xlsx_to_csv as migration

        source = sample_market()
        self.write_workbook({"0331": source})
        market_store.write_snapshot(
            "20260331", source, root=self.root, min_rows=1
        )
        snapshot = self.root / "2026" / "20260331.csv"
        manifest = self.root / "manifest.csv"
        before = (snapshot.read_bytes(), manifest.read_bytes())

        with mock.patch.object(
            migration.market_store,
            "write_snapshot",
            side_effect=AssertionError("validate-only attempted a write"),
        ):
            metas = migration.migrate_workbook(
                self.xlsx,
                year=2026,
                root=self.root,
                min_rows=1,
                validate_only=True,
            )

        self.assertEqual([meta.full_date for meta in metas], ["20260331"])
        self.assertEqual(
            (snapshot.read_bytes(), manifest.read_bytes()),
            before,
        )

    def test_validate_only_rejects_csv_mismatch(self):
        from quant_web import migrate_market_xlsx_to_csv as migration

        workbook_frame = sample_market()
        csv_frame = sample_market()
        csv_frame.loc[0, "全称"] = "不匹配"
        self.write_workbook({"0331": workbook_frame})
        market_store.write_snapshot(
            "20260331", csv_frame, root=self.root, min_rows=1
        )

        with self.assertRaises(AssertionError):
            migration.migrate_workbook(
                self.xlsx,
                year=2026,
                root=self.root,
                min_rows=1,
                validate_only=True,
            )


if __name__ == "__main__":
    unittest.main()
