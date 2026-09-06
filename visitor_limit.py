"""Atomic rolling-hour browser allowance stored alongside the API budget."""
import time
import api_budget


def check(visitor, limit=10, consume=False):
    conn = api_budget._connect()
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS browser_searches (visitor TEXT, at REAL)')
        conn.execute('CREATE INDEX IF NOT EXISTS browser_search_idx ON browser_searches(visitor, at)')
        conn.execute('CREATE INDEX IF NOT EXISTS browser_search_time ON browser_searches(at)')
        conn.execute('CREATE INDEX IF NOT EXISTS browser_search_time ON browser_searches(at)')
        conn.execute('BEGIN IMMEDIATE')
        now = time.time()
        conn.execute('DELETE FROM browser_searches WHERE at <= ?', (now-3600,))
        rows = conn.execute('SELECT at FROM browser_searches WHERE visitor=? ORDER BY at', (visitor,)).fetchall()
        allowed = len(rows) < limit
        if consume and allowed:
            conn.execute('INSERT INTO browser_searches VALUES (?,?)', (visitor,now))
            rows.append((now,))
        conn.commit()
        return {'allowed': allowed, 'remaining': max(0,limit-len(rows)),
                'retry_at': rows[0][0]+3600 if len(rows)>=limit else 0}
    finally:
        conn.close()
