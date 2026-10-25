"""VPN routes sharing the existing website session and canonical user database."""
import contextlib,hmac,http.client,json,pathlib,re,secrets,socket,sqlite3,urllib.parse,traceback
from flask import Blueprint,Response,g,jsonify,redirect,render_template,request,send_from_directory,session
from accounts import auth_stamp,read_user_db

ORIGINS={'https://example.com','https://www.example.com'}

def resolve_user(db,login):
    if not isinstance(login,str) or not login:return None
    with read_user_db(db) as con:
        con.row_factory=sqlite3.Row
        row=con.execute('SELECT id,username,name,role FROM users WHERE username=?',(login,)).fetchone()
        if row is None and '@' in login:row=con.execute('SELECT id,username,name,role FROM users WHERE email=?',(login,)).fetchone()
        if row is None and '@' not in login:
            rows=con.execute('SELECT id,username,name,role FROM users WHERE email LIKE ? LIMIT 2',(login+'@%',)).fetchall()
            if len(rows)==1:row=rows[0]
        return dict(row) if row is not None else None

class UnixConnection(http.client.HTTPConnection):
    def __init__(self,path):super().__init__('localhost',timeout=12);self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(12);self.sock.connect(str(self.path))

class StreamBody:
    def __init__(self,response,connection):self.response=response;self.connection=connection
    def __iter__(self):
        try:
            while True:
                chunk=self.response.read(65536)
                if not chunk:break
                yield chunk
        finally:self.close()
    def close(self):self.response.close();self.connection.close()

def unix_rpc(socket_path,method,path,principal,body,headers):
    con=UnixConnection(socket_path)
    outgoing={'X-VPN-User-ID':str(principal['id']),'Content-Type':'application/json'}
    if headers.get('Range'):outgoing['Range']=headers['Range']
    try:
        con.request(method,path,body=body,headers=outgoing);r=con.getresponse()
        allowed={'content-type','content-length','content-disposition','content-range','accept-ranges','subscription-userinfo','profile-update-interval','profile-web-page-url'}
        response_headers={k:v for k,v in r.getheaders() if k.lower() in allowed}
        if method=='HEAD':r.close();con.close();return r.status,response_headers,b''
        if path.startswith('/downloads/') and r.status in (200,206):
            return r.status,response_headers,StreamBody(r,con)
        data=r.read(4*1024*1024+1)
        if len(data)>4*1024*1024:raise ValueError('internal response too large')
        con.close();return r.status,response_headers,data
    except Exception:
        con.close();raise

def register_vpn_portal(app,users_db,socket_path,template_dir=None,assets_dir=None,transport=None):
    template_dir=pathlib.Path(template_dir or pathlib.Path(__file__).parent/'vpn_portal_templates')
    assets_dir=pathlib.Path(assets_dir or pathlib.Path(__file__).parent/'vpn_portal_assets')
    bp=Blueprint('vpn_portal',__name__,url_prefix='/vpn',template_folder=str(template_dir))
    rpc=transport or (lambda method,path,principal,body,headers:unix_rpc(socket_path,method,path,principal,body,headers))
    def refresh_website_login():
        if not isinstance(session.get('user'),dict):return None
        if request.endpoint in ('vpn_portal.assets','vpn_portal.subscription'):return None
        try:
            expected=auth_stamp(users_db,session.get('vpn_user_id'),app.secret_key)
            supplied=session.get('vpn_auth_stamp')
            if not expected or not isinstance(supplied,str) or not hmac.compare_digest(expected,supplied):
                for key in ('user','vpn_user_id','vpn_auth_stamp','_csrf_token'):session.pop(key,None)
                return None
            with read_user_db(users_db) as con:
                row=con.execute('SELECT username,role,name FROM users WHERE id=?',(session['vpn_user_id'],)).fetchone()
            canonical={'username':row[0],'role':row[1],'name':row[2] or row[0]}
            if session.get('user')!=canonical:session['user']=canonical
        except sqlite3.Error:
            for key in ('user','vpn_user_id','vpn_auth_stamp','_csrf_token'):session.pop(key,None)
            return jsonify(error='account_service_unavailable'),503
    # Must run before the original website's role/session guards, not just /vpn/.
    app.before_request_funcs.setdefault(None,[]).insert(0,refresh_website_login)
    def principal():
        identity=session.get('vpn_user_id')
        user=None
        if isinstance(session.get('user'),dict) and type(identity) is int and identity>0:
            with read_user_db(users_db) as con:
                con.row_factory=sqlite3.Row
                row=con.execute('SELECT id,username,name,role FROM users WHERE id=?',(identity,)).fetchone()
                if row is not None:user=dict(row)
        if not user:session.pop('user',None);session.pop('vpn_user_id',None)
        return user
    def csrf():
        if '_csrf_token' not in session:session['_csrf_token']=secrets.token_hex(32)
        return session['_csrf_token']
    @bp.before_request
    def guard():
        if request.endpoint in ('vpn_portal.assets','vpn_portal.subscription'):return None
        try:g.vpn_user=principal()
        except sqlite3.Error:return jsonify(error='account_service_unavailable'),503
        if not g.vpn_user:
            if request.path.startswith('/vpn/api/') or request.path.startswith('/vpn/qr/'):return jsonify(error='login_required'),401
            return redirect('/login?'+urllib.parse.urlencode({'next':'/vpn/'}))
        if request.method in ('POST','PATCH','PUT','DELETE'):
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf_token','')
            expected=session.get('_csrf_token')
            if request.headers.get('Origin') not in ORIGINS or not expected or not hmac.compare_digest(str(supplied),str(expected)):
                return jsonify(error='csrf_validation_failed'),403
    @bp.after_request
    def private(response):
        response.headers['Cache-Control']='public, max-age=86400' if request.endpoint=='vpn_portal.assets' and response.status_code in (200,304) else 'no-store'
        response.headers['Referrer-Policy']='same-origin';response.headers['X-Content-Type-Options']='nosniff'
        return response
    def proxy(path):
        if request.content_length and request.content_length>16384:return jsonify(error='request_too_large'),413
        if request.method in ('POST','PATCH','DELETE') and not request.is_json:return jsonify(error='json_required'),400
        body=request.get_data() if request.method in ('POST','PATCH','DELETE') else None
        try:
            status,headers,data=rpc(request.method,path,g.vpn_user,body,{'Range':request.headers.get('Range')})
            return Response(data,status=status,headers=headers)
        except (OSError,ValueError,http.client.HTTPException) as exc:
            app.logger.warning('VPN internal RPC failed: endpoint=%s class=%s errno=%s frames=%s',request.endpoint,type(exc).__name__,getattr(exc,'errno',None),''.join(traceback.format_tb(exc.__traceback__)))
            return jsonify(error='vpn_service_unavailable'),503
    @bp.get('/')
    def home():
        enabled=False
        try:
            status,_,body=rpc('GET','/me',g.vpn_user,None,{})
            if status==200:enabled=bool(json.loads(body).get('enabled'))
        except (OSError,ValueError,http.client.HTTPException):pass
        return render_template('portal.html',vpn_bootstrap={'user':g.vpn_user,'csrf_token':csrf(),'base':'/vpn/','enabled':enabled})
    @bp.route('/api/<path:route>',methods=['GET','POST','PATCH','DELETE'])
    def api(route):
        if route.startswith('admin/') and g.vpn_user['role']!='admin':return jsonify(error='forbidden'),403
        suffix=('?'+request.query_string.decode('ascii')) if request.query_string else ''
        return proxy('/'+route+suffix)
    @bp.get('/qr/<device_id>.png')
    def qr(device_id):return proxy('/devices/'+device_id+'/qr')
    @bp.get('/subscription-download/<kind>')
    def subscription(kind):
        # Nginx rewrites the public token URL before Gunicorn access logging.
        token=request.headers.get('X-VPN-Subscription-Token','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or kind not in ('config.yaml','shadowrocket.txt','node.txt') or request.query_string:
            return jsonify(error='not_found'),404
        try:
            status,headers,data=rpc(request.method,'/public/subscriptions/'+token+'/'+kind,{'id':0},None,{})
            headers.setdefault('Profile-Update-Interval','1');headers.setdefault('Profile-Web-Page-Url','https://example.com/vpn/')
            return Response(data,status=status,headers=headers)
        except (OSError,ValueError,http.client.HTTPException):return jsonify(error='subscription_unavailable'),503
    @bp.get('/downloads/<name>')
    def download(name):return proxy('/downloads/'+name)
    @bp.get('/assets/<name>')
    def assets(name):
        if name not in ('portal.js','portal.css','system.js','system.css','quota.js','quota.css','shell.js','shell.css','view-model.js','scene-lake.png'):return jsonify(error='not_found'),404
        return send_from_directory(assets_dir,name,max_age=86400)
    @bp.post('/logout')
    def logout():
        session.pop('user',None);session.pop('_csrf_token',None);session.pop('vpn_user_id',None);session.pop('vpn_auth_stamp',None)
        return redirect('/login?'+urllib.parse.urlencode({'next':'/vpn/'}))
    app.register_blueprint(bp)
