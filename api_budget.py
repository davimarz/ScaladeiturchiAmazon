"""Local shared Creators API budget. Run this file to inspect today's usage."""
from pathlib import Path
import sqlite3
import time
import json
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent / '.runtime' / 'api_usage.sqlite3'

class BudgetUnavailable(RuntimeError):
    pass


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5, isolation_level=None)
    conn.execute('CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY, next_at REAL NOT NULL)')
    return conn


def _day():
    return datetime.now(timezone.utc).date().isoformat()


def usage(limit=800):
    try:
        conn = _connect()
        try:
            row = conn.execute('SELECT calls FROM usage WHERE day=?', (_day(),)).fetchone()
        finally:
            conn.close()
        used = row[0] if row else 0
        return dict(day_utc=_day(), calls=used, limit=limit, remaining=max(0, limit-used))
    except (OSError, sqlite3.Error) as exc:
        raise BudgetUnavailable('Contatore richieste non disponibile') from exc


def reserve(limit=800, interval=1.1, max_wait=5):
    """Count each HTTP attempt before dispatch; fail closed on storage errors."""
    deadline = time.monotonic() + max_wait
    while True:
        try:
            conn = _connect()
            try:
                conn.execute('BEGIN IMMEDIATE')
                day = _day()
                row = conn.execute('SELECT calls FROM usage WHERE day=?', (day,)).fetchone()
                used = row[0] if row else 0
                if used >= limit:
                    raise BudgetUnavailable('Budget giornaliero raggiunto')
                row = conn.execute('SELECT next_at FROM pacing WHERE id=1').fetchone()
                wait = max(0, (row[0] if row else 0) - time.time())
                if wait <= 0:
                    conn.execute('INSERT INTO usage(day,calls) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))
                    conn.execute('INSERT OR REPLACE INTO pacing VALUES (1,?)', (time.time()+interval,))
                    conn.commit()
                    return
                conn.rollback()
            finally:
                conn.close()
        except (OSError, sqlite3.Error) as exc:
            raise BudgetUnavailable('Contatore richieste non disponibile') from exc
        if time.monotonic() + wait > deadline:
            raise BudgetUnavailable('Ricerca occupata, riprova tra qualche secondo')
        time.sleep(min(wait, 0.25))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=800)
    print(json.dumps(usage(parser.parse_args().limit), indent=2))
