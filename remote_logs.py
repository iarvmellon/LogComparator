"""Password-authenticated SCP imports, independent of the legacy UAT settings."""
from __future__ import annotations

import base64
import hashlib
import re
import stat
import tempfile
import threading
import queue
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import paramiko
from scp import SCPClient

import log_core as core


class UnknownHostKey(ValueError):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__(f'Confirm remote host key: {fingerprint}')


@dataclass(frozen=True)
class RemoteConnection:
    endpoint: str
    username: str
    password: str = field(repr=False)
    audit_folder: str = '/opt/tango/MLNPSP01/audit'
    fingerprint: str = ''

    def address(self):
        parsed = urlsplit('ssh://' + self.endpoint.strip())
        if not parsed.hostname or parsed.username or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('Enter a remote IP/hostname and optional port, for example 10.0.0.1:22.')
        port = 22 if parsed.port is None else parsed.port
        if not 1 <= port <= 65535 or not self.username.strip():
            raise ValueError('Enter a valid port and username.')
        if not self.audit_folder.startswith('/') or '\x00' in self.audit_folder:
            raise ValueError('Enter an absolute remote audit folder.')
        return parsed.hostname, port


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected):
        self.expected = expected

    def missing_host_key(self, client, hostname, key):
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if not self.expected:
            raise UnknownHostKey(fingerprint)
        if fingerprint != self.expected:
            raise ValueError('Remote host key changed; reconnect and verify the new host fingerprint.')


def connect(settings):
    host, port = settings.address()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey(settings.fingerprint))
    try:
        client.connect(host, port=port, username=settings.username.strip(), password=settings.password,
                       allow_agent=False, look_for_keys=False, timeout=15,
                       banner_timeout=15, auth_timeout=15, channel_timeout=30)
        return client
    except Exception:
        client.close()
        raise


def audit_date(name):
    for match in re.finditer(r'(?<!\d)(\d{4}-\d{2}-\d{2}|\d{8})(?!\d)', name):
        value = match.group(1)
        try:
            return datetime.strptime(value, '%Y-%m-%d' if '-' in value else '%Y%m%d').date().isoformat()
        except ValueError:
            continue
    return None


def safe_audit_name(name):
    return (PurePosixPath(name).name == name and '\\' not in name
            and not any(ord(c) < 32 for c in name)
            and name.startswith(('audit.OPN', 'audit.PTMS')))


def list_remote_audits(settings):
    with connect(settings) as client, client.open_sftp() as sftp:
        sftp.get_channel().settimeout(30)
        return sorted(entry.filename for entry in sftp.listdir_attr(settings.audit_folder)
                      if stat.S_ISREG(entry.st_mode) and safe_audit_name(entry.filename)
                      and audit_date(entry.filename))


def banks_for_audits(names):
    codes = {core.source_file_key(Path(name)).split('.')[1] for name in names
             if safe_audit_name(name) and len(name.split('.')) >= 3}
    if not any(code.startswith('OPN') for code in codes) and any(code.startswith('PTMS') for code in codes):
        # Shared SPDH audits have no bank-specific filename: let the user choose
        # a bank and let the existing transaction-level matching do the filtering.
        return list(core.BANK_AUDIT_CODES)
    return [bank for bank in core.BANK_AUDIT_CODES
            if any(core.bank_audit_code_matches(bank, code) for code in codes if code.startswith('OPN'))]


def names_for_bank(names, bank):
    return [name for name in names if name.startswith('audit.PTMS') or bank in banks_for_audits([name])]


def download_audits(settings, names, target, progress=None, cancel_event=None):
    """Publish each complete file atomically; never expose partial downloads."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if any(not safe_audit_name(name) for name in names):
        raise ValueError('Invalid remote audit filename.')
    with connect(settings) as client, SCPClient(client.get_transport(), socket_timeout=30) as scp:
        for index, name in enumerate(names):
            if cancel_event and cancel_event.is_set():
                return
            if progress:
                progress(index, len(names), f'Downloading {name}')
            with tempfile.TemporaryDirectory(prefix='.scp-', dir=target) as staging:
                staged = Path(staging) / name
                scp.get(str(PurePosixPath(settings.audit_folder) / name), str(staged))
                if cancel_event and cancel_event.is_set():
                    return
                staged.replace(target / name)
            if progress:
                progress(index + 1, len(names), f'Downloaded {name}')


class RemoteAuditJob:
    """Fetch the other banks after the requested bank has loaded."""
    def __init__(self, settings, names, folder):
        self.folder = Path(folder).resolve()
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.messages = queue.Queue()
        self.error = None

        def worker():
            try:
                download_audits(settings, names, self.folder,
                                lambda current, total, text: self.messages.put(text), self.cancel_event)
                if not self.cancel_event.is_set():
                    self.messages.put('Background audits ready for all banks')
            except Exception as error:
                self.error = str(error)
                self.messages.put(f'Background download failed: {error}')
            finally:
                self.done.set()
        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()
