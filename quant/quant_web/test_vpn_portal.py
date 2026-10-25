import contextlib,io,json,pathlib,sqlite3,tempfile,unittest
from unittest.mock import patch
from flask import Flask,session,jsonify
from accounts import auth_stamp,UserAccounts
from vpn_portal import register_vpn_portal,StreamBody,unix_rpc

class PortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name);self.db=self.root/'users.db'
        con=sqlite3.connect(self.db);con.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,email TEXT,name TEXT,role TEXT,password_hash TEXT)')
        con.executemany('INSERT INTO users VALUES(?,?,?,?,?,?)',[(1,'admin','owner@example.test','Owner','admin','admin-hash'),(2,'alice','alice@example.test','Alice','user','alice-hash')]);con.commit();con.close()
        UserAccounts(self.db)
        (self.root/'portal.html').write_text('{{ vpn_bootstrap|tojson }}')
        self.app=Flask(__name__);self.app.secret_key='test-only-secret';self.calls=[]
        def rpc(method,path,principal,body,headers):
            self.calls.append((method,path,principal,body,headers));return 200,{'Content-Type':'application/json'},b'{"enabled":true,"device":{}}'
        register_vpn_portal(self.app,self.db,'unused.sock',self.root,self.root,transport=rpc)
        self.app.add_url_rule('/outside',view_func=lambda:jsonify(user=session.get('user')))
        self.client=self.app.test_client()
    def tearDown(self):self.tmp.cleanup()
    def login(self,username='alice',role='admin'):
        uid=1 if username=='admin' else 2
        with self.client.session_transaction() as s:
            s['user']={'username':username,'role':role};s['vpn_user_id']=uid;s['_csrf_token']='csrf-test'
            s['vpn_auth_stamp']=auth_stamp(self.db,uid,self.app.secret_key)
    def test_password_change_invalidates_existing_session_across_website(self):
        self.login()
        with contextlib.closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE users SET password_hash='new-hash' WHERE id=2")
        self.assertIsNone(self.client.get('/outside').json['user'])
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_role_change_rejects_old_admin_cookie(self):
        self.login('admin')
        with contextlib.closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE users SET role='user' WHERE id=1")
        self.assertEqual(self.client.get('/vpn/api/admin/users').status_code,401)
    def test_missing_stamp_requires_relogin_once(self):
        self.login()
        with self.client.session_transaction() as s:s.pop('vpn_auth_stamp')
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_valid_cookie_refreshes_name_and_canonical_username(self):
        self.login('alice@example.test')
        with contextlib.closing(sqlite3.connect(self.db)) as c,c:c.execute("UPDATE users SET name='Updated name' WHERE id=2")
        user=self.client.get('/outside').json['user'];self.assertEqual(user['username'],'alice');self.assertEqual(user['name'],'Updated name')
    def test_anonymous_page_redirects_and_api_401(self):
        self.assertEqual(self.client.get('/vpn/').status_code,302)
        self.assertEqual(self.client.get('/vpn/api/devices').status_code,401);self.assertEqual(self.calls,[])
    def test_subscription_is_anonymous_fixed_resource_without_website_cookie(self):
        token='a'*43
        path='/vpn/subscription-download/'
        r=self.client.get(path+'config.yaml',headers={'X-VPN-Subscription-Token':token})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.calls[-1][1],'/public/subscriptions/'+token+'/config.yaml')
        self.assertEqual(self.calls[-1][2]['id'],0)
        self.assertEqual(r.headers['Profile-Web-Page-Url'],'https://example.com/vpn/')
        self.assertEqual(self.client.get(path+'devices',headers={'X-VPN-Subscription-Token':token}).status_code,404)
        self.assertEqual(self.client.get(path+'config.yaml?admin=1',headers={'X-VPN-Subscription-Token':token}).status_code,404)
        self.assertEqual(self.client.get(path+'config.yaml').status_code,404)
        self.assertEqual(self.client.get('/vpn/api/admin/system/health').status_code,401)
    def test_normal_member_cannot_read_system_totals(self):
        self.login()
        self.assertEqual(self.client.get('/vpn/api/admin/system/usage').status_code,403)
        self.assertEqual(self.calls,[])
    def test_principal_from_database_not_session_role_or_request_header(self):
        self.login();self.assertEqual(self.client.get('/vpn/api/devices',headers={'X-VPN-User-ID':'1'}).status_code,200)
        p=self.calls[-1][2];self.assertEqual(p['id'],2);self.assertEqual(p['role'],'user')
    def test_post_requires_session_csrf_and_fixed_origin(self):
        self.login();path='/vpn/api/devices'
        self.assertEqual(self.client.post(path,json={}).status_code,403)
        self.assertEqual(self.client.post(path,json={},headers={'X-CSRF-Token':'csrf-test','Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post(path,json={},headers={'X-CSRF-Token':'csrf-test','Origin':'https://example.com'}).status_code,200)
    def test_canonical_email_login_and_deleted_user_rechecked(self):
        self.login('alice@example.test');self.assertEqual(self.client.get('/vpn/api/me').status_code,200)
        self.assertEqual(self.calls[-1][2]['username'],'alice')
        con=sqlite3.connect(self.db);con.execute('DELETE FROM users WHERE id=2');con.commit();con.close()
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_logout_switch_returns_to_vpn_login(self):
        self.login();r=self.client.post('/vpn/logout',data={'csrf_token':'csrf-test'},headers={'Origin':'https://example.com'})
        self.assertEqual(r.status_code,302);self.assertIn('next=',r.location)
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_bootstrap_uses_canonical_identity_and_csrf(self):
        self.login();r=self.client.get('/vpn/');self.assertEqual(r.status_code,200)
        payload=json.loads(r.data);self.assertEqual(payload['user']['id'],2);self.assertEqual(payload['csrf_token'],'csrf-test')
        self.assertEqual(r.headers['Referrer-Policy'],'same-origin')
    def test_recreated_username_does_not_rebind_old_login(self):
        self.login();con=sqlite3.connect(self.db)
        con.execute('DELETE FROM users WHERE id=2');con.execute("INSERT INTO users(id,username,email,name,role,password_hash) VALUES(3,'alice','new@example.test','New','admin','new-hash')");con.commit();con.close()
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_old_session_without_bound_id_requires_relogin(self):
        self.login()
        with self.client.session_transaction() as s:s.pop('vpn_user_id')
        self.assertEqual(self.client.get('/vpn/api/me').status_code,401)
    def test_unstarted_download_stream_can_be_closed(self):
        class Connection:
            closed=False
            def close(self):self.closed=True
        con=Connection();response=io.BytesIO(b'download')
        body=StreamBody(response,con);body.close()
        self.assertTrue(response.closed);self.assertTrue(con.closed)
    def test_download_head_closes_connection_immediately(self):
        class Result(io.BytesIO):
            status=200
            def getheaders(self):return [('Content-Length','100')]
        response=Result(b'data')
        with patch('vpn_portal.UnixConnection') as connection:
            connection.return_value.getresponse.return_value=response
            status,headers,body=unix_rpc('unused.sock','HEAD','/downloads/windows',{'id':1},None,{})
            self.assertEqual((status,body),(200,b''));self.assertTrue(response.closed)
            connection.return_value.close.assert_called_once()
