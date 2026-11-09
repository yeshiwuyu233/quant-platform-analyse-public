import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class TestMenuAndScreenerAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from quant_web import app
        cls.web = app

    def setUp(self):
        # Canonical identity and membership checks have separate integration
        # coverage. Exercise these real route decorators without real accounts.
        hooks = patch.dict(self.web.app.before_request_funcs, {None: [self.web._check_csrf_for_unsafe_methods]})
        hooks.start()
        self.addCleanup(hooks.stop)
        self.client = self.web.app.test_client()

    def login(self, role='user'):
        with self.client.session_transaction() as session:
            session['user'] = {'username': 'access-test', 'role': role, 'name': 'Test'}

    def test_menu_visibility_uses_role_and_vpn_permission_separately(self):
        for role in ('user', 'admin'):
            for vpn in (False, True):
                with self.subTest(role=role, vpn=vpn), self.web.app.test_request_context('/'):
                    self.web.session['user'] = {'username': 'access-test', 'role': role, 'name': 'Test'}
                    html = self.web.render_template('base.html', service_permissions={'vpn': vpn})
                    self.assertEqual('href="/screener"' in html, role == 'admin')
                    self.assertEqual('href="/vpn/"' in html, vpn)

    def test_missing_vpn_permission_hides_menu(self):
        with self.web.app.test_request_context('/'):
            self.web.session['user'] = {'username': 'access-test', 'role': 'user', 'name': 'Test'}
            html = self.web.render_template('base.html')
        self.assertNotIn('href="/vpn/"', html)

    def test_member_cannot_open_screener_api_or_export_or_reach_data_reads(self):
        self.login()
        with patch.object(self.web.ds, 'get_available_dates', side_effect=AssertionError('Read protected dates')), \
             patch.object(self.web.ds, 'query_screener', side_effect=AssertionError('Read protected stocks')), \
             patch.object(self.web.ds, 'get_screener_data', side_effect=AssertionError('Exported protected stocks')):
            for path in ('/screener', '/screener/20261028', '/screener/', '/api/screener/20261028',
                         '/export/screener', '/export/screener/20261028', '/export/%73creener/20261028'):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 403)
                    if path.startswith(('/api/', '/export/')):
                        self.assertEqual(response.get_json(), {'error': 'forbidden'})

    def test_admin_can_open_screener_query_and_export(self):
        self.login('admin')
        with patch.object(self.web.ds, 'get_available_dates', return_value=['20261028']), \
             patch.object(self.web.ds, 'get_all_industries', return_value=['测试行业']), \
             patch.object(self.web.ds, 'get_screener_count', return_value=1), \
             patch.object(self.web.ds, 'query_screener', return_value={'rows': [{'代码': '000001'}], 'total': 1}), \
             patch.object(self.web.ds, 'get_screener_data', return_value=[{'代码': '000001'}]):
            self.assertEqual(self.client.get('/screener').status_code, 200)
            response = self.client.get('/api/screener/20261028')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['total'], 1)
            exported = self.client.get('/export/screener/20261028')
            self.assertEqual(exported.status_code, 200)
            self.assertTrue(exported.data.startswith(b'PK'))

    def test_other_member_exports_and_timing_remain_available(self):
        self.login()
        with patch.object(self.web.ds, 'get_history_data', return_value=[{'date': '2026/10/28', 'all_pct': 61.54}]):
            self.assertEqual(self.client.get('/export/history').status_code, 200)
            self.assertEqual(self.client.get('/api/history').status_code, 200)
        self.assertEqual(self.client.get('/history/settings').status_code, 200)

    def test_anonymous_screener_requires_login(self):
        self.assertEqual(self.client.get('/screener').status_code, 302)
        self.assertEqual(self.client.get('/api/screener/20261028').status_code, 401)


if __name__ == '__main__':
    unittest.main()
