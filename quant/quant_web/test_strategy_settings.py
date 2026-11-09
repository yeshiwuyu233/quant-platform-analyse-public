import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_web import data_service as ds
from quant_web import strategy_settings as store


class TestStrategySettingsStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'settings.json'
        self.patch = patch.object(store, 'SETTINGS_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)
        def clear_strategy_cache():
            for function in (ds.get_daily_index_strategy_history, ds.get_weekly_strategy_history):
                for cell in function.__closure__ or ():
                    if isinstance(cell.cell_contents, dict):
                        cell.cell_contents.clear()
        clear_strategy_cache()
        self.addCleanup(clear_strategy_cache)

    def test_defaults_save_restore_and_concurrent_edits(self):
        self.assertEqual(store.load_document()['version'], 0)
        config = copy.deepcopy(store.DEFAULT_SETTINGS)
        config['states']['1']['allocation_pct'] = 30
        saved = store.save_settings(config, actor='admin', expected_version=0)
        self.assertEqual((saved['version'], saved['updated_by']), (1, 'admin'))
        with self.assertRaises(store.SettingsConflict):
            store.save_settings(config, actor='stale-tab', expected_version=0)
        restored = store.save_settings(None, actor='admin', expected_version=1, restore=True)
        self.assertEqual(restored['version'], 2)
        self.assertEqual(restored['config'], store.DEFAULT_SETTINGS)
        self.assertEqual([r['version'] for r in restored['history']], [0, 1])

    def test_initial_settings_stay_fixed_when_defaults_and_returned_copies_change(self):
        config = copy.deepcopy(store.DEFAULT_SETTINGS)
        config['systemic_count'] = 50
        config['states']['1']['allocation_pct'] = 25
        store.save_settings(config, actor='admin', expected_version=0)
        initial = store.initial_settings()
        self.assertEqual(initial['thresholds'], {'rebound_below': 22, 'down_below': 45, 'range_ceiling': 55, 'pullback_above': 78})
        self.assertEqual((initial['systemic_count'], initial['daily_leverage']), (60, 6))
        self.assertEqual([initial['states'][str(i)]['allocation_pct'] for i in range(1, 7)], [80, 80, 80, 50, 50, 50])
        self.assertEqual([initial['states'][str(i)]['direction'] for i in range(1, 7)], [1, -1, -1, -1, 1, 1])
        initial['states']['1']['allocation_pct'] = 1
        self.assertEqual(store.initial_settings()['states']['1']['allocation_pct'], 80)
        self.assertEqual(store.load_document()['config']['systemic_count'], 50)

    def test_personal_settings_are_isolated_and_inherit_system_defaults(self):
        config = copy.deepcopy(store.DEFAULT_SETTINGS)
        config['systemic_count'] = 50
        store.save_settings(config, actor='admin', expected_version=0)
        with store.using_account('alice'):
            inherited = store.load_document()
            self.assertEqual((inherited['version'], inherited['source']), (0, 'default'))
            self.assertEqual(inherited['config']['systemic_count'], 50)
            personal = copy.deepcopy(inherited['config'])
            personal['states']['1']['allocation_pct'] = 25
            store.save_settings(personal, actor='alice', expected_version=0)
        with store.using_account('bob'):
            self.assertEqual(store.load_document()['config']['states']['1']['allocation_pct'], 80)
            self.assertEqual(store.load_document()['source'], 'default')
        with store.using_account('alice'):
            self.assertEqual(store.load_document()['config']['states']['1']['allocation_pct'], 25)
            self.assertEqual(store.load_document()['source'], 'personal')
        self.assertEqual(store.load_document()['config']['states']['1']['allocation_pct'], 80)

    def test_rejects_invalid_order_nan_bounds_and_fractional_counts(self):
        variants = []
        for key, value in (('rebound_below', 60), ('down_below', float('nan'))):
            c = copy.deepcopy(store.DEFAULT_SETTINGS)
            c['thresholds'][key] = value
            variants.append(c)
        for key, value in (('systemic_count', 50.5), ('daily_leverage', -1)):
            c = copy.deepcopy(store.DEFAULT_SETTINGS)
            c[key] = value
            variants.append(c)
        c = copy.deepcopy(store.DEFAULT_SETTINGS)
        c['states']['1']['allocation_pct'] = 101
        variants.append(c)
        for c in variants:
            with self.subTest(config=c), self.assertRaises(store.SettingsError):
                store.save_settings(c, actor='admin', expected_version=0)
        self.assertFalse(self.path.exists())

    def test_failed_atomic_replace_preserves_previous_document(self):
        store.save_settings(store.DEFAULT_SETTINGS, actor='admin', expected_version=0)
        before = self.path.read_bytes()
        with patch.object(store.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                store.save_settings(store.DEFAULT_SETTINGS, actor='admin', expected_version=1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('.strategy-*')), [])

    def test_invalid_file_never_silently_falls_back(self):
        self.path.write_text('broken JSON')
        with self.assertRaises(store.SettingsError):
            store.load_document()

    def test_settings_change_invalidates_history_cache_without_restart(self):
        class Market:
            def get_market_dates(self):
                return ['20260401', '20260402']
        prices = [{'date': '20260401', 'open': 100, 'close': 100},
                  {'date': '20260402', 'open': 100, 'close': 101}]
        with patch.object(ds, 'market_db', Market()), patch.object(ds, '_count_qualified_stocks', return_value=100), \
             patch.object(ds, '_read_index_cache_rows', return_value=prices), \
             patch.object(ds, '_read_previous_prediction_accuracy', return_value={'20260401': 12.85}):
            before = ds.get_daily_index_strategy_history()[0]
            config = copy.deepcopy(store.DEFAULT_SETTINGS)
            config['states']['1']['allocation_pct'] = 40
            config['daily_leverage'] = 2
            store.save_settings(config, actor='admin', expected_version=0)
            after = ds.get_daily_index_strategy_history()[0]
            with store.using_account('alice'):
                personal = store.load_document()['config']
                personal['states']['1']['allocation_pct'] = 20
                store.save_settings(personal, actor='alice', expected_version=0)
                alice = ds.get_daily_index_strategy_history()[0]
            with store.using_account('bob'):
                bob = ds.get_daily_index_strategy_history()[0]
            self.assertEqual((alice['position'], alice['strategy_return']), ('做多20%', 0.4))
            self.assertEqual((bob['position'], bob['strategy_return']), ('做多40%', 0.8))

        self.assertEqual((before['position'], before['strategy_return']), ('做多80%', 4.8))
        self.assertEqual((after['position'], after['strategy_return'], after['nav']), ('做多40%', 0.8, 1.008))

    def test_direction_zero_position_and_count_are_shared_by_weekly_and_daily(self):
        config = copy.deepcopy(store.DEFAULT_SETTINGS)
        config['systemic_count'] = 50
        config['states']['5']['direction'] = -1
        config['states']['1']['allocation_pct'] = 0
        with store.using_settings(config):
            self.assertEqual(ds._market_timing_signal(55, 60)['state_id'], 6)
            self.assertEqual(ds._timing_positions(55, 60), (.5, True))
            self.assertEqual(ds._daily_index_position(100, 50), (-1, '做空50%'))
            self.assertEqual(ds._timing_positions(100, 50), (-.5, False))
            self.assertEqual(ds._daily_index_position(100, 12), (0, '空仓'))
            self.assertEqual(ds._timing_positions(100, 12), (0, False))


class TestStrategySettingsRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from quant_web import app
        cls.web = app

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = self.web.ds.strategy_config
        self.path = Path(self.temp.name) / 'settings.json'
        self.patch = patch.object(self.store, 'SETTINGS_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.temp.cleanup)
        # Membership/session refresh has separate integration tests. Keep this
        # feature's real admin decorator and CSRF check with synthetic sessions.
        hooks = patch.dict(self.web.app.before_request_funcs, {None: [self.web._check_csrf_for_unsafe_methods]})
        hooks.start()
        self.addCleanup(hooks.stop)
        self.client = self.web.app.test_client()

    def login(self, role='admin'):
        with self.client.session_transaction() as session:
            session['user'] = {'username': 'test-admin', 'role': role, 'name': 'Test'}
        response = self.client.get('/admin/strategy')
        if role == 'admin':
            self.assertEqual(response.status_code, 200)
            with self.client.session_transaction() as session:
                self.csrf = session['_csrf_token']
        return response

    def form(self, **changes):
        config = self.store.DEFAULT_SETTINGS
        form = {key: str(value) for key, value in config['thresholds'].items()}
        form.update(systemic_count='60', daily_leverage='6', version='0', action='preview')
        form['csrf_token'] = self.csrf
        for i in range(1, 7):
            form[f'direction_{i}'] = str(config['states'][str(i)]['direction'])
            form[f'allocation_{i}'] = str(config['states'][str(i)]['allocation_pct'])
        form.update(changes)
        return form

    def test_admin_only_and_csrf_required(self):
        self.assertEqual(self.client.get('/admin/strategy').status_code, 302)
        self.assertEqual(self.login('user').status_code, 403)
        self.login()
        response = self.client.post('/admin/strategy', data=self.form(action='save', csrf_token=''))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.path.exists())

    def test_preview_save_restore_and_stale_form(self):
        self.login()
        form = self.form(allocation_1='30', sample_count='10', sample_probability='12.85')
        preview = self.client.post('/admin/strategy', data=form)
        self.assertEqual(preview.status_code, 200)
        self.assertIn('做多30%', preview.get_data(as_text=True))
        self.assertIn('未保存的预览', preview.get_data(as_text=True))
        self.assertFalse(self.path.exists())
        form['action'] = 'save'
        self.assertEqual(self.client.post('/admin/strategy', data=form).status_code, 302)
        self.assertEqual(self.store.load_document()['config']['states']['1']['allocation_pct'], 30)
        self.assertEqual(self.client.post('/admin/strategy', data=form).status_code, 409)
        form.update(action='restore', version='1')
        self.assertEqual(self.client.post('/admin/strategy', data=form).status_code, 302)
        self.assertEqual(self.store.load_document()['config'], self.store.DEFAULT_SETTINGS)

    def test_regular_users_can_save_only_their_own_settings(self):
        with self.client.session_transaction() as session:
            session['user'] = {'username': 'alice', 'role': 'user', 'name': 'Alice'}
        self.assertEqual(self.client.get('/history/settings').status_code, 200)
        with self.client.session_transaction() as session:
            self.csrf = session['_csrf_token']
        form = self.form(action='save', allocation_1='25')
        self.assertEqual(self.client.post('/history/settings', data=form).status_code, 302)
        self.assertFalse(self.path.exists())
        with self.store.using_account('alice'):
            self.assertEqual(self.store.load_document()['config']['states']['1']['allocation_pct'], 25)
        with self.client.session_transaction() as session:
            session['user'] = {'username': 'bob', 'role': 'user', 'name': 'Bob'}
        response = self.client.get('/history/settings')
        self.assertEqual(response.status_code, 200)
        self.assertIn('80.0', response.get_data(as_text=True))
        self.assertEqual(self.client.get('/admin/strategy').status_code, 403)
        with self.store.using_account('bob'):
            self.assertEqual(self.store.load_document()['source'], 'default')

    def test_initialize_previews_original_rules_then_save_keeps_history_and_other_accounts(self):
        changed = self.store.initial_settings()
        changed['systemic_count'] = 50
        self.store.save_settings(changed, actor='admin', expected_version=0)
        with self.store.using_account('alice'):
            personal = copy.deepcopy(changed)
            personal['states']['1']['allocation_pct'] = 25
            saved = self.store.save_settings(personal, actor='alice', expected_version=0)
        with self.client.session_transaction() as session:
            session['user'] = {'username': 'alice', 'role': 'user', 'name': 'Alice'}
        self.client.get('/history/settings')
        with self.client.session_transaction() as session:
            self.csrf = session['_csrf_token']
        invalid_form = self.form(action='initialize', version='1', rebound_below='bad',
                                 direction_1='bad', sample_count='bad', sample_probability='bad')
        with patch.object(self.web, 'render_template', wraps=self.web.render_template) as render:
            response = self.client.post('/history/settings', data=invalid_form)
        self.assertEqual(response.status_code, 200)
        self.assertIn('已填回初始参数，保存后生效。', response.get_data(as_text=True))
        context = render.call_args.kwargs
        self.assertEqual(context['config'], self.store.initial_settings())
        self.assertEqual(context['values'], {})
        self.assertTrue(context['previewed'] and context['initialized'])
        with self.store.using_account('alice'):
            self.assertEqual(self.store.load_document()['config'], personal)
        save = self.client.post('/history/settings', data=self.form(action='save', version='1'))
        self.assertEqual(save.status_code, 302)
        with self.store.using_account('alice'):
            current = self.store.load_document()
            self.assertEqual(current['config'], self.store.initial_settings())
            self.assertEqual(current['version'], 2)
            self.assertEqual(current['history'][-1]['config'], saved['config'])
        self.assertEqual(self.store.load_document()['config']['systemic_count'], 50)
        with self.store.using_account('bob'):
            self.assertEqual(self.store.load_document()['config']['systemic_count'], 50)

    def test_initialize_is_available_without_history_and_requires_csrf(self):
        self.login()
        self.assertFalse(self.path.exists())
        response = self.client.post('/admin/strategy', data=self.form(action='initialize', csrf_token=''))
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/admin/strategy', data=self.form(action='initialize', rebound_below='bad'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('已填回初始参数，保存后生效。', response.get_data(as_text=True))
        self.assertFalse(self.path.exists())

    def test_weekly_api_uses_current_users_personal_settings(self):
        with self.store.using_account('alice'):
            config = self.store.load_document()['config']
            config['systemic_count'] = 50
            self.store.save_settings(config, actor='alice', expected_version=0)
        with patch.object(self.web.ds, 'get_weekly_strategy_history',
                          side_effect=lambda: [{'systemic_count': self.store.get_settings()['systemic_count']}]):
            for account, expected in (('alice', 50), ('bob', 60)):
                with self.client.session_transaction() as session:
                    session['user'] = {'username': account, 'role': 'user', 'name': account}
                response = self.client.get('/api/history/weekly-strategy')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()[0]['systemic_count'], expected)

    def test_bad_threshold_order_does_not_write(self):
        self.login()
        response = self.client.post('/admin/strategy', data=self.form(rebound_below='70', action='save'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('本次未保存', response.get_data(as_text=True))
        self.assertFalse(self.path.exists())
