import http.client
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from create_https_certificate import create_certificate
from web_tls import tls_options, local_tls_context


class HttpsTests(unittest.TestCase):
    def test_certificate_names_reuse_and_configuration_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOGCOMPARATOR_SSL_CERTFILE': '', 'LOGCOMPARATOR_SSL_KEYFILE': ''}):
            folder = Path(directory)
            certificate, key = create_certificate(folder / 'explicit', ['10.1.110.84'])
            parsed = x509.load_pem_x509_certificate(certificate.read_bytes())
            names = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            self.assertIn(ipaddress.ip_address('10.1.110.84'), names.get_values_for_type(x509.IPAddress))
            self.assertIn(ipaddress.ip_address('127.0.0.1'), names.get_values_for_type(x509.IPAddress))
            self.assertIn('localhost', names.get_values_for_type(x509.DNSName))
            self.assertIn('ssl_keyfile', tls_options(certificate, key))
            with self.assertRaisesRegex(ValueError, 'already exist'):
                create_certificate(folder / 'explicit', ['10.1.110.84'])
            with self.assertRaisesRegex(ValueError, 'requires both'):
                tls_options()
            with self.assertRaisesRegex(ValueError, 'requires both'):
                tls_options(certificate, '')
            _, wrong_key = create_certificate(folder / 'other', ['localhost'])
            with self.assertRaises(ssl.SSLError):
                tls_options(certificate, wrong_key)
            defaults = tls_options(default_folder=folder / 'automatic')
            before = Path(defaults['ssl_keyfile']).read_bytes()
            self.assertEqual(tls_options(default_folder=folder / 'automatic'), defaults)
            self.assertEqual(Path(defaults['ssl_keyfile']).read_bytes(), before)

    def test_https_health_ui_and_plain_http_rejection(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            certificate, key = create_certificate(folder / 'certs', ['127.0.0.1'])
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            env = dict(os.environ, LOGCOMPARATOR_SSL_CERTFILE=str(certificate),
                       LOGCOMPARATOR_SSL_KEYFILE=str(key), LOGCOMPARATOR_CACHE=str(folder / 'cache'),
                       NICEGUI_STORAGE_PATH=str(folder / 'state'))
            env.pop('PYTEST_CURRENT_TEST', None)
            command = [sys.executable, 'main.py', '--no-browser', '--port', str(port)]
            context = ssl.create_default_context(cafile=str(certificate))
            with open(os.devnull, 'w') as log:
                process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    url = f'https://127.0.0.1:{port}'
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        try:
                            with urllib.request.urlopen(url + '/health', context=context, timeout=1) as response:
                                self.assertEqual(json.load(response)['app'], 'LogComparator')
                            break
                        except OSError:
                            if process.poll() is not None:
                                break
                            time.sleep(0.1)
                    else:
                        self.fail('HTTPS startup timed out')
                    if process.poll() is not None:
                        self.fail('HTTPS server exited before becoming ready')
                    with urllib.request.urlopen(url + '/', context=context, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    with urllib.request.urlopen(url + '/readme', context=context, timeout=5) as response:
                        self.assertIn(b'LogComparator', response.read())
                    with patch.dict(os.environ, env, clear=True):
                        from web_tls import check_health
                        self.assertIn(b'LogComparator', check_health(port))
                    with self.assertRaises((OSError, http.client.HTTPException)):
                        urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2)
                    reused = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=20)
                    self.assertEqual(reused.returncode, 0, reused.stderr)
                    self.assertIn('already running at https://', reused.stdout)
                finally:
                    process.terminate()
                    try:
                        process.wait(10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
