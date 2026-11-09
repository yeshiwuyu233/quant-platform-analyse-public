"""Independent website capabilities. VPN capability uses the existing membership ledger."""
import http.client,posixpath,sqlite3,urllib.parse
from flask import g,jsonify,redirect,request,session
from accounts import read_user_db

PUBLIC_EXTENSIONS={'.css','.js','.png','.jpg','.jpeg','.gif','.svg','.ico','.woff','.woff2','.ttf','.map'}
QUANT_PREFIXES=('/backtest','/weekly','/history','/screener','/api/','/export/','/static/')

def clean_path(value):
    if not isinstance(value,str) or not value.startswith('/') or value.startswith('//'):return None
    if any(ord(c)<32 or ord(c)==127 for c in value) or '\\' in value:return None
    try:
        parts=urllib.parse.urlsplit(value)
        if parts.scheme or parts.netloc:return None
        path=parts.path
        for _ in range(4):
            decoded=urllib.parse.unquote(path)
            if decoded==path:break
            path=decoded
        if '%' in path or '\\' in path or path.startswith('//') or any(ord(c)<32 or ord(c)==127 for c in path):return None
        if '..' in path.split('/') or '.' in path.split('/'):return None
        return path
    except ValueError:return None

def safe_destination(value,quant,vpn):
    fallback='/' if quant else '/vpn/' if vpn else '/access-denied'
    path=clean_path(value)
    if not path or path in ('/login','/logout','/register','/access-denied') or path.startswith('/vpn/logout'):return fallback
    is_vpn=path=='/vpn' or path.startswith('/vpn/')
    if is_vpn and vpn:return value
    if not is_vpn and quant and (path=='/' or any(path.startswith(p) for p in QUANT_PREFIXES) or path.startswith('/admin/')):return value
    return fallback

def register_service_access(app,users_db,vpn_lookup):
    def permissions():
        uid=session.get('vpn_user_id')
        if not isinstance(session.get('user'),dict) or type(uid) is not int:return None
        with read_user_db(users_db) as con:
            row=con.execute('SELECT id,username,name,role,quant_enabled FROM users WHERE id=?',(uid,)).fetchone()
        if row is None:return None
        user=dict(row);admin=user['role']=='admin'
        quant=admin or bool(user['quant_enabled'])
        try:vpn=admin or bool(vpn_lookup(user))
        except (OSError,ValueError,http.client.HTTPException):
            if not quant or request.path=='/vpn' or request.path.startswith('/vpn/'):raise
            vpn=False
        return {'user':user,'admin':admin,'quant':quant,'vpn':vpn}
    def destination(value):
        p=permissions()
        return safe_destination(value,p['quant'],p['vpn']) if p else '/login'
    app.extensions['service_access_destination']=destination
    @app.context_processor
    def inject_permissions():return {'service_permissions':getattr(g,'service_permissions',{})}
    def denied(message='未开通此项服务，请联系管理员。'):
        return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>服务未开通</title><main style="max-width:600px;margin:15vh auto;font-family:system-ui"><h1>服务未开通</h1><p>'+message+'</p><a href="/logout">退出账号</a></main></html>',403
    def guard():
        endpoint=request.endpoint or '';path=request.path
        # Token subscriptions enforce ownership/membership in the private backend.
        if endpoint=='vpn_portal.subscription' or path.startswith('/vpn/assets/'):return None
        if path.startswith('/static/') and posixpath.splitext(path)[1].lower() in PUBLIC_EXTENSIONS:return None
        if path in ('/health','/logout','/register'):return None
        if request.endpoint is None and path!='/access-denied':return None
        is_api=path.startswith(('/api/','/vpn/api/','/vpn/qr/','/export/','/static/')) or request.is_json
        try:p=permissions()
        except (sqlite3.Error,OSError,ValueError,http.client.HTTPException):return jsonify(error='account_service_unavailable'),503
        if path=='/login':
            if p and request.method=='GET':return redirect(safe_destination(request.args.get('next','/'),p['quant'],p['vpn']))
            return None
        if not p:
            if is_api:return jsonify(error='login_required'),401
            return redirect('/login?'+urllib.parse.urlencode({'next':path}))
        g.service_permissions=p
        if path=='/access-denied':return denied()
        if path.startswith('/admin/') or path=='/debug':
            if not p['admin']:return jsonify(error='forbidden'),403
            if path=='/admin/users':
                if request.method in ('GET','HEAD'):return redirect('/vpn/#/admin/users')
                return jsonify(error='user_management_moved',message='请使用统一用户管理。'),410
            return None
        is_vpn=path=='/vpn' or path.startswith('/vpn/')
        allowed=p['vpn'] if is_vpn else p['quant']
        if allowed:return None
        if is_api or request.method not in ('GET','HEAD'):return jsonify(error='service_forbidden'),403
        if p['quant'] or p['vpn']:return redirect('/' if p['quant'] else '/vpn/')
        return denied()
    # Existing VPN integration places canonical login refresh first.
    app.before_request_funcs.setdefault(None,[]).insert(1,guard)
