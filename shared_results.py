"""Shared result cache: one loader per key, bounded stale fallback, retry cooldown."""
import logging
import copy
import threading
import time
from collections import OrderedDict

_lock = threading.RLock()
_entries = OrderedDict()
_running = set()
_changed = threading.Condition(_lock)


def get(key, ttl, loader, retry=30, stale_for=900):
    with _changed:
        while key in _running:
            _changed.wait(timeout=1)
        now = time.time()
        entry = _entries.get(key)
        if entry and now < entry['expires']:
            return copy.deepcopy(entry['data'])
        if entry and now < entry.get('retry_at', 0):
            return _stale(entry, now, stale_for)
        _running.add(key)
    try:
        data = loader()
        if not data:
            raise ValueError('Empty result')
    except Exception as exc:
        logging.getLogger("amazon_affiliate").warning("Recupero condiviso fallito: %s", type(exc).__name__)
        with _changed:
            entry = _entries.setdefault(key, {'data': [], 'expires': 0})
            entry['retry_at'] = time.time() + retry
            result = _stale(entry, time.time(), stale_for)
            _running.discard(key)
            _trim()
            _changed.notify_all()
        return result
    with _changed:
        _entries[key] = {'data': copy.deepcopy(data), 'expires': time.time()+ttl}
        _entries.move_to_end(key)
        _running.discard(key)
        _trim()
        _changed.notify_all()
    return copy.deepcopy(data)


def _trim():
    while len(_entries) > 256:
        _entries.popitem(last=False)


def _stale(entry, now, stale_for):
    if now > entry['expires'] + stale_for:
        return []
    data = copy.deepcopy(entry['data'])
    for product in data:
        product.update(prezzo_finale=None, prezzo_iniziale=None,
                       prezzo_verificato=False, sconto='', sconto_val=0)
    return data
