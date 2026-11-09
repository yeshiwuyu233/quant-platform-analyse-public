import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from quant_web import data_service as ds
from quant_web import db_service as db


class TestTimingCounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        target = patch.object(db, 'DB_PATH', str(Path(self.temp.name) / 'market.db'))
        target.start(); self.addCleanup(target.stop)
        db.init_db()

    def insert(self, date, rows):
        with db.get_db() as con:
            con.executemany('INSERT INTO market_snapshot(trade_date,code,accuracy,indicator) VALUES(?,?,?,?)',
                            [(date, str(i), acc, ind) for i, (acc, ind) in enumerate(rows)])

    def test_sql_matches_original_count_at_boundaries_nulls_and_zero(self):
        values = [(0.6, 2), (0.6000001, 1.1), (0.7, 1), (0.7, 1.000001),
                  (None, 2), (0.9, None), (0.0, 2), (float('inf'), 2)]
        self.insert('1028', values)
        frame = db.read_market_sheet('1028')
        old = int(((pd.to_numeric(frame['准确率'], errors='coerce') > .6)
                   & (pd.to_numeric(frame['今日指标'], errors='coerce') > 1)).sum())
        self.assertEqual(db.count_qualified_stocks('20261028'), old)
        self.assertEqual(db.count_qualified_stocks('1028'), old)
        self.insert('1029', [(0.6, 1)])
        self.assertEqual(db.count_qualified_stocks('1029'), 0)
        self.assertIsNone(db.count_qualified_stocks('1030'))
        self.insert('20271028', [(0.9, 2)])
        self.assertEqual(db.count_qualified_stocks('20271028'), 1)

    def test_unusual_text_values_keep_legacy_coercion(self):
        self.insert('1028', [('inf', 2), ('0.8bad', 2), ('', 3), ('0.9', '1.5')])
        with patch.object(ds, 'market_db', db):
            self.assertEqual(ds._count_qualified_stocks('20261028'), 2)

    def test_fast_path_does_not_read_full_stock_rows_and_new_requests_see_updates(self):
        self.insert('1028', [(0.9, 2)])
        with patch.object(ds, 'market_db', db), \
             patch.object(db, 'read_market_sheet', side_effect=AssertionError('Read stock details')):
            with ds.timing_input_session():
                self.assertEqual(ds._count_qualified_stocks('20261028'), 1)
                with db.get_db() as con:
                    con.execute("INSERT INTO market_snapshot(trade_date,code,accuracy,indicator) VALUES('1028','new',.9,2)")
                self.assertEqual(ds._count_qualified_stocks('20261028'), 1)
            with ds.timing_input_session():
                self.assertEqual(ds._count_qualified_stocks('20261028'), 2)

    def test_report_inputs_are_read_once_per_request_without_stale_cross_request_data(self):
        path = Path(self.temp.name) / '1028量化复盘报告.json'
        def write(value):
            path.write_text(json.dumps({'history_entry': {'date_raw': '20261028', 'prev_date': '20261027', 'all_pct': value}}))
        write(61.54)
        with patch.object(ds, 'glob_reports', return_value=[str(path)]) as files:
            with ds.timing_input_session():
                self.assertEqual(list(ds._read_previous_prediction_accuracy().values()), [61.54])
                ds._read_previous_prediction_accuracy()
                self.assertEqual(files.call_count, 1)
            write(22)
            with ds.timing_input_session():
                self.assertEqual(list(ds._read_previous_prediction_accuracy().values()), [22])
                self.assertEqual(files.call_count, 2)

    def test_exception_clears_request_cache(self):
        self.insert('1028', [(0.9, 2)])
        with patch.object(ds, 'market_db', db):
            with self.assertRaises(RuntimeError):
                with ds.timing_input_session():
                    ds._count_qualified_stocks('20261028')
                    raise RuntimeError('page failed')
            with db.get_db() as con:
                con.execute("DELETE FROM market_snapshot WHERE trade_date='1028'")
            self.assertIsNone(ds._count_qualified_stocks('20261028'))
