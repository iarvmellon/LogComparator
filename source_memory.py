"""Process-local, immutable SSH archive snapshots; source contents never touch disk."""
import io
import time
from pathlib import Path
from types import SimpleNamespace
from threading import RLock

_LOCK = RLock()
_GROUPS = {}

def key(path):
    return str(Path(path).resolve())

def publish(archive, files):
    stamp = time.time_ns()
    with _LOCK:
        _GROUPS[key(archive)] = {key(path): (data, stamp) for path, data in files.items()}

def snapshot(path):
    name = key(path)
    with _LOCK:
        for group in reversed(list(_GROUPS.values())):
            if name in group:
                return group[name]
    return None

def paths(folder):
    parent = Path(folder).resolve()
    with _LOCK:
        return [Path(name) for group in _GROUPS.values() for name in group if Path(name).parent == parent]

def list_paths(folder):
    return sorted(set(Path(folder).iterdir()) | set(paths(folder)))

def is_file(path):
    return snapshot(path) is not None or Path(path).is_file()

def stat(path):
    item = snapshot(path)
    if item is None:
        return Path(path).stat()
    data, stamp = item
    return SimpleNamespace(st_size=len(data), st_mtime_ns=stamp, st_ctime_ns=stamp, st_ino=0)

def open_source(path, mode='rb', encoding='utf-8', errors='replace'):
    item = snapshot(path)
    if item is None:
        return open(path, mode) if 'b' in mode else open(path, mode, encoding=encoding, errors=errors)
    stream = io.BytesIO(item[0])
    return stream if 'b' in mode else io.TextIOWrapper(stream, encoding=encoding, errors=errors)
