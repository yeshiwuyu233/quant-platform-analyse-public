import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_web import data_service as ds
from quant_web import trading_calendar as calendar

SESSIONS = ['20261020', '20261021', '20261022', '20261023', '20261026',
            '20261027', '20261028', '20261029', '20261030', '20261102', '20261103', '20261104']


class TestUnsettledTimingDetails(unittest.TestCase):
    def setUp(self):
        context = ds.strategy_config.using_settings(copy.deepcopy(ds.strategy_config.DEFAULT_SETTINGS))
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        calendars = patch.object(ds, '_get_exchange_sessions', return_value=SESSIONS)
        calendars.start()
        self.addCleanup(calendars.stop)
        counts = patch.object(ds, '_count_qualified_stocks', return_value=78)
        self.count = counts.start()
        self.addCleanup(counts.stop)
        accuracy = patch.object(ds, '_read_previous_prediction_accuracy', return_value={
            '1023': 80.95, '1026': 64.71, '1027': 12.85,
        })
        accuracy.start()
        self.addCleanup(accuracy.stop)

    def test_today_direction_exists_without_todays_market_quotes(self):
        with patch.object(ds, '_read_index_cache_rows', return_value=[{'date': '20261027'}]):
            prediction = ds.get_daily_index_prediction('20261028')
        self.assertEqual(prediction['signal_date_raw'], '20261027')
        self.assertEqual(prediction['prediction_accuracy'], 12.85)
        self.assertEqual(prediction['position'], '做多80%')
        self.assertEqual(prediction['state_id'], 1)

    def test_pending_daily_row_does_not_copy_yesterdays_nav_or_create_returns(self):
        history = [{'date_raw': '20261027', 'nav': 2.264528, 'drawdown': -10.68}]
        before = copy.deepcopy(history)
        rows = ds.get_daily_index_strategy_details('20261028', history=history)
        self.assertEqual(history, before)
        self.assertEqual(len(rows), 2)
        pending = rows[-1]
        self.assertEqual((pending['signal_date_raw'], pending['date_raw']), ('20261027', '20261028'))
        self.assertEqual(pending['position'], '做多80%')
        self.assertTrue(pending['is_pending'])
        for field in ('index_open', 'index_close', 'index_return', 'strategy_return', 'nav', 'drawdown'):
            self.assertIsNone(pending[field])

    def test_published_today_replaces_pending_row_without_duplicate(self):
        row = {'date_raw': '20261028', 'position': '做多80%', 'nav': 2.3}
        rows = ds.get_daily_index_strategy_details('20261028', history=[row])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['is_pending'])
        self.assertEqual(rows[0]['nav'], 2.3)

    def test_closed_day_shows_next_session_and_missing_previous_signal_is_not_reused(self):
        rows = ds.get_daily_index_strategy_details('20261025', history=[])
        self.assertEqual([row['date_raw'] for row in rows], ['20261026'])
        self.assertEqual(rows[0]['signal_date_raw'], '20261023')
        self.assertTrue(rows[0]['is_forecast'])
        self.count.return_value = None
        self.assertIsNone(ds.get_daily_index_prediction('20261026'))
        rows = ds.get_daily_index_strategy_details('20261026', history=[])
        self.assertEqual(rows[-1]['signal_date_raw'], '20261023')
        self.assertEqual(rows[-1]['position'], '-')
        self.count.assert_called_with('20261023')

    def test_weekly_details_include_unsettled_and_today_with_no_future_input(self):
        class Market:
            def get_market_dates(self):
                return ['1023', '1026', '1027', '1028']
        completed = [{'date_raw': '1023', 'date': '10/23', 'exit_date_raw': '1030', 'top_nav': 1.1}]
        with patch.object(ds, 'market_db', Market()):
            rows = ds.get_weekly_strategy_details('20261028', history=completed)
        self.assertEqual([row['trade_date_raw'] for row in rows], ['20261026', '20261027', '20261028'])
        self.assertFalse(rows[0]['is_pending'])
        self.assertEqual(rows[0]['top_nav'], 1.1)
        today = rows[-1]
        self.assertEqual(today['prediction_accuracy'], 12.85)
        self.assertEqual(today['futures_position'], '做多80%')
        self.assertEqual(today['stock_position'], '做多100%')
        self.assertEqual(today['exit_date_raw'], '20261103')
        for series in ('top', 'filtered_top', 'futures_timing', 'stock_timing', 'cold', 'standard', 'csi1000'):
            for metric in ('return', 'nav', 'drawdown'):
                self.assertIsNone(today[f'{series}_{metric}'])

    def test_prior_session_survives_weekends_and_year_boundary(self):
        with patch.object(ds, '_get_exchange_sessions', return_value=['20261231', '20270104', '20270105']), \
             patch.object(ds, '_read_previous_prediction_accuracy', return_value={'20261231': 12.85}):
            row = ds.get_daily_index_prediction('20270104')
        self.assertEqual(row['signal_date_raw'], '20261231')
        self.assertEqual(row['position'], '做多80%')


class TestExchangeCalendarCache(unittest.TestCase):
    def test_calendar_caches_sessions_and_never_fills_missing_weekdays(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(calendar, 'CALENDAR_PATH', Path(directory) / 'calendar.json'), \
             patch.object(calendar, '_fetch_sessions', return_value=SESSIONS) as fetch:
            self.assertEqual(calendar.load_sessions('20261028'), SESSIONS)
            self.assertEqual(calendar.load_sessions('20261029'), SESSIONS)
            self.assertEqual(fetch.call_count, 1)
            self.assertNotIn('20261025', calendar.load_sessions('20261025'))


class TestTimingPageRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from quant_web import app
        cls.web = app

    def test_history_does_not_compute_timing_and_new_page_uses_personal_context(self):
        web = self.web
        with web.app.test_request_context('/history'), \
             patch.object(web.ds, 'get_history_data', return_value=[]), \
             patch.object(web.ds, 'get_history_index_trend', return_value={}), \
             patch.object(web.ds, 'get_available_dates', return_value=[]), \
             patch.object(web.ds, 'get_weekly_strategy_history', side_effect=AssertionError('history calculated timing')):
            html = web.history.__wrapped__()
        self.assertNotIn('id="marketStateRules"', html)
        self.assertNotIn('id="weeklyStrategyPanel"', html)
        self.assertIn('/history/timing', html)
        with web.app.test_request_context('/history/timing'), \
             patch.object(web.ds, 'get_weekly_strategy_history', return_value=[]), \
             patch.object(web.ds, 'get_daily_index_strategy_history', return_value=[]), \
             patch.object(web.ds, 'get_weekly_strategy_details', return_value=[]), \
             patch.object(web.ds, 'get_daily_index_strategy_details', return_value=[]), \
             patch.object(web.ds, 'get_latest_daily_index_prediction', return_value=None):
            web.session['user'] = {'username': 'page-test', 'role': 'user', 'name': 'test'}
            html = web.timing_backtest.__wrapped__()
        self.assertIn('择时回测', html)
        self.assertIn('id="marketStateRules"', html)
        self.assertNotIn('id="winRateChart"', html)
