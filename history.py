"""Histórico persistente de detecções e inclusões."""
import sqlite3
import json
import re
import time


class History:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, playlist TEXT, title TEXT, status TEXT, track_id TEXT, score REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS added (playlist TEXT, track_id TEXT, PRIMARY KEY (playlist, track_id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY, playlist TEXT, title TEXT, dry_run INTEGER, UNIQUE(playlist,title,dry_run))')
        self.db.execute('CREATE TABLE IF NOT EXISTS candidates (playlist TEXT, title TEXT, data TEXT, PRIMARY KEY(playlist,title))')
        self.db.execute('CREATE TABLE IF NOT EXISTS choices (title_key TEXT PRIMARY KEY, title TEXT, track_id TEXT, label TEXT)')
        if 'revision' not in [r[1] for r in self.db.execute('PRAGMA table_info(pending)')]:
            self.db.execute('ALTER TABLE pending ADD COLUMN revision INTEGER NOT NULL DEFAULT 0')
        self.db.execute('CREATE TABLE IF NOT EXISTS runtime (channel TEXT PRIMARY KEY, payload TEXT, updated REAL)')
        if 'enqueued_at' not in [r[1] for r in self.db.execute('PRAGMA table_info(pending)')]:
            self.db.execute('ALTER TABLE pending ADD COLUMN enqueued_at REAL NOT NULL DEFAULT 0')
        self.db.commit()

    def contains(self, playlist, track_id):
        return self.db.execute('SELECT 1 FROM added WHERE playlist=? AND track_id=?', (playlist, track_id)).fetchone() is not None

    def record(self, playlist, title, status, track_id=None, score=None):
        with self.db:
            self.db.execute('INSERT INTO events (playlist,title,status,track_id,score) VALUES (?,?,?,?,?)', (playlist,title,status,track_id,score))
            if status in ('adicionada', 'duplicada') and track_id:
                self.db.execute('INSERT OR IGNORE INTO added VALUES (?,?)', (playlist,track_id))

    def recent(self, limit=20):
        return self.db.execute('SELECT created_at,status,title,track_id,score FROM events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()

    def enqueue(self, playlist, title, dry_run=False):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO pending (playlist,title,dry_run,enqueued_at) VALUES (?,?,?,?)',
                            (playlist, title, int(dry_run),time.time()))

    def next_pending(self, playlist, dry_run=False):
        return self.db.execute('SELECT id,title,revision FROM pending WHERE playlist=? AND dry_run=? ORDER BY id LIMIT 1',
                               (playlist, int(dry_run))).fetchone()

    def finish(self, job_id, revision=None):
        with self.db:
            if revision is None:
                self.db.execute('DELETE FROM pending WHERE id=?', (job_id,))
            else:
                self.db.execute('DELETE FROM pending WHERE id=? AND revision=?', (job_id,revision))

    @staticmethod
    def title_key(title):
        return ' '.join(title.casefold().split())

    def choice(self, title):
        row = self.db.execute('SELECT track_id,label FROM choices WHERE title_key=?', (self.title_key(title),)).fetchone()
        return {'id': row[0], 'label': row[1]} if row else None

    def save_candidates(self, playlist, title, candidates):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO candidates VALUES (?,?,?)', (playlist,title,json.dumps(candidates)))

    def review_items(self):
        rows = self.db.execute("""SELECT e.id,e.playlist,e.title,e.status,c.data FROM events e
            LEFT JOIN candidates c ON c.playlist=e.playlist AND c.title=e.title
            WHERE e.id IN (SELECT max(id) FROM events WHERE status IN
            ('incerta','nao_encontrada','ignorada','erro','adicionada','duplicada','simulacao') GROUP BY playlist,title)
            AND e.status IN ('incerta','nao_encontrada','ignorada','erro') ORDER BY e.id DESC LIMIT 100""").fetchall()
        return [dict(event_id=r[0],playlist=r[1],title=r[2],status=r[3],candidates=json.loads(r[4]) if r[4] else [],
                     choice=self.choice(r[2])) for r in rows]

    def event(self, event_id):
        row = self.db.execute('SELECT playlist,title FROM events WHERE id=?', (event_id,)).fetchone()
        if not row or not row[0]:
            raise ValueError('Registro sem playlist ou não encontrado.')
        return row

    def requeue(self, event_id, dry_run=True, track_id=None, label='', provider='tidal'):
        playlist,title = self.event(event_id)
        if track_id is not None and not re.fullmatch(r'[A-Za-z0-9]{22}' if provider == 'spotify' else r'[0-9]{1,20}', track_id):
            raise ValueError('Informe um ID numérico ou link de faixa válido para o serviço desta rádio.')
        with self.db:
            if track_id:
                self.db.execute('INSERT OR REPLACE INTO choices VALUES (?,?,?,?)',
                                (self.title_key(title),title,track_id,label[:200]))
            self.db.execute('INSERT INTO pending (playlist,title,dry_run,enqueued_at) VALUES (?,?,?,?) ON CONFLICT(playlist,title,dry_run) DO UPDATE SET revision=revision+1',
                            (playlist,title,int(dry_run),time.time()))
            self.db.execute('INSERT INTO events (playlist,title,status,track_id) VALUES (?,?,?,?)',
                            (playlist,title,'escolha_salva' if track_id else 'reprocessamento',track_id))

    def forget(self, title):
        with self.db:
            self.db.execute('DELETE FROM choices WHERE title_key=?', (self.title_key(title),))

    def learned(self):
        return [dict(title=r[0],track_id=r[1],label=r[2]) for r in self.db.execute('SELECT title,track_id,label FROM choices ORDER BY title')]


    def activity(self, channel, status, **details):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?)',
                            (channel,json.dumps(dict(status=status,**details)),time.time()))

    def activities(self):
        return {r[0]:dict(json.loads(r[1]),updated=r[2]) for r in self.db.execute('SELECT channel,payload,updated FROM runtime')}

    def indicators(self):
        counts = dict(self.db.execute("SELECT status,count(*) FROM events WHERE created_at >= datetime('now','-24 hours') GROUP BY status"))
        queues = dict(self.db.execute('SELECT dry_run,count(*) FROM pending GROUP BY dry_run'))
        oldest = self.db.execute('SELECT min(enqueued_at) FROM pending WHERE enqueued_at>0').fetchone()[0]
        return dict(last24=counts, queue_real=queues.get(0,0), queue_dry=queues.get(1,0),
                    oldest_pending=oldest)

    def close(self):
        self.db.close()
