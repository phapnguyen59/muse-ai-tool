"""Bounded, thread-safe activity feed. Never record prompts, cookies or media URLs."""
from collections import deque
from threading import Lock
import time
import json
import os
import sys
from pathlib import Path

from core.paths import ACTIVITY_LOG_FILE
_path = Path(os.environ.get('MUSE_LOG_PATH', ACTIVITY_LOG_FILE)).resolve()

_entries = deque(maxlen=500)
_lock = Lock()
_sequence = 0
try:
    _entries.extend(json.loads(_path.read_text(encoding='utf-8'))[-500:])
    _sequence = max((item['id'] for item in _entries), default=0)
except (OSError, ValueError, TypeError, KeyError):
    _entries.clear()


def record(message, job_id='', level='info'):
    global _sequence
    with _lock:
        _sequence += 1
        _entries.append(dict(id=_sequence, time=time.time(), jobId=job_id,
                             level=level, message=message))
        try:
            _path.parent.mkdir(parents=True, exist_ok=True)
            temp = _path.with_suffix('.tmp')
            temp.write_text(json.dumps(list(_entries), ensure_ascii=False), encoding='utf-8')
            temp.replace(_path)
        except OSError:
            pass


def snapshot(limit=100):
    with _lock:
        items = list(_entries)
    return items[-limit:]


def clear():
    global _sequence
    with _lock:
        _entries.clear()
        try:
            _path.parent.mkdir(parents=True, exist_ok=True)
            temp = _path.with_suffix('.tmp')
            temp.write_text('[]', encoding='utf-8')
            temp.replace(_path)
        except OSError:
            pass
