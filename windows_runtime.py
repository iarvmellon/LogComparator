"""Provide file-backed standard streams for the windowless Windows build."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def configure_standard_streams():
    if sys.stdout is not None and sys.stderr is not None:
        return None
    folder = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'LogComparator'
    try:
        folder.mkdir(parents=True, exist_ok=True)
        stream = (folder / 'LogComparator.log').open('a', encoding='utf-8', buffering=1)
    except OSError:
        stream = open(os.devnull, 'w', encoding='utf-8')
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    if sys.stdin is None:
        sys.stdin = open(os.devnull, 'r', encoding='utf-8')
    return stream
