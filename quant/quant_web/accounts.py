"""Administrator account edits against the original website user database."""
import contextlib,datetime,hashlib,hmac,json,pathlib,re,secrets,sqlite3

PUBLIC='id,username,email,name,role,created_at'
FIELDS={'username','email','name','role','password'}

class AccountError(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message);self.status=status

@contextlib.contextmanager
def read_user_db(path):
    # WAL readers may need to recover shared-memory metadata. Open an existing
    # DB with that capability, then prohibit SQL writes on this connection.
    con=sqlite3.connect(pathlib.Path(path).resolve().as_uri()+'?mode=rw',uri=True,timeout=10)
    try:
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        yield con
    finally:con.close()

def auth_stamp(path,user_id,secret):
    """Opaque session binding; never put a password hash in a client cookie."""
    if type(user_id) is not int or user_id<=0:return None
    with read_user_db(path) as con:
        row=con.execute('SELECT id,username,email,role,password_hash,vpn_auth_revision FROM users WHERE id=?',(user_id,)).fetchone()
    if row is None:return None
    key=secret.encode() if isinstance(secret,str) else secret
    if not key:raise RuntimeError('website session secret missing')
    return hmac.new(key,json.dumps(list(row),separators=(',',':'),ensure_ascii=True).encode(),hashlib.sha256).hexdigest()

class UserAccounts:
    def __init__(self,path):
        self.path=str(path)
        with self.db(write=True) as con:
            if 'vpn_auth_revision' not in {r['name'] for r in con.execute('PRAGMA table_info(users)')}:
                con.execute("ALTER TABLE users ADD COLUMN vpn_auth_revision TEXT NOT NULL DEFAULT '0'")
            con.execute('''CREATE TRIGGER IF NOT EXISTS vpn_auth_revision_changed
                AFTER UPDATE OF username,email,password_hash,role ON users
                WHEN OLD.username IS NOT NEW.username OR OLD.email IS NOT NEW.email
                    OR OLD.password_hash IS NOT NEW.password_hash OR OLD.role IS NOT NEW.role
                BEGIN UPDATE users SET vpn_auth_revision=lower(hex(randomblob(32))) WHERE id=NEW.id; END''')
    @contextlib.contextmanager
    def db(self,write=False):
        con=sqlite3.connect(self.path,timeout=10);con.row_factory=sqlite3.Row
        try:
            with con:
                if write:con.execute('BEGIN IMMEDIATE')
                yield con
        finally:con.close()
    @staticmethod
    def _admin(con,actor):
        if type(actor) is not int or actor<=0:raise PermissionError('forbidden')
        row=con.execute('SELECT role FROM users WHERE id=?',(actor,)).fetchone()
        if row is None or row['role']!='admin':raise PermissionError('forbidden')
    @staticmethod
    def _public(row):
        out=dict(row)
        email=out['email'] or ''
        if re.fullmatch(r'vpn-[0-9a-f]{32}@no-email\.yeshiwuyu\.invalid',email):email=''
        out['email']=email
        return out
    @staticmethod
    def _placeholder_email():
        return 'vpn-'+secrets.token_hex(16)+'@no-email.yeshiwuyu.invalid'
    @staticmethod
    def _is_placeholder_email(value):
        return isinstance(value,str) and re.fullmatch(r'vpn-[0-9a-f]{32}@no-email\.yeshiwuyu\.invalid',value) is not None
    def list(self,actor):
        with self.db() as con:
            self._admin(con,actor)
            return [self._public(r) for r in con.execute('SELECT '+PUBLIC+' FROM users ORDER BY id')]
    @staticmethod
    def _values(data,create=False):
        if not isinstance(data,dict) or not data or set(data)-FIELDS:raise AccountError('提交的用户字段不正确。')
        data=dict(data)
        if create:
            if not data.get('username') or not data.get('password'):raise AccountError('请填写用户名和初始密码。')
            data.setdefault('name',data['username']);data.setdefault('role','user');data.setdefault('email','')
        for key in ('username','name','email','password','role'):
            if key in data and not isinstance(data[key],str):raise AccountError('用户字段必须是文字。')
        if 'username' in data:
            data['username']=data['username'].strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}',data['username']):raise AccountError('用户名需为 3–32 位字母、数字、下划线、点或短横线。')
        if 'name' in data:
            data['name']=data['name'].strip()
            if not 1<=len(data['name'])<=64 or any(ord(c)<32 or ord(c)==127 for c in data['name']):raise AccountError('昵称需为 1–64 字，不能包含控制字符。')
        if 'email' in data:
            value=data['email'].strip()
            if value and (len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value)):raise AccountError('请填写有效邮箱，或留空。')
            if value and value.rsplit('@',1)[1].lower()=='no-email.yeshiwuyu.invalid':raise AccountError('该邮箱域名为系统保留地址。')
            data['email']=value
        if 'role' in data and data['role'] not in ('user','admin'):raise AccountError('请选择普通用户或管理员。')
        if 'password' in data:
            password=data.pop('password')
            if password:
                if not 8<=len(password)<=128 or any(ord(c)<32 or ord(c)==127 for c in password):raise AccountError('密码需为 8–128 位，不能包含控制字符。')
                salt=secrets.token_bytes(16)
                data['password_hash']=salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,100000).hex()
            elif create:raise AccountError('请填写初始密码。')
        return data
    @staticmethod
    def _unique(con,data,exclude=0):
        for field,label in [('username','用户名'),('email','邮箱')]:
            if data.get(field) and con.execute('SELECT 1 FROM users WHERE lower('+field+')=lower(?) AND id<>?',(data[field],exclude)).fetchone():
                raise AccountError(label+'已被其他账号使用。',409)
    def create(self,actor,payload):
        with self.db(write=True) as con:
            self._admin(con,actor);data=self._values(payload,True)
            if not data.get('email'):data['email']=self._placeholder_email()
            self._unique(con,data)
            data['created_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
            fields=list(data)
            try:
                cur=con.execute('INSERT INTO users('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',[data[k] for k in fields])
            except sqlite3.IntegrityError:raise AccountError('用户名或邮箱已经存在。',409) from None
            return self._public(con.execute('SELECT '+PUBLIC+' FROM users WHERE id=?',(cur.lastrowid,)).fetchone())
    def update(self,actor,user_id,payload):
        if type(user_id) is not int or user_id<=0:raise AccountError('用户编号不正确。')
        with self.db(write=True) as con:
            self._admin(con,actor)
            old=con.execute('SELECT '+PUBLIC+' FROM users WHERE id=?',(user_id,)).fetchone()
            if old is None:raise KeyError('not_found')
            data=self._values(payload)
            if data.get('email')=='':
                if not old['email'] or self._is_placeholder_email(old['email']):data.pop('email')
                else:data['email']=self._placeholder_email()
            if data.get('role')=='user' and old['role']=='admin':
                if actor==user_id:raise AccountError('不能移除自己的管理员权限。')
                if con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]<=1:raise AccountError('必须保留至少一个管理员。')
            self._unique(con,data,user_id)
            if data:
                try:
                    con.execute('UPDATE users SET '+','.join(k+'=?' for k in data)+' WHERE id=?',[*data.values(),user_id])
                except sqlite3.IntegrityError:raise AccountError('用户名或邮箱已经存在。',409) from None
            return self._public(con.execute('SELECT '+PUBLIC+' FROM users WHERE id=?',(user_id,)).fetchone())
