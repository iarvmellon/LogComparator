"""Exercise password SSH, SFTP discovery and actual SCP over loopback."""
import base64
import hashlib
import socket
import time
import stat
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch, Mock

import paramiko

from remote_logs import (RemoteConnection, UnknownHostKey, audit_date,
                         banks_for_audits, download_audits, list_remote_audits, names_for_bank, RemoteAuditJob,
                         list_remote_sources, download_tango_logs, uat_connection, connect, read_remote_files, RemoteSourceWatcher, is_transient_ssh_error, open_sftp)


class RemoteLogsTests(unittest.TestCase):
    def test_historical_source_never_opens_live_connection(self):
        with tempfile.TemporaryDirectory() as folder, patch('remote_logs.connect') as connector, patch('log_core.current_log_date', return_value='2026-10-15'):
            watcher = RemoteSourceWatcher(RemoteConnection('localhost', 'reader', ''), '2026-10-14', folder)
            watcher.thread.join(2)
            self.assertFalse(watcher.thread.is_alive())
            connector.assert_not_called()

    def test_failed_sftp_startup_closes_channel(self):
        client = Mock()
        channel = client.get_transport.return_value.open_session.return_value
        channel.invoke_subsystem.side_effect = TimeoutError('SFTP setup timed out')
        with self.assertRaises(TimeoutError):
            open_sftp(client)
        channel.close.assert_called_once()

    def test_retry_only_transient_transport_errors(self):
        import errno
        for error in (TimeoutError('timed out'), EOFError(), ConnectionResetError(),
                      paramiko.SSHException('connection dropped'), OSError(errno.EHOSTUNREACH, 'unreachable')):
            with self.subTest(error=type(error).__name__):
                self.assertTrue(is_transient_ssh_error(error))
        for error in (UnknownHostKey('SHA256:test'), ValueError('changed host key'),
                      paramiko.AuthenticationException('bad password'), PermissionError(),
                      FileNotFoundError()):
            with self.subTest(error=type(error).__name__):
                self.assertFalse(is_transient_ssh_error(error))
        wrapped = paramiko.ssh_exception.NoValidConnectionsError({('127.0.0.1', 22): TimeoutError()})
        self.assertTrue(is_transient_ssh_error(wrapped))

    def test_uat_defaults_stay_server_side_and_explicit_credentials_override(self):
        from types import SimpleNamespace
        import log_core as core
        settings = SimpleNamespace(user='old-uat-user', sudo_password='test-old-uat-password')
        configured = uat_connection(settings=settings)
        self.assertEqual(configured.endpoint, f'{core.DEFAULT_HOST}:{core.SSH_PORT}')
        self.assertEqual(configured.username, settings.user)
        self.assertEqual(configured.password, settings.sudo_password)
        self.assertEqual(configured.audit_folder, core.REMOTE_AUDIT_DIR)
        self.assertEqual(configured.log_folder, core.REMOTE_LOG_DIR)
        self.assertNotIn(settings.sudo_password, repr(configured))
        with patch('remote_logs.paramiko.SSHClient') as client:
            connect(configured)
            self.assertTrue(client.return_value.connect.call_args.kwargs['allow_agent'])
            self.assertTrue(client.return_value.connect.call_args.kwargs['look_for_keys'])
        overridden = uat_connection('127.0.0.1:2222', 'new-user', 'test-new-password', settings=settings)
        self.assertEqual(overridden.username, 'new-user')
        self.assertEqual(overridden.password, 'test-new-password')
        self.assertFalse(overridden.allow_keys)
        with self.assertRaisesRegex(ValueError, 'explicit password'):
            uat_connection('127.0.0.1:2222', settings=settings)
        with self.assertRaisesRegex(ValueError, 'explicit password'):
            uat_connection(username='another-user', settings=settings)

    @patch('log_core.current_log_date', return_value='2026-10-14')
    def test_password_connection_listing_scp_and_atomic_failure(self, current_day):
        key = paramiko.RSAKey.generate(2048)
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        name = 'audit.OPNBISOBKT01.2026-10-14'
        log_name = 'tango.log.2026-10-14'
        content = b'audit content\n'
        files = {'/remote audit/' + name: content, '/remote log/' + log_name: content}
        reads = []
        fail_reads = set()

        class Handle(paramiko.SFTPHandle):
            def read(self, offset, length):
                reads.append((self.filename, offset, length))
                if self.filename in fail_reads and offset >= 262144:
                    return paramiko.SFTP_FAILURE
                return files[self.filename][offset:offset + length]

        class Listing(paramiko.SFTPServerInterface):
            def stat(self, path):
                if path not in files:
                    return paramiko.SFTP_NO_SUCH_FILE
                result = paramiko.SFTPAttributes()
                result.st_size = len(files[path])
                result.st_mtime = len(files[path])
                result.st_mode = stat.S_IFREG | 0o640
                return result

            def open(self, path, flags, attr):
                if path not in files:
                    return paramiko.SFTP_NO_SUCH_FILE
                result = Handle()
                result.filename = path
                return result

            def list_folder(self, path):
                if path not in ('/remote audit', '/remote log'):
                    return paramiko.SFTP_NO_SUCH_FILE
                result = []
                filenames = [key.rsplit('/', 1)[1] for key in list(files) if key.rsplit('/', 1)[0] == path]
                if path == '/remote audit':
                    filenames += ['ignore.txt', '../audit.OPNBISOBKT01.2026-10-14', 'audit.PTMS01.20261014.gz']
                for filename in filenames:
                    entry = paramiko.SFTPAttributes()
                    entry.filename = filename
                    entry.st_mode = stat.S_IFREG | 0o640
                    entry.st_size = len(content)
                    result.append(entry)
                return result

        class Server(paramiko.ServerInterface):
            def check_auth_password(self, username, password):
                return paramiko.AUTH_SUCCESSFUL if (username, password) == ('reader', 'test-secret') else paramiko.AUTH_FAILED

            def get_allowed_auths(self, username):
                return 'password'

            def check_channel_request(self, kind, channel_id):
                return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

            def check_channel_exec_request(self, channel, command):
                import shlex
                args = shlex.split(command.decode())
                if args not in (['scp', '-f', '/remote audit/' + name], ['scp', '-f', '/remote log/' + log_name]):
                    return False
                requested_name = Path(args[-1]).name

                def send():
                    try:
                        assert channel.recv(1) == b'\0'
                        channel.sendall(f'C0640 {len(content)} {requested_name}\n'.encode())
                        assert channel.recv(1) == b'\0'
                        channel.sendall(content + b'\0')
                        assert channel.recv(1) == b'\0'
                        channel.send_exit_status(0)
                    finally:
                        channel.close()
                threading.Thread(target=send, daemon=True).start()
                return True

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(0.2)
        stopped = threading.Event()
        transports = []

        def serve():
            while not stopped.is_set():
                try:
                    sock, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                transport = paramiko.Transport(sock)
                transports.append(transport)
                transport.add_server_key(key)
                transport.set_subsystem_handler('sftp', paramiko.SFTPServer, Listing)
                try:
                    transport.start_server(server=Server())
                except (EOFError, OSError, paramiko.SSHException):
                    transport.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        settings = RemoteConnection(f'127.0.0.1:{listener.getsockname()[1]}', 'reader', 'test-secret', '/remote audit', log_folder='/remote log')
        try:
            with self.assertRaises(UnknownHostKey) as caught:
                list_remote_audits(settings)
            self.assertEqual(caught.exception.fingerprint, fingerprint)
            trusted = replace(settings, fingerprint=fingerprint)
            names = list_remote_audits(trusted)
            self.assertEqual(names, [name, 'audit.PTMS01.20261014.gz'])
            self.assertEqual(list_remote_sources(trusted), (names, [log_name]))
            self.assertIn('AKTIF/BKT', banks_for_audits(names))
            self.assertIn('AKTIF/BKT', banks_for_audits(['audit.PTMS01.20261014.gz']))
            self.assertEqual(names_for_bank(names, 'AKTIF/BKT'), names)
            self.assertEqual(audit_date(names[-1]), '2026-10-14')
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                download_audits(trusted, [name], target)
                self.assertEqual((target / name).read_bytes(), content)
                with patch('remote_logs.SCPClient.get', side_effect=OSError('interrupted')):
                    with self.assertRaises(OSError):
                        download_audits(trusted, [name], target)
                self.assertEqual((target / name).read_bytes(), content)
                self.assertEqual([p.name for p in target.iterdir()], [name])
                download_tango_logs(trusted, [log_name], target)
                self.assertEqual((target / log_name).read_bytes(), content)
                job = RemoteAuditJob(trusted, [name], target)
                job.thread.join(5)
                self.assertTrue(job.done.is_set())
                self.assertIsNone(job.error)
                self.assertEqual((target / name).read_bytes(), content)
                with self.assertRaises(ValueError):
                    download_audits(trusted, ['../audit.OPN.2026-10-14'], target)
                read_remote_files(trusted, [name], target)
                self.assertEqual((target / name).read_bytes(), content)
                files['/remote audit/' + name] = b'Z' * 300000
                fail_reads.add('/remote audit/' + name)
                with self.assertRaises(OSError):
                    read_remote_files(trusted, [name], target)
                self.assertEqual((target / name).read_bytes(), content)
                self.assertFalse(any(path.name.startswith('.ssh-') for path in target.iterdir()))
                fail_reads.clear()
                files['/remote audit/' + name] = content
                old_name = 'audit.OPNBISOBKT01.2026-10-13'
                files['/remote audit/' + old_name] = b'historical data'
                watcher = RemoteSourceWatcher(trusted, '2026-10-14', target, interval=0.05)
                def wait_for(predicate):
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if predicate():
                            return
                        time.sleep(0.025)
                    self.fail(f'Remote watcher timed out: {watcher.error}')
                def has_bytes(filename, data):
                    try:
                        return (target / filename).read_bytes() == data
                    except (FileNotFoundError, PermissionError):
                        return False
                try:
                    wait_for(lambda: watcher.changed.is_set())
                    watcher.changed.clear()
                    old = b'A' * 4096
                    files['/remote audit/' + name] = old
                    wait_for(lambda: has_bytes(name, old))
                    reads.clear()
                    files['/remote audit/' + name] = old + b'new response\n'
                    wait_for(lambda: has_bytes(name, old + b'new response\n'))
                    self.assertFalse(any(path.endswith(name) and offset == 0 and length > 256 for path, offset, length in reads))
                    files['/remote audit/' + name] = b'truncated\n'
                    wait_for(lambda: has_bytes(name, b'truncated\n'))
                    files['/remote audit/' + name] = b'replaced!\n'
                    wait_for(lambda: has_bytes(name, b'replaced!\n'))
                    rotated = 'audit.OPNBISOBKT02.2026-10-14'
                    files['/remote audit/' + rotated] = b'new bank file\n'
                    wait_for(lambda: has_bytes(rotated, b'new bank file\n'))
                    for transport in list(transports):
                        transport.close()
                    files['/remote audit/' + name] = b'after reconnect\n'
                    wait_for(lambda: has_bytes(name, b'after reconnect\n'))
                    wait_for(lambda: watcher.error is None)
                    self.assertFalse((target / old_name).exists())
                    self.assertFalse(any(path.endswith(old_name) for path, _, _ in reads))
                    current_day.return_value = '2026-10-15'
                    watcher.thread.join(2)
                    self.assertFalse(watcher.thread.is_alive())
                finally:
                    watcher.close()
                    watcher.thread.join(3)
                self.assertFalse(watcher.thread.is_alive())

            with self.assertRaises(ValueError):
                list_remote_audits(replace(trusted, fingerprint='SHA256:wrong'))
            with self.assertRaises(paramiko.AuthenticationException):
                list_remote_audits(replace(trusted, password='wrong'))
            self.assertNotIn('test-secret', repr(settings))
        finally:
            stopped.set()
            listener.close()
            for transport in transports:
                transport.close()
            thread.join(3)


if __name__ == '__main__':
    unittest.main()
