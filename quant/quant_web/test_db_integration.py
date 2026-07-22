"""
Phase 1 数据库集成测试。
使用独立的临时数据库文件，不干扰生产 market.db。
全部可重复执行。
"""
import os
import sys
import tempfile
import sqlite3
import unittest

# ── 测试用 DB 路径覆盖 ──
_test_db_path = None  # 由 setUpModule 设置


def _set_test_db(path):
    global _test_db_path
    _test_db_path = path
    # patch db_service.DB_PATH
    import quant_web.db_service as dbs
    dbs.DB_PATH = path


class TestInitDB(unittest.TestCase):
    """init_db 幂等性和表结构测试"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mktemp(suffix='.db')
        _set_test_db(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.tmp)
            os.remove(cls.tmp + '-wal')
            os.remove(cls.tmp + '-shm')
        except OSError:
            pass

    def setUp(self):
        # 每次测试前删除旧文件，重新开始
        for f in [self.tmp, self.tmp + '-wal', self.tmp + '-shm']:
            try:
                os.remove(f)
            except OSError:
                pass

    def _tables(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def _indexes(self, conn):
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def test_init_db_creates_tables(self):
        from quant_web.db_service import init_db, get_db
        conn = get_db()
        init_db(conn)
        tables = self._tables(conn)
        for t in ('market_snapshot', 'daily_tracking', 'import_meta'):
            self.assertIn(t, tables, f"表 {t} 应被创建")
        conn.close()

    def test_init_db_idempotent(self):
        from quant_web.db_service import init_db, get_db
        conn = get_db()
        init_db(conn)
        tables1 = self._tables(conn)
        init_db(conn)  # 第二次调用
        tables2 = self._tables(conn)
        self.assertEqual(tables1, tables2, "重复 init_db 不应改变表结构")
        conn.close()

    def test_init_db_creates_indexes(self):
        from quant_web.db_service import init_db, get_db
        conn = get_db()
        init_db(conn)
        idxs = self._indexes(conn)
        self.assertIn('idx_ms_date', idxs)
        self.assertIn('idx_ms_ind', idxs)
        self.assertIn('idx_dt_date', idxs)
        conn.close()

    def test_init_db_no_argument(self):
        """init_db() 不带参数也应正常工作（自动开/关连接）"""
        from quant_web.db_service import init_db
        init_db()  # 不应抛异常

    def test_market_snapshot_schema(self):
        from quant_web.db_service import init_db, get_db
        conn = get_db()
        init_db(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(market_snapshot)").fetchall()]
        for col in ('trade_date', 'code', 'name', 'industry', 'accuracy', 'indicator', 'indicator_history'):
            self.assertIn(col, cols, f"market_snapshot 应包含列 {col}")
        conn.close()

    def test_daily_tracking_schema(self):
        from quant_web.db_service import init_db, get_db
        conn = get_db()
        init_db(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_tracking)").fetchall()]
        for col in ('trade_date', 'acc_08_raw', 'all_raw', 'next_10'):
            self.assertIn(col, cols, f"daily_tracking 应包含列 {col}")
        conn.close()


class TestMarketSnapshotCRUD(unittest.TestCase):
    """market_snapshot 表的增删查测试"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mktemp(suffix='.db')
        _set_test_db(cls.tmp)
        from quant_web.db_service import init_db
        init_db()

    @classmethod
    def tearDownClass(cls):
        for f in [cls.tmp, cls.tmp + '-wal', cls.tmp + '-shm']:
            try:
                os.remove(f)
            except OSError:
                pass

    def setUp(self):
        from quant_web.db_service import get_db
        conn = get_db()
        conn.execute("DELETE FROM market_snapshot")
        conn.execute("DELETE FROM import_meta")
        conn.commit()
        conn.close()

    def test_insert_and_query(self):
        from quant_web.db_service import execute, fetchall
        r = execute(
            "INSERT INTO market_snapshot (trade_date, code, name, industry, accuracy, indicator) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ('0511', '000001.SZ', '平安银行', '银行', 0.75, 1.2)
        )
        self.assertEqual(r, 1, "应影响 1 行")
        rows = fetchall("SELECT * FROM market_snapshot")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], '000001.SZ')
        self.assertEqual(rows[0]['trade_date'], '0511')

    def test_unique_constraint(self):
        from quant_web.db_service import execute
        execute(
            "INSERT INTO market_snapshot (trade_date, code, name) VALUES (?, ?, ?)",
            ('0511', '000001.SZ', '平安银行')
        )
        r = execute(
            "INSERT INTO market_snapshot (trade_date, code, name) VALUES (?, ?, ?)",
            ('0511', '000001.SZ', '平安银行')
        )
        self.assertEqual(r, 0, "相同 trade_date+code 应违反 UNIQUE 约束，影响 0 行")

    def test_query_empty_returns_empty_list(self):
        from quant_web.db_service import fetchall
        rows = fetchall("SELECT * FROM market_snapshot")
        self.assertEqual(rows, [])

    def test_fetchone_returns_none_when_empty(self):
        from quant_web.db_service import fetchone
        row = fetchone("SELECT * FROM market_snapshot WHERE trade_date = ?", ('9999',))
        self.assertIsNone(row)

    def test_query_by_date(self):
        from quant_web.db_service import execute, fetchall
        execute(
            "INSERT INTO market_snapshot (trade_date, code, name) VALUES (?, ?, ?)",
            ('0511', 'A', '股票A')
        )
        execute(
            "INSERT INTO market_snapshot (trade_date, code, name) VALUES (?, ?, ?)",
            ('0512', 'B', '股票B')
        )
        rows = fetchall("SELECT * FROM market_snapshot WHERE trade_date = ?", ('0511',))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['code'], 'A')

    def test_query_distinct_dates(self):
        from quant_web.db_service import execute, fetchall
        for d in ('0511', '0512', '0511', '0513'):
            execute(
                "INSERT OR IGNORE INTO market_snapshot (trade_date, code, name) VALUES (?, ?, ?)",
                (d, f'X.{d}', f'股票{d}')
            )
        dates = [r['trade_date'] for r in fetchall(
            "SELECT DISTINCT trade_date FROM market_snapshot ORDER BY trade_date"
        )]
        self.assertEqual(dates, ['0511', '0512', '0513'])

    def test_query_by_industry(self):
        from quant_web.db_service import execute, fetchall
        execute(
            "INSERT INTO market_snapshot (trade_date, code, name, industry) VALUES (?, ?, ?, ?)",
            ('0511', 'A', '股票A', '银行')
        )
        execute(
            "INSERT INTO market_snapshot (trade_date, code, name, industry) VALUES (?, ?, ?, ?)",
            ('0511', 'B', '股票B', '医药')
        )
        rows = fetchall(
            "SELECT DISTINCT industry FROM market_snapshot WHERE trade_date = ? ORDER BY industry",
            ('0511',)
        )
        inds = [r['industry'] for r in rows]
        self.assertIn('银行', inds)
        self.assertIn('医药', inds)


class TestDailyTrackingCRUD(unittest.TestCase):
    """daily_tracking 表测试"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mktemp(suffix='.db')
        _set_test_db(cls.tmp)
        from quant_web.db_service import init_db
        init_db()

    @classmethod
    def tearDownClass(cls):
        for f in [cls.tmp, cls.tmp + '-wal', cls.tmp + '-shm']:
            try:
                os.remove(f)
            except OSError:
                pass

    def setUp(self):
        from quant_web.db_service import get_db
        conn = get_db()
        conn.execute("DELETE FROM daily_tracking")
        conn.commit()
        conn.close()

    def test_insert_and_query_latest(self):
        from quant_web.db_service import execute, fetchone
        execute(
            "INSERT INTO daily_tracking (trade_date, all_raw, next_10) VALUES (?, ?, ?)",
            ('0511', '75.0%(30/40)', 15)
        )
        execute(
            "INSERT INTO daily_tracking (trade_date, all_raw, next_10) VALUES (?, ?, ?)",
            ('0512', '80.0%(32/40)', 18)
        )
        latest = fetchone(
            "SELECT * FROM daily_tracking ORDER BY trade_date DESC LIMIT 1"
        )
        self.assertIsNotNone(latest)
        self.assertEqual(latest['trade_date'], '0512')

    def test_unique_trade_date(self):
        from quant_web.db_service import execute
        execute(
            "INSERT INTO daily_tracking (trade_date, all_raw) VALUES (?, ?)",
            ('0511', 'test')
        )
        r = execute(
            "INSERT INTO daily_tracking (trade_date, all_raw) VALUES (?, ?)",
            ('0511', 'test')
        )
        self.assertEqual(r, 0, "重复 trade_date 应违反 UNIQUE")


class TestFetchHelpers(unittest.TestCase):
    """fetchone/fetchall 异常安全性测试"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mktemp(suffix='.db')
        _set_test_db(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        for f in [cls.tmp, cls.tmp + '-wal', cls.tmp + '-shm']:
            try:
                os.remove(f)
            except OSError:
                pass

    def test_fetchone_bad_sql_returns_none(self):
        from quant_web.db_service import fetchone
        result = fetchone("SELECT * FROM non_existent_table")
        self.assertIsNone(result)

    def test_fetchall_bad_sql_returns_empty(self):
        from quant_web.db_service import fetchall
        result = fetchall("SELECT * FROM non_existent_table")
        self.assertEqual(result, [])

    def test_execute_bad_sql_returns_zero(self):
        from quant_web.db_service import execute
        result = execute("INSERT INTO non_existent VALUES (1)")
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
