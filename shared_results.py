"""Shared result cache: one loader per key, bounded stale fallback, retry cooldown."""
import logging
import copy
import threading
import time
from collections import OrderedDict

class RetryPending(Exception):
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__("Recupero temporaneamente non disponibile")


def retry_at(key):
    with _lock:
        return _entries.get(key, {}).get("retry_at", 0)


class EmptyResult(Exception):
    pass


_lock = threading.RLock()
_entries = OrderedDict()
_running = set()
_changed = threading.Condition(_lock)


def get(key, ttl, loader, retry=30, stale_for=900, report_failure=False):
    with _changed:
        wait_until = time.monotonic() + 20
        while key in _running:
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                entry = _entries.get(key)
                if report_failure:
                    raise RetryPending(time.time() + 1)
                return _stale(entry, time.time(), stale_for) if entry else []
            _changed.wait(timeout=min(1, remaining))
        now = time.time()
        entry = _entries.get(key)
        if entry and now < entry['expires']:
            return copy.deepcopy(entry['data'])
        if entry and now < entry.get('retry_at', 0):
            if report_failure:
                raise RetryPending(entry['retry_at'])
            return _stale(entry, now, stale_for)
        _running.add(key)
    try:
        data = loader()
        if not data:
            raise EmptyResult()
    except BaseException as exc:
        if not isinstance(exc, Exception):
            with _changed:
                _running.discard(key)
                _changed.notify_all()
            raise
        logger = logging.getLogger("amazon_affiliate")
        if isinstance(exc, EmptyResult):
            logger.info("Cache: nessun prodotto utilizzabile; nuovo tentativo consentito tra %ss", retry)
        else:
            logger.warning("Cache: recupero fallito error_type=%s retry_seconds=%s", type(exc).__name__, retry)
        with _changed:
            entry = _entries.setdefault(key, {'data': [], 'expires': 0})
            entry['retry_at'] = time.time() + retry
            result = _stale(entry, time.time(), stale_for)
            _running.discard(key)
            _trim()
            _changed.notify_all()
        if report_failure:
            raise RetryPending(entry["retry_at"]) from exc
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
        for offer in [product] + list(product.get("variants", [])):
            offer.update(prezzo_finale=None, prezzo_iniziale=None,
                         prezzo_verificato=False, sconto='', sconto_val=0)
    return data
