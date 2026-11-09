import copy
import unittest
from unittest.mock import patch
from quant_web import data_service as ds


class TestAuditRegressions(unittest.TestCase):
    def test_fractional_position_is_displayed_exactly_in_daily_and_weekly(self):
        config = copy.deepcopy(ds.strategy_config.DEFAULT_SETTINGS)
        config['states']['1']['allocation_pct'] = 25.5
        with ds.strategy_config.using_settings(config):
            self.assertEqual(ds._daily_index_position(78, 12.85), (1, '做多25.5%'))
            self.assertAlmostEqual(ds._timing_positions(78, 12.85)[0], .255)

    def test_missing_yesterday_stays_in_detail_when_next_session_arrives(self):
        dates = ['20261026','20261027','20261028','20261029','20261030']
        with patch.object(ds, '_get_exchange_sessions', return_value=dates), \
             patch.object(ds, '_count_qualified_stocks', return_value=78), \
             patch.object(ds, '_read_previous_prediction_accuracy', return_value={'1027':12.85,'1028':80.95}), \
             ds.strategy_config.using_settings(ds.strategy_config.DEFAULT_SETTINGS):
            rows = ds.get_daily_index_strategy_details('20261029', history=[{'date_raw':'20261027','nav':2.2}])
        self.assertEqual([r['date_raw'] for r in rows], ['20261027','20261028','20261029'])
        self.assertEqual(rows[1]['position'], '做多80%')
        self.assertEqual(rows[2]['position'], '做空80%')
        self.assertIsNone(rows[1]['nav'])
        self.assertIsNone(rows[2]['nav'])

    def test_legacy_selected_count_is_corrected_without_filling_returns(self):
        report = {'meta': {'n_available': 5}, 'standard': {
            'summary': [{'策略分组': '指标大于1.0', '入选股票数': 1, '平均持仓回报': '2.00%'}],
            'sheets': {'指标大于1.0': {'rows': [{'T+5回报': '+1.00%'}, {'T+5回报': '待更新'}]}}}}
        corrected = ds._normalize_weekly_report_counts(report)
        row = corrected['standard']['summary'][0]
        self.assertEqual((row['入选股票数'], row['有效收益股票数'], row['缺失收益股票数']), (2, 1, 1))
        self.assertEqual(row['平均持仓回报'], '2.00%')
        self.assertTrue(corrected['meta']['count_corrections'])
        self.assertEqual(corrected['standard']['sheets']['指标大于1.0']['rows'][1]['T+5回报'], '待更新')

    def test_zero_valid_return_group_never_counts_as_zero_return_weight(self):
        value, count = ds._weighted_weekly_return([
            {'平均持仓回报': '10.00%', '有效收益股票数': 2, '入选股票数': 2},
            {'平均持仓回报': '0.00%', '有效收益股票数': 0, '入选股票数': 1},
        ])
        self.assertEqual(count, 2)
        self.assertAlmostEqual(value, .1)
