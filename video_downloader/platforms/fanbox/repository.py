"""Transactional archive index and durable work, scheduler and traffic ledger.

All workers in an archive share one conservative credential slot. Session
rotation must not reset limits. No authentication material is stored here.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time as day_time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .errors import FanboxError


class Repository:
    VERSION = 4

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > self.VERSION:
                raise FanboxError('database_version', '归档数据库来自更高版本')
            if version == 0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise FanboxError('database_version', '无法识别归档数据库结构')
                db.executescript('''
                    BEGIN IMMEDIATE;
                    CREATE TABLE jobs(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                        status TEXT NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL);
                    CREATE TABLE assets(key TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                        state TEXT NOT NULL);
                    CREATE TABLE lanes(kind TEXT PRIMARY KEY, next REAL NOT NULL DEFAULT 0);
                    CREATE TABLE leases(token TEXT PRIMARY KEY, kind TEXT NOT NULL,
                        expires REAL NOT NULL, held INTEGER NOT NULL DEFAULT 0, capacity INTEGER NOT NULL DEFAULT 1);
                    CREATE TABLE traffic(bucket INTEGER PRIMARY KEY, bytes INTEGER NOT NULL);
                    CREATE TABLE cooldown(id INTEGER PRIMARY KEY CHECK(id=1), until REAL NOT NULL);
                    INSERT INTO cooldown VALUES(1,0);
                    PRAGMA user_version=1;
                    COMMIT;
                ''')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            try:
                if db.execute('PRAGMA user_version').fetchone()[0]==1:
                    if version==1:
                        backup=self.path.with_suffix(self.path.suffix+'.v1.bak')
                        if backup.exists() or backup.is_symlink():
                            backup=self.path.with_suffix(self.path.suffix+'.v1.'+uuid.uuid4().hex+'.bak')
                        with sqlite3.connect(self.path) as source,sqlite3.connect(backup) as target:
                            source.backup(target)
                    db.execute('CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, job TEXT NOT NULL)')
                    db.execute('PRAGMA user_version=2')
                if db.execute('PRAGMA user_version').fetchone()[0]==2:
                    if version==2:
                        backup=self.path.with_suffix(self.path.suffix+'.v2.bak')
                        if backup.exists() or backup.is_symlink():backup=self.path.with_suffix('.v2.'+uuid.uuid4().hex+'.bak')
                        with sqlite3.connect(self.path) as source,sqlite3.connect(backup) as target:source.backup(target)
                    db.execute('CREATE TABLE url_records(path TEXT PRIMARY KEY, origin TEXT NOT NULL)')
                    db.execute('CREATE TABLE success_traffic(bucket INTEGER PRIMARY KEY, bytes INTEGER NOT NULL)')
                    db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                    db.execute("INSERT INTO metadata VALUES('success_since',?)",(str(self.clock()),))
                    db.execute("CREATE INDEX jobs_source ON jobs(json_extract(state,'$.source'))")
                    db.execute('PRAGMA user_version=3')
                if db.execute('PRAGMA user_version').fetchone()[0]==3:
                    if version==3:
                        backup=self.path.with_suffix(self.path.suffix+'.v3.bak')
                        if backup.exists() or backup.is_symlink():backup=self.path.with_suffix('.v3.'+uuid.uuid4().hex+'.bak')
                        with sqlite3.connect(self.path) as source,sqlite3.connect(backup) as target:source.backup(target)
                    db.execute('CREATE TABLE verifications(job TEXT PRIMARY KEY, state TEXT NOT NULL)')
                    db.execute('PRAGMA user_version=4')
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def save_job(self, state, *, lease_token=None):
        with self.transaction() as db:
            if lease_token is not None:
                now=self.clock()
                if not db.execute('UPDATE leases SET expires=? WHERE token=? AND kind=? AND expires>?',
                                  (now+120,lease_token,'job:'+state['id'],now)).rowcount:
                    raise FanboxError('lease_expired','工作租约已失效，请继续任务')
            previous = db.execute('SELECT version FROM jobs WHERE id=?', (state['id'],)).fetchone()
            state['version'] = (previous['version'] if previous else 0) + 1
            state['updated_at'] = self.clock()
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',
                       (state['id'], state['version'], state['status'], state['updated_at'],
                        json.dumps(state, ensure_ascii=False)))

    def save_terminal_job(self,state,token):
        """Persist a stopped worker without renewing or overwriting a new owner."""
        with self.transaction() as db:
            previous=db.execute('SELECT version FROM jobs WHERE id=?',(state['id'],)).fetchone()
            if previous is None or previous['version']!=state['version']:
                return False
            if db.execute('SELECT 1 FROM leases WHERE kind=? AND token<>? AND expires>?',
                          ('job:'+state['id'],token,self.clock())).fetchone():
                return False
            state['version']+=1;state['updated_at']=self.clock()
            db.execute('UPDATE jobs SET version=?,status=?,updated=?,state=? WHERE id=?',
                       (state['version'],state['status'],state['updated_at'],json.dumps(state,ensure_ascii=False),state['id']))
            return True

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()
            return json.loads(row['state']) if row else None

    def create_requested(self,state,key,fingerprint):
        with self.transaction() as db:
            old=db.execute('SELECT fingerprint,job FROM requests WHERE key=?',(key,)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:
                    raise FanboxError('request_conflict','重复请求标识对应了不同参数')
                return json.loads(db.execute('SELECT state FROM jobs WHERE id=?',(old['job'],)).fetchone()[0]),False
            state['version']=1;state['updated_at']=self.clock()
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(state['id'],1,state['status'],state['updated_at'],json.dumps(state,ensure_ascii=False)))
            db.execute('INSERT INTO requests VALUES(?,?,?)',(key,fingerprint,state['id']))
            return state,True

    def transition(self,state,expected):
        with self.transaction() as db:
            old=db.execute('SELECT version FROM jobs WHERE id=?',(state['id'],)).fetchone()
            if old is None or old[0]!=expected:
                raise FanboxError('stale_version','任务版本已改变，请刷新后重试')
            if db.execute('SELECT 1 FROM leases WHERE kind=? AND expires>?',('job:'+state['id'],self.clock())).fetchone():
                raise FanboxError('job_busy','任务仍在运行或收尾')
            state['version']=expected+1;state['updated_at']=self.clock()
            db.execute('UPDATE jobs SET version=?,status=?,updated=?,state=? WHERE id=?',
                       (state['version'],state['status'],state['updated_at'],json.dumps(state,ensure_ascii=False),state['id']))

    def has_lease(self,kind):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM leases WHERE kind=? AND expires>?',(kind,self.clock())).fetchone() is not None

    def jobs(self, limit=100):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT state FROM jobs ORDER BY updated DESC LIMIT ?', (limit,))]

    def summaries(self,source=None,limit=100,job_id=None):
        keys=('id','source','status','version','created_at','updated_at','counts','error','scope','output','phase','outcome','resume_after')
        expression=','.join("'"+key+"',json_extract(j.state,'$."+key+"')" for key in keys)
        query="SELECT json_object("+expression+",'notify',json_extract(j.state,'$.options.notifications.on_complete'),'verification',json_remove(v.state,'$.issues')) FROM jobs j LEFT JOIN verifications v ON v.job=j.id"
        args=[];conditions=[]
        if source is not None:conditions.append("json_extract(j.state,'$.source')=?");args.append(source)
        if job_id is not None:conditions.append('j.id=?');args.append(job_id)
        if conditions:query+=' WHERE '+' AND '.join(conditions)
        query+=' ORDER BY j.updated DESC LIMIT ?';args.append(limit)
        with self.connect() as db:
            values=[json.loads(row[0]) for row in db.execute(query,args)]
        for value in values:
            value['notify']=bool(value['notify'])
            report=value.get('verification')
            if report and report['job_version']!=value['version']:report['status']='stale'
        return values

    def verification(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT state FROM verifications WHERE job=?',(job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def save_verification(self,job_id,report):
        with self.transaction() as db:
            previous=db.execute("SELECT json_extract(state,'$.version') FROM verifications WHERE job=?",(job_id,)).fetchone()
            report['version']=(previous[0] if previous else 0)+1
            db.execute('INSERT OR REPLACE INTO verifications VALUES(?,?)',(job_id,json.dumps(report,ensure_ascii=False)))

    def allocate(self, key, candidate, *, conflict='uniquify', exists=lambda p: False, repair_extension=False):
        """Freeze paths in SQL before IO; never steal another asset's filename."""
        with self.transaction() as db:
            old = db.execute('SELECT path FROM assets WHERE key=?', (key,)).fetchone()
            if old:
                if not repair_extension or Path(old['path']).suffix.lower()==Path(candidate).suffix.lower():
                    return old['path']
                candidate=Path(old['path']).with_suffix(Path(candidate).suffix).as_posix()
            path = Path(candidate)
            for number in range(10000):
                name = path if not number else path.with_name(f'{path.stem} ({number}){path.suffix}')
                taken = db.execute('SELECT key FROM assets WHERE path=? COLLATE NOCASE', (name.as_posix(),)).fetchone()
                occupied = exists(name.as_posix())
                if taken or (occupied and conflict == 'uniquify'):
                    continue
                if occupied and conflict=='skip':
                    raise FanboxError('file_skipped','已按冲突策略跳过现有文件')
                if occupied and conflict=='prompt':
                    raise FanboxError('conflict_required', '目标文件已存在，请调整冲突策略')
                if old:
                    db.execute('UPDATE assets SET path=?,state=? WHERE key=?', (name.as_posix(),'{}',key))
                else:
                    db.execute('INSERT INTO assets VALUES(?,?,?)', (key, name.as_posix(), '{}'))
                return name.as_posix()
            raise FanboxError('path_conflict', '无法分配唯一文件名')

    def asset(self, key):
        with self.connect() as db:
            row = db.execute('SELECT path,state FROM assets WHERE key=?', (key,)).fetchone()
            return dict(json.loads(row['state']), path=row['path']) if row else None

    def save_asset(self, key, state):
        with self.transaction() as db:
            db.execute('UPDATE assets SET state=? WHERE key=?', (json.dumps(state), key))
            if state.get('status')=='completed':
                if state.get('resource_path'):
                    db.execute("INSERT OR REPLACE INTO url_records VALUES(?,'downloaded')",(state['resource_path'],))
                if type(state.get('size')) is int and state['size']>=0:
                    db.execute('INSERT INTO success_traffic VALUES(?,?) ON CONFLICT(bucket) DO UPDATE SET bytes=bytes+excluded.bytes',
                               (int(self.clock()//60),state['size']))

    def url_records(self):
        with self.connect() as db:return [dict(row) for row in db.execute('SELECT path,origin FROM url_records ORDER BY path')]

    def import_url_records(self,paths):
        with self.transaction() as db:
            before=db.total_changes
            db.executemany("INSERT OR IGNORE INTO url_records VALUES(?,'imported')",((path,) for path in paths))
            return db.total_changes-before

    def clear_url_records(self):
        with self.transaction() as db:return db.execute('DELETE FROM url_records').rowcount

    def record_stats(self):
        with self.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM url_records').fetchone()[0]
            imported=db.execute("SELECT COUNT(*) FROM url_records WHERE origin='imported'").fetchone()[0]
            verified=db.execute("SELECT COUNT(*) FROM assets WHERE json_extract(state,'$.status')='completed'").fetchone()[0]
        return {'urls':count,'imported':imported,'verified':verified}

    def imported_hints(self,paths):
        result=set()
        with self.connect() as db:
            for offset in range(0,len(paths),500):
                chunk=paths[offset:offset+500]
                result.update(row[0] for row in db.execute("SELECT path FROM url_records WHERE origin='imported' AND path IN ("+
                              ','.join('?' for _ in chunk)+')',chunk))
        return result

    def acquire(self, kind, *, limit=1, interval=0, ttl=120):
        now, token = self.clock(), uuid.uuid4().hex
        with self.transaction() as db:
            db.execute('DELETE FROM leases WHERE expires<=?', (now,))
            until = db.execute('SELECT until FROM cooldown WHERE id=1').fetchone()[0] if kind in {'api','file'} else 0
            lane = db.execute('SELECT next FROM lanes WHERE kind=?', (kind,)).fetchone()
            wait = max(0, until-now, (lane[0]-now) if lane else 0)
            occupied = db.execute('SELECT COUNT(*),MIN(capacity) FROM leases WHERE kind=?', (kind,)).fetchone()
            effective = min(limit,occupied[1]) if occupied[1] is not None else limit
            if wait or occupied[0] >= effective:
                return None, max(.05, wait)
            db.execute('INSERT INTO leases VALUES(?,?,?,0,?)', (token, kind, now+ttl,limit))
            db.execute('INSERT OR REPLACE INTO lanes VALUES(?,?)', (kind, now+interval))
        return token, 0

    def release(self, token, *, interval=0):
        with self.transaction() as db:
            row = db.execute('SELECT kind FROM leases WHERE token=?', (token,)).fetchone()
            if row and interval:
                db.execute('UPDATE lanes SET next=MAX(next,?) WHERE kind=?', (self.clock()+interval, row[0]))
            db.execute('DELETE FROM leases WHERE token=?', (token,))

    def heartbeat(self, token):
        with self.transaction() as db:
            if not db.execute('UPDATE leases SET expires=? WHERE token=? AND expires>?',
                              (self.clock()+120, token, self.clock())).rowcount:
                raise FanboxError('lease_expired', '工作租约已失效，请继续任务')

    def defer(self, seconds):
        with self.transaction() as db:
            db.execute('UPDATE cooldown SET until=MAX(until,?) WHERE id=1', (self.clock()+seconds,))

    def cooldown_remaining(self):
        with self.connect() as db:
            return max(0,db.execute('SELECT until FROM cooldown WHERE id=1').fetchone()[0]-self.clock())

    @staticmethod
    def _day(now, zone):
        current = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(zone))
        start = datetime.combine(current.date(), day_time(), current.tzinfo)
        return int(start.timestamp()//60), int((start+timedelta(days=1)).timestamp()//60)

    def _usage(self, db, zone):
        start, end = self._day(self.clock(), zone)
        return db.execute('SELECT COALESCE(SUM(bytes),0) FROM traffic WHERE bucket>=? AND bucket<?', (start,end)).fetchone()[0]

    def reserve(self, token, quota, expected):
        with self.transaction() as db:
            db.execute('DELETE FROM leases WHERE expires<=?', (self.clock(),))
            row = db.execute('SELECT held FROM leases WHERE token=?', (token,)).fetchone()
            if row is None:
                raise FanboxError('lease_expired', '下载租约已失效')
            if not quota['enabled']:
                return None
            used = self._usage(db, quota['timezone'])
            held = db.execute('SELECT COALESCE(SUM(held),0) FROM leases WHERE token<>?', (token,)).fetchone()[0]
            available = int(quota['limit_gib']*1024**3)-used-held
            wanted = available if expected is None else expected
            if wanted < 0 or wanted > available or (wanted == 0 and expected is None):
                code = 'quota_busy' if held and wanted <= available+held else 'quota_exceeded'
                raise FanboxError(code, '当日下载额度不足' if code=='quota_exceeded' else '下载额度正在使用')
            db.execute('UPDATE leases SET held=? WHERE token=?', (wanted,token))
            return wanted

    def charge(self, token, count):
        with self.transaction() as db:
            # Received payload is counted even when its contents fail validation.
            db.execute('INSERT INTO traffic VALUES(?,?) ON CONFLICT(bucket) DO UPDATE SET bytes=bytes+excluded.bytes',
                       (int(self.clock()//60),count))
            db.execute('UPDATE leases SET held=MAX(0,held-?),expires=? WHERE token=?', (count,self.clock()+120,token))

    def usage(self, zone):
        with self.connect() as db:
            return self._usage(db, zone)

    def usage_history(self,zone,days=30):
        tz=ZoneInfo(zone)
        today=datetime.fromtimestamp(self.clock(),timezone.utc).astimezone(tz).date()
        totals={str(today-timedelta(days=i)):{'bytes':0,'completed_bytes':0} for i in reversed(range(days))}
        with self.connect() as db:
            since=float(db.execute("SELECT value FROM metadata WHERE key='success_since'").fetchone()[0])
            first_day=str(datetime.fromtimestamp(since,timezone.utc).astimezone(tz).date())
            for date in totals:
                if date<first_day:totals[date]['completed_bytes']=None
            for table,key in [('traffic','bytes'),('success_traffic','completed_bytes')]:
                for row in db.execute('SELECT bucket,bytes FROM '+table+' WHERE bucket>=?',(int((self.clock()-days*86400)//60),)):
                    date=str(datetime.fromtimestamp(row['bucket']*60,timezone.utc).astimezone(tz).date())
                    if date in totals and totals[date][key] is not None:totals[date][key]+=row['bytes']
        return [{'date':date,**counts} for date,counts in totals.items()]
