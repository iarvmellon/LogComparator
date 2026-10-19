"""SSH source access and live mirrors, with legacy SCP helpers retained."""
from __future__ import annotations

import base64
import hashlib
import re
import stat
import tempfile
import threading
import queue
import shutil
import errno
import socket
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
    log_folder: str = '/opt/tango/MLNPSP01/log'
    allow_keys: bool = False

    def address(self):
        parsed = urlsplit('ssh://' + self.endpoint.strip())
        if not parsed.hostname or parsed.username or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('Enter a remote IP/hostname and optional port, for example 10.0.0.1:22.')
        port = 22 if parsed.port is None else parsed.port
        if not 1 <= port <= 65535 or not self.username.strip():
            raise ValueError('Enter a valid port and username.')
        if any(not folder.startswith('/') or '\x00' in folder for folder in (self.audit_folder, self.log_folder)):
            raise ValueError('Remote log and audit folders must be absolute paths.')
        return parsed.hostname, port


def uat_connection(endpoint='', username='', password='', *, settings=None, fingerprint=''):
    """Reuse the existing UAT configuration without putting its password in HTML."""
    settings = settings or core.RUNTIME_SETTINGS
    configured_endpoint = f'{core.DEFAULT_HOST}:{core.SSH_PORT}'
    connection = RemoteConnection(endpoint or configured_endpoint,
                                  username or settings.user, password or settings.sudo_password,
                                  audit_folder=core.REMOTE_AUDIT_DIR, log_folder=core.REMOTE_LOG_DIR,
                                  fingerprint=fingerprint, allow_keys=not bool(password))
    if not password:
        configured = RemoteConnection(configured_endpoint, settings.user, '')
        if connection.address() != configured.address() or connection.username.strip() != settings.user.strip():
            raise ValueError('Enter an explicit password for a different host, port or username.')
    return connection


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
                       allow_agent=settings.allow_keys, look_for_keys=settings.allow_keys, timeout=30,
                       banner_timeout=60, auth_timeout=60, channel_timeout=60)
        client.get_transport().set_keepalive(15)
        return client
    except Exception:
        client.close()
        raise


def is_transient_ssh_error(error):
    """Retry transport failures, never credentials, permissions or host-key checks."""
    if isinstance(error, (UnknownHostKey, paramiko.AuthenticationException,
                          paramiko.BadHostKeyException, ValueError)):
        return False
    if isinstance(error, paramiko.ssh_exception.NoValidConnectionsError):
        return bool(error.errors) and all(is_transient_ssh_error(item) for item in error.errors.values())
    return (isinstance(error, (TimeoutError, EOFError, ConnectionError, paramiko.SSHException))
            or isinstance(error, OSError) and error.errno in {
                errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED,
                errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH,
                errno.EPIPE, getattr(socket, 'EAI_AGAIN', -3)})


def open_sftp(client):
    """Bound subsystem startup too, before an SFTP client exists to set timeouts."""
    channel = client.get_transport().open_session(timeout=60)
    channel.settimeout(60)
    deadline = threading.Timer(60, channel.close)
    deadline.daemon = True
    deadline.start()
    try:
        channel.invoke_subsystem('sftp')
        return paramiko.SFTPClient(channel)
    except Exception:
        channel.close()
        raise
    finally:
        deadline.cancel()


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


def safe_log_name(name):
    return (PurePosixPath(name).name == name and '\\' not in name
            and not any(ord(c) < 32 for c in name) and core.parse_log_date(name) is not None)


@dataclass(frozen=True)
class RemoteImportRequest:
    connection: RemoteConnection
    audits: list[str]
    logs: list[str]
    selected_date: str
    bank: str
    all_banks: bool = False


def list_remote_sources(settings):
    """Read the same log/audit directories as a local import, over SSH/SFTP."""
    with connect(settings) as client, open_sftp(client) as sftp:
        sftp.get_channel().settimeout(60)
        audits = sorted(entry.filename for entry in sftp.listdir_attr(settings.audit_folder)
                        if stat.S_ISREG(entry.st_mode) and safe_audit_name(entry.filename)
                        and audit_date(entry.filename))
        logs = sorted(entry.filename for entry in sftp.listdir_attr(settings.log_folder)
                      if stat.S_ISREG(entry.st_mode) and safe_log_name(entry.filename))
        return audits, logs


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


def download_audits(settings, names, target, progress=None, cancel_event=None, *, log_files=False):
    """Publish each complete file atomically; never expose partial downloads."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    validator = safe_log_name if log_files else safe_audit_name
    if any(not validator(name) for name in names):
        raise ValueError('Invalid remote source filename.')
    with connect(settings) as client, SCPClient(client.get_transport(), socket_timeout=30) as scp:
        for index, name in enumerate(names):
            if cancel_event and cancel_event.is_set():
                return
            if progress:
                progress(index, len(names), f'Downloading {name}')
            with tempfile.TemporaryDirectory(prefix='.scp-', dir=target) as staging:
                staged = Path(staging) / name
                remote_folder = settings.log_folder if log_files else settings.audit_folder
                scp.get(str(PurePosixPath(remote_folder) / name), str(staged))
                if cancel_event and cancel_event.is_set():
                    return
                staged.replace(target / name)
            if progress:
                progress(index + 1, len(names), f'Downloaded {name}')


def download_tango_logs(settings, names, target, progress=None):
    if names:
        download_audits(settings, names, target, progress, log_files=True)


def read_remote_files(settings, names, target, progress=None, cancel_event=None, *, log_files=False):
    """Initial SSH/SFTP read; publish only complete, bounded snapshots."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    validator = safe_log_name if log_files else safe_audit_name
    if any(not validator(name) for name in names):
        raise ValueError('Invalid remote source filename.')
    with connect(settings) as client, client.open_sftp() as sftp:
        sftp.get_channel().settimeout(30)
        for index, name in enumerate(names):
            if cancel_event and cancel_event.is_set():
                return
            if progress:
                progress(index, len(names), f'Reading {name} over SSH')
            root = settings.log_folder if log_files else settings.audit_folder
            _mirror_file(sftp, str(PurePosixPath(root) / name), target / name, cancel_event)


def read_remote_logs(settings, names, target, progress=None):
    if names:
        read_remote_files(settings, names, target, progress, log_files=True)


def _mirror_file(sftp, remote, local, stop=None, previous=None):
    """Reuse a verified local prefix, reading only appended remote bytes.

    A private staging file prevents the parser from seeing an interrupted read.
    Head/tail checks also detect replacement or truncation across reconnects.
    """
    attrs = sftp.stat(remote)
    size = attrs.st_size
    stamp = (size, attrs.st_mtime)
    with sftp.open(remote, 'rb') as source:
        old_size = local.stat().st_size if local.exists() else 0
        prefix_ok = False
        if local.exists() and old_size <= size:
            with local.open('rb') as cached:
                head = cached.read(min(256, old_size))
                prefix_ok = source.read(len(head)) == head
                offset = max(0, old_size - 256)
                cached.seek(offset)
                source.seek(offset)
                prefix_ok = prefix_ok and source.read(old_size - offset) == cached.read()
        if prefix_ok and old_size == size and previous == stamp:
            return False, stamp
        # A same-size rewrite with a changed mtime needs a complete refresh.
        start = old_size if prefix_ok and old_size < size else 0
        with tempfile.TemporaryDirectory(prefix='.ssh-', dir=local.parent) as staging:
            staged = Path(staging) / local.name
            if start:
                shutil.copyfile(local, staged)
            with staged.open('ab' if start else 'wb') as output:
                source.seek(start)
                remaining = size - start
                while remaining:
                    if stop and stop.is_set():
                        return False, previous
                    chunk = source.read(min(262144, remaining))
                    if not chunk:
                        raise OSError('Remote file changed while reading; retrying')
                    output.write(chunk)
                    remaining -= len(chunk)
            if stop and stop.is_set():
                return False, previous
            staged.replace(local)
    return True, stamp


class RemoteSourceWatcher:
    """Persistent SSH connection, incremental reads and reconnectable discovery."""
    def __init__(self, settings, selected_date, folder, interval=0.5):
        self.settings, self.selected_date = settings, selected_date
        self.folder = Path(folder)
        self.interval = interval
        self.changed = threading.Event()
        self.stop_event = threading.Event()
        self.error = None
        self.client = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        stamps = {}
        while not self.stop_event.is_set() and self.selected_date == core.current_log_date():
            try:
                with connect(self.settings) as client:
                    self.client = client
                    if self.stop_event.is_set():
                        return
                    client.get_transport().set_keepalive(15)
                    with client.open_sftp() as sftp:
                        sftp.get_channel().settimeout(15)
                        while not self.stop_event.is_set() and self.selected_date == core.current_log_date():
                            for root, validator, date_of in (
                                (self.settings.audit_folder, safe_audit_name, audit_date),
                                (self.settings.log_folder, safe_log_name, core.parse_log_date),
                            ):
                                for entry in sftp.listdir_attr(root):
                                    if self.stop_event.is_set() or self.selected_date != core.current_log_date():
                                        return
                                    name = entry.filename
                                    if not stat.S_ISREG(entry.st_mode) or not validator(name) or date_of(name) != self.selected_date:
                                        continue
                                    try:
                                        changed, stamps[name] = _mirror_file(
                                            sftp, str(PurePosixPath(root) / name), self.folder / name,
                                            self.stop_event, stamps.get(name))
                                    except FileNotFoundError:
                                        # Rotation can remove a file between listing and open.
                                        continue
                                    if changed:
                                        self.changed.set()
                                    if self.stop_event.is_set():
                                        return
                            # Keep rotated/deleted files in the local history; new names
                            # are discovered on the next pass without changing the date.
                            self.error = None
                            if self.stop_event.wait(self.interval):
                                return
            except Exception as error:
                if not self.stop_event.is_set():
                    self.error = str(error)
                    self.changed.set()
                    self.stop_event.wait(2)
            finally:
                self.client = None

    def close(self):
        self.stop_event.set()
        if self.client:
            self.client.close()


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
                read_remote_files(settings, names, self.folder,
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
