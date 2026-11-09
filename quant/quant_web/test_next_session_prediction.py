import copy
import unittest
from unittest.mock import patch

from quant_web import data_service as ds


class TestNextSessionPrediction(unittest.TestCase):
    def setUp(self):
        self.sessions = ['20261027', '20261028', '20261029', '20261030', '20261102']
        self.counts = {'20261027': 78, '20261028': 191}
        self.accuracy = {'1027': 12.85, '1028': 61.54, '1029': 99.0}
        for target, kwargs in (
            ('market_db', {'new': object()}),
            ('_get_exchange_sessions', {'side_effect': lambda _: self.sessions}),
            ('_count_qualified_stocks', {'side_effect': self.counts.get}),
            ('_read_previous_prediction_accuracy', {'side_effect': lambda: self.accuracy}),
        ):
            patcher = patch.object(ds, target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        settings = ds.strategy_config.using_settings(copy.deepcopy(ds.strategy_config.DEFAULT_SETTINGS))
        settings.__enter__()
        self.addCleanup(settings.__exit__, None, None, None)

    def test_published_inputs_add_next_session_without_changing_settled_rows(self):
        history = [{'date_raw': '20261028', 'nav': 2.41575, 'strategy_return': 6.6778}]
        original = copy.deepcopy(history)
        rows = ds.get_daily_index_strategy_details('20261028', history=history)
        self.assertEqual(history, original)
        self.assertEqual([r['date_raw'] for r in rows], ['20261028', '20261029'])
        forecast = rows[-1]
        self.assertEqual((forecast['signal_date_raw'], forecast['gt1_count'], forecast['prediction_accuracy']),
                         ('20261028', 191, 61.54))
        self.assertEqual((forecast['state_id'], forecast['position'], forecast['status']), (6, '做多50%', '待开盘'))
        self.assertTrue(forecast['is_forecast'])
        for field in ('index_open', 'index_close', 'index_return', 'strategy_return', 'nav', 'drawdown', 'effective_exposure'):
            self.assertIsNone(forecast[field])
        top = ds.get_latest_daily_index_prediction('20261028')
        self.assertEqual((top['date_raw'], top['position']), (forecast['date_raw'], forecast['position']))

    def test_partial_or_invalid_signal_keeps_todays_prediction(self):
        for count, probability in ((None, 61.54), (191, None), (191, float('nan'))):
            with self.subTest(count=count, probability=probability):
                self.counts['20261028'] = count
                self.accuracy['1028'] = probability
                self.assertIsNone(ds._next_daily_index_prediction('20261028'))
                prediction = ds.get_latest_daily_index_prediction('20261028')
                self.assertEqual((prediction['date_raw'], prediction['position']), ('20261028', '做多80%'))
                rows = ds.get_daily_index_strategy_details('20261028', history=[{'date_raw': '20261028'}])
                self.assertEqual(len(rows), 1)

    def test_zero_qualified_stocks_is_a_valid_forecast_input(self):
        self.counts['20261028'] = 0
        prediction = ds.get_latest_daily_index_prediction('20261028')
        self.assertEqual((prediction['date_raw'], prediction['state_id'], prediction['position']),
                         ('20261029', 3, '做空80%'))

    def test_weekends_holidays_and_new_year_use_the_exchange_calendar(self):
        for today, signal, next_date in (
            ('20261030', '20261030', '20261102'),
            ('20261031', '20261030', '20261102'),
            ('20261001', '20260930', '20261008'),
            ('20261231', '20261231', '20270104'),
        ):
            with self.subTest(today=today):
                self.sessions = [signal, next_date]
                self.counts[signal] = 191
                self.accuracy[signal] = 61.54
                prediction = ds.get_latest_daily_index_prediction(today)
                self.assertEqual((prediction['signal_date_raw'], prediction['date_raw']), (signal, next_date))

    def test_unknown_future_calendar_never_guesses_a_weekday(self):
        self.sessions = ['20261027', '20261028']
        self.assertIsNone(ds._next_daily_index_prediction('20261028'))
        self.assertEqual(ds.get_latest_daily_index_prediction('20261028')['date_raw'], '20261028')

    def test_today_specific_api_keeps_its_original_date_semantics(self):
        prediction = ds.get_daily_index_prediction('20261028')
        self.assertEqual((prediction['date_raw'], prediction['signal_date_raw'], prediction['position']),
                         ('20261028', '20261027', '做多80%'))

    def test_next_morning_keeps_forecast_until_new_signal_is_ready(self):
        prediction = ds.get_latest_daily_index_prediction('20261029')
        self.assertEqual((prediction['date_raw'], prediction['signal_date_raw']), ('20261029', '20261028'))
        rows = ds.get_daily_index_strategy_details('20261029', history=[{'date_raw': '20261028'}])
        self.assertEqual([row['date_raw'] for row in rows], ['20261028', '20261029'])
        self.assertEqual(rows[-1]['position'], '做多50%')

    def test_top_prediction_and_details_respect_personal_settings(self):
        config = copy.deepcopy(ds.strategy_config.DEFAULT_SETTINGS)
        config['states']['6'].update(direction=-1, allocation_pct=35.5)
        with ds.strategy_config.using_settings(config):
            prediction = ds.get_latest_daily_index_prediction('20261028')
            rows = ds.get_daily_index_strategy_details('20261028', history=[{'date_raw': '20261028'}])
        self.assertEqual(prediction['position'], '做空35.5%')
        self.assertEqual(rows[-1]['position'], prediction['position'])

    def test_existing_next_session_row_is_not_duplicated(self):
        history = [{'date_raw': '20261028'}, {'date_raw': '20261029'}]
        rows = ds.get_daily_index_strategy_details('20261028', history=history)
        self.assertEqual([row['date_raw'] for row in rows], ['20261028', '20261029'])


if __name__ == '__main__':
    unittest.main()
