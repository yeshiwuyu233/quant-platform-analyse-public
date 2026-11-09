import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from quant_web import data_service as ds, im_quotes


class TestImQuoteCache(unittest.TestCase):
    def test_contract_is_selected_using_previous_open_interest(self):
        def contract(code, prior, current, opening, closing):
            return f'''<dailydata><instrumentid>{code}</instrumentid><tradingday>20261106</tradingday>
                <preopeninterest>{prior}</preopeninterest><openinterest>{current}</openinterest>
                <openprice>{opening}</openprice><closeprice>{closing}</closeprice>
                <volume>100</volume></dailydata>'''

        payload = '<dailydatas>' + contract('IM2611', 120, 250, 6400, 6490) + contract(
            'IM2612', 200, 100, 6400, 6460.8) + '</dailydatas>'
        quote = im_quotes.parse_daily_quote(payload, '20261106')
        self.assertEqual((quote['contract'], quote['close']), ('IM2612', '6460.8'))
        with self.assertRaises(ValueError):
            im_quotes.parse_daily_quote(payload, '20261105')

    def test_failed_refresh_retains_prior_quotes_and_retries_missing_dates(self):
        quote = {'contract': 'IM2612', 'open': '6400', 'close': '6460.8'}
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'im_daily.json'
            with patch.object(im_quotes, '_fetch_quote', return_value=quote):
                self.assertEqual(im_quotes.refresh_quotes(['20261106'], target), (1, {}))
            with patch.object(im_quotes, '_fetch_quote', side_effect=ValueError('Not published')) as fetch:
                self.assertEqual(im_quotes.refresh_quotes(['20261106', '20261109'], target),
                                 (0, {'20261109': 'Not published'}))
                fetch.assert_called_once_with('20261109')
            self.assertEqual(im_quotes.load_quotes(target), {'20261106': quote})


class TestDailyImSettlement(unittest.TestCase):
    def setUp(self):
        self.sessions = ['20261103', '20261104', '20261105', '20261106', '20261109']
        for cell in ds.get_daily_im_strategy_details.__closure__:
            if isinstance(cell.cell_contents, dict):
                cell.cell_contents.clear()

    def calculate(self, quotes):
        market = SimpleNamespace(get_market_dates=lambda: self.sessions[:-1])
        probabilities = {'20261103': 60, '20261104': 85, '20261105': 85, '20261106': 60}
        with patch.object(ds, 'market_db', market), patch.object(ds, '_get_exchange_sessions', return_value=self.sessions), \
             patch.object(ds, '_count_qualified_stocks', return_value=150), \
             patch.object(ds, '_read_previous_prediction_accuracy', return_value=probabilities), \
             patch.object(im_quotes, 'load_quotes', return_value=quotes), \
             ds.strategy_config.using_settings(ds.strategy_config.DEFAULT_SETTINGS):
            return ds.get_daily_im_strategy_details('20261106')

    def test_direction_cash_pnl_and_forecast(self):
        def quote(opening, closing):
            return {'contract': 'IM2612', 'open': opening, 'close': closing}

        rows = self.calculate({'20261104': quote('6180', '6469.2'),
                               '20261105': quote('6423', '6605'),
                               '20261106': quote('6400', '6460.8')})
        self.assertEqual([row['pnl'] for row in rows], [57840, -36400, -12160, None])
        self.assertEqual([row['cumulative_pnl'] for row in rows], [57840, 21440, 9280, None])
        self.assertEqual([row['drawdown_yuan'] for row in rows], [0, -36400, -48560, None])
        self.assertTrue(rows[-1]['is_forecast'])
        self.assertEqual(rows[-1]['position'], '做多 1 手')

    def test_gap_keeps_subsequent_cumulative_pnl_unknown(self):
        rows = self.calculate({'20261106': {'contract': 'IM2612', 'open': '6400', 'close': '6460.8'}})
        self.assertEqual(rows[0]['status'], '待 IM 行情')
        self.assertEqual(rows[2]['pnl'], -12160)
        self.assertIsNone(rows[2]['cumulative_pnl'])
        self.assertIsNone(rows[2]['drawdown_yuan'])
