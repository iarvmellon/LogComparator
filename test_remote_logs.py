"""Exercise password SSH, SFTP discovery and actual SCP over loopback."""
import base64
import hashlib
import socket
import stat
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import paramiko

from remote_logs import (RemoteConnection, UnknownHostKey, audit_date,
                         banks_for_audits, download_audits, list_remote_audits, names_for_bank, RemoteAuditJob)


class RemoteLogsTests(unittest.TestCase):
    def test_password_connection_listing_scp_and_atomic_failure(self):
        key = paramiko.RSAKey.generate(2048)
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        name = 'audit.OPNBISOBKT01.2026-10-14'
        content = b'audit content\n'

        class Listing(paramiko.SFTPServerInterface):
            def list_folder(self, path):
                if path != '/remote audit':
                    return paramiko.SFTP_NO_SUCH_FILE
                result = []
                for filename in [name, 'ignore.txt', '../audit.OPNBISOBKT01.2026-10-14', 'audit.PTMS01.20261014.gz']:
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
                if args != ['scp', '-f', '/remote audit/' + name]:
                    return False

                def send():
                    try:
                        assert channel.recv(1) == b'\0'
                        channel.sendall(f'C0640 {len(content)} {name}\n'.encode())
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
        settings = RemoteConnection(f'127.0.0.1:{listener.getsockname()[1]}', 'reader', 'test-secret', '/remote audit')
        try:
            with self.assertRaises(UnknownHostKey) as caught:
                list_remote_audits(settings)
            self.assertEqual(caught.exception.fingerprint, fingerprint)
            trusted = replace(settings, fingerprint=fingerprint)
            names = list_remote_audits(trusted)
            self.assertEqual(names, [name, 'audit.PTMS01.20261014.gz'])
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
                job = RemoteAuditJob(trusted, [name], target)
                job.thread.join(5)
                self.assertTrue(job.done.is_set())
                self.assertIsNone(job.error)
                self.assertEqual((target / name).read_bytes(), content)
                with self.assertRaises(ValueError):
                    download_audits(trusted, ['../audit.OPN.2026-10-14'], target)
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
