"""Local-only, atomic backup versions and forward-only signal observations.

No credentials are stored here. SQLite lives outside the install directory so
replacing the application does not remove backups or the evaluation journal.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

MODEL_VERSION = 'intraday-v6.1'
ALLOWED_KEY = re.compile(r'^(pf_[\w-]+|watchlist|search_history|stock_notes[\w-]*|ticker_bar[\w-]*|mi_[\w-]+)$')
SECRET_KEY = re.compile(r'(apikey|api_key|secret|token|password|backup_profile)', re.I)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def data_directory():
    override = os.environ.get('MARKETINTEL_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'MarketIntel'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'MarketIntel'


def validate_snapshot(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('localStorage'), dict):
        raise ValueError('La copia debe contener localStorage como objeto.')
    values = payload['localStorage']
    if len(values) > 2000:
        raise ValueError('Demasiadas entradas en la copia.')
    for key, value in values.items():
        if not ALLOWED_KEY.fullmatch(key) or SECRET_KEY.search(key):
            raise ValueError('La copia contiene una clave no permitida o privada.')
        if not isinstance(value, str) or len(value) > 4_000_000:
            raise ValueError('Valor de respaldo inválido o demasiado grande.')
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(canonical.encode('utf8')) > 8_000_000:
        raise ValueError('La copia supera 8 MB.')
    return canonical


class LocalStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else data_directory()

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.directory / 'marketintel.sqlite3', timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
          CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY, profile TEXT NOT NULL, created_at TEXT NOT NULL,
            reason TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS backup_profile ON backups(profile, id);
          CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY, model TEXT NOT NULL, day TEXT NOT NULL,
            bucket INTEGER NOT NULL, recorded_at TEXT NOT NULL, data_at TEXT NOT NULL,
            score REAL NOT NULL, label TEXT NOT NULL, reference REAL NOT NULL,
            close_price REAL, return_pct REAL, actual TEXT, hit INTEGER,
            UNIQUE(model, day, bucket));
        ''')
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_backup(self, payload, profile, reason='automatic'):
        if not isinstance(profile, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', profile):
            raise ValueError('Identificador del navegador inválido.')
        canonical = validate_snapshot(payload)
        if not json.loads(canonical):
            return {'status': 'empty', 'id': None, 'message': 'Sin datos para respaldar.'}
        digest = hashlib.sha256(canonical.encode('utf8')).hexdigest()
        reason = reason if reason in ('automatic', 'manual', 'before-import', 'before-restore', 'before-delete') else 'manual'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT id, digest, created_at FROM backups WHERE profile=? ORDER BY id DESC LIMIT 1', (profile,)).fetchone()
            if prior and prior['digest'] == digest and reason == 'automatic':
                return {'status': 'unchanged', 'id': prior['id'], 'created_at': prior['created_at']}
            stamp = utc_now()
            cursor = db.execute('INSERT INTO backups(profile,created_at,reason,digest,payload) VALUES(?,?,?,?,?)', (profile, stamp, reason, digest, canonical))
            return {'status': 'saved', 'id': cursor.lastrowid, 'created_at': stamp}

    def list_backups(self, before_id=None):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,profile,created_at,reason,length(payload) AS size_bytes FROM backups WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT 100', (before_id, before_id))]

    def read_backup(self, backup_id):
        with self.connect() as db:
            row = db.execute('SELECT created_at,payload FROM backups WHERE id=?', (backup_id,)).fetchone()
        if not row:
            raise LookupError('No existe esa copia.')
        return {'version': 2, 'exported_at': row['created_at'], 'localStorage': json.loads(row['payload'])}

    def record_signal(self, pulse):
        intraday, session = pulse['intraday'], pulse['session']
        elapsed = session.get('elapsed_minutes', -1)
        if (not session.get('is_open') or intraday.get('status') != 'ok'
                or intraday.get('score') is None or elapsed < 5
                or session.get('remaining_minutes', 0) < 45):
            return
        # One immutable observation per half-hour window, not every refresh.
        bucket = int(elapsed // 30)
        if elapsed % 30 > 10:
            return
        quote = pulse['quotes'].get('SPY', {})
        reference = quote.get('price')
        if not reference or not quote.get('usable'):
            return
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO signals(model,day,bucket,recorded_at,data_at,score,label,reference) VALUES(?,?,?,?,?,?,?,?)',
                       (MODEL_VERSION, session['date'], bucket, utc_now(), quote['data_at'], intraday['score'], intraday['label'], reference))

    def settle_signals(self, completed_closes):
        # Caller supplies completed sessions only; never use a partial daily bar.
        with self.connect() as db:
            rows = db.execute('SELECT * FROM signals WHERE close_price IS NULL AND model=?', (MODEL_VERSION,)).fetchall()
            for row in rows:
                close = completed_closes.get(row['day'])
                if not close or close <= 0:
                    continue
                change = (close / row['reference'] - 1) * 100
                actual = 'alcista' if change > 0.1 else 'bajista' if change < -0.1 else 'mixto'
                predicted = 'alcista' if row['score'] >= 60 else 'bajista' if row['score'] <= 40 else 'mixto'
                hit = None if predicted == 'mixto' else int(predicted == actual)
                db.execute('UPDATE signals SET close_price=?,return_pct=?,actual=?,hit=? WHERE id=? AND close_price IS NULL',
                           (close, round(change, 5), actual, hit, row['id']))

    def signal_history(self, complete=False):
        with self.connect() as db:
            aggregate = dict(db.execute('SELECT count(*) AS total, count(close_price) AS evaluated, count(DISTINCT CASE WHEN close_price IS NOT NULL THEN day END) AS days, count(hit) AS directional, sum(hit) AS hits FROM signals WHERE model=?', (MODEL_VERSION,)).fetchone())
            query = 'SELECT * FROM signals WHERE model=? ORDER BY id DESC'
            rows = [dict(row) for row in db.execute(query + ('' if complete else ' LIMIT 100'), (MODEL_VERSION,))]
        aggregate['hit_rate'] = round(aggregate['hits'] / aggregate['directional'] * 100, 1) if aggregate['directional'] else None
        return {'model': MODEL_VERSION, 'summary': aggregate, 'observations': rows,
                'method': 'SPY desde el precio registrado hasta el cierre de esa sesión. Zona neutral ±0.10%. Lecturas mixtas no cuentan como pronósticos direccionales. Observaciones del mismo día están correlacionadas. No incluye costos ni representa rentabilidad o probabilidad futura.'}
