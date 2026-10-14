"""Устойчивое состояние и аудит."""

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA busy_timeout=10000;
            CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, at TEXT, actor TEXT, role TEXT,
                tenant TEXT, project TEXT, action TEXT, detail TEXT, prev TEXT, hash TEXT);
        ''')

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.db.in_transaction:
                yield self.db
                return
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield self.db
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def get(self, kind, key):
        with self.lock:
            row = self.db.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
            return json.loads(row['data']) if row else None

    def list(self, kind, status=None):
        with self.lock:
            query = 'SELECT data FROM records WHERE kind=?'
            params = [kind]
            if status is not None:
                query += " AND json_extract(data,'$.status')=?"
                params.append(status)
            return [json.loads(r['data']) for r in self.db.execute(query + ' ORDER BY id', params)]

    def put(self, kind, item):
        with self.transaction() as con:
            con.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)', (kind, item['id'], packed(item)))
        return item

    def update(self, kind, key, fn):
        with self.transaction() as con:
            row = con.execute('SELECT data FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
            if not row:
                raise KeyError(key)
            value = fn(json.loads(row['data']))
            con.execute('UPDATE records SET data=? WHERE kind=? AND id=?', (packed(value), kind, key))
            return value

    def audit(self, actor, role, tenant, project, action, detail):
        with self.transaction() as con:
            previous = con.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
            row = {'at': now(), 'actor': actor, 'role': role, 'tenant': tenant, 'project': project,
                   'action': action, 'detail': detail, 'prev': previous['hash'] if previous else '0' * 64}
            digest = hashlib.sha256(packed(row).encode()).hexdigest()
            con.execute('INSERT INTO audit(at,actor,role,tenant,project,action,detail,prev,hash) VALUES(?,?,?,?,?,?,?,?,?)',
                        (row['at'], actor, role, tenant, project, action, packed(detail), row['prev'], digest))

    def events(self):
        with self.lock:
            rows = [dict(r) for r in self.db.execute('SELECT * FROM audit ORDER BY seq')]
        for row in rows:
            row['detail'] = json.loads(row['detail'])
        return rows

    def verify_audit(self):
        previous = '0' * 64
        rows = self.events()
        for row in rows:
            data = {k: v for k, v in row.items() if k not in ('seq', 'hash')}
            if row['prev'] != previous or hashlib.sha256(packed(data).encode()).hexdigest() != row['hash']:
                return {'valid': False, 'broken_at': row['seq'], 'events': len(rows)}
            previous = row['hash']
        return {'valid': True, 'events': len(rows), 'head': previous}

    def backup(self, path):
        with self.lock, sqlite3.connect(str(path)) as target:
            self.db.backup(target)

    def close(self):
        with self.lock:
            self.db.close()
