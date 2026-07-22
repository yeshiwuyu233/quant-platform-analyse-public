import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quant_web import db_service, market_store
from quant_web.test_market_store import sample_market


class TestMarketImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "market"
        self.db_path = str(Path(self.tmp.name) / "market.db")
        self.previous_db_path = db_service.DB_PATH
        db_service.DB_PATH = self.db_path

    def tearDown(self):
        db_service.DB_PATH = self.previous_db_path
        self.tmp.cleanup()

    def test_import_frame_preserves_market_columns(self):
        from quant_web.market_import import import_frame

        conn = db_service.get_db()
        try:
            db_service.init_db(conn)
            count = import_frame(conn, "0714", sample_market())
            conn.commit()
            rows = conn.execute(
                """SELECT code, name, industry, accuracy, indicator,
                          indicator_history
                   FROM market_snapshot
                   WHERE trade_date = ? ORDER BY row_order""",
                ("0714",),
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(count, 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            tuple(rows[0]),
            ("000000.SZ", "股票0", "银行", 0.7, 1.2, "(+1.20%)"),
        )

    def test_second_import_replaces_same_date(self):
        from quant_web.market_import import import_frame

        conn = db_service.get_db()
        try:
            db_service.init_db(conn)
            import_frame(conn, "0714", sample_market())
            replacement = sample_market(1)
            replacement.loc[0, "全称"] = "替换后"
            import_frame(conn, "0714", replacement)
            conn.commit()
            rows = conn.execute(
                "SELECT code, name FROM market_snapshot WHERE trade_date = ?",
                ("0714",),
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual([tuple(row) for row in rows], [("000000.SZ", "替换后")])

    def test_import_csv_snapshot_records_metadata(self):
        from quant_web.import_market_csv import import_csv_snapshot

        market_store.write_snapshot(
            "20260714", sample_market(), root=self.root, min_rows=1
        )
        self.assertEqual(import_csv_snapshot("20260714", self.root), 3)

        conn = db_service.get_db()
        try:
            meta = conn.execute(
                "SELECT rows_count FROM import_meta WHERE trade_date = ?", ("0714",)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(meta["rows_count"], 3)

    def test_import_csv_snapshot_rolls_back_and_keeps_borrowed_connection_open(self):
        from quant_web.import_market_csv import import_csv_snapshot
        from quant_web.market_import import import_frame

        conn = db_service.get_db()
        try:
            db_service.init_db(conn)
            import_frame(conn, "0714", sample_market(1))
            conn.commit()
            invalid = sample_market().drop(columns=["指标历史"])
            with mock.patch.object(market_store, "read_snapshot", return_value=invalid):
                with self.assertRaisesRegex(ValueError, "missing columns"):
                    import_csv_snapshot("20260714", self.root, conn=conn)
            count = conn.execute(
                "SELECT COUNT(*) FROM market_snapshot WHERE trade_date = '0714'"
            ).fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(count, 1)

    def test_import_csv_snapshot_closes_owned_connection_after_failure(self):
        from quant_web.import_market_csv import import_csv_snapshot

        conn = db_service.get_db()
        invalid = sample_market().drop(columns=["指标历史"])
        with mock.patch.object(db_service, "get_db", return_value=conn), mock.patch.object(
            market_store, "read_snapshot", return_value=invalid
        ):
            with self.assertRaisesRegex(ValueError, "missing columns"):
                import_csv_snapshot("20260714", self.root)

        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
