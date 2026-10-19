"""TLS configuration and the container health check."""
import os
import ssl
import urllib.request
from pathlib import Path


def tls_options(certfile=None, keyfile=None, *, default_folder=None):
    certfile = certfile if certfile is not None else os.environ.get('LOGCOMPARATOR_SSL_CERTFILE', '')
    keyfile = keyfile if keyfile is not None else os.environ.get('LOGCOMPARATOR_SSL_KEYFILE', '')
    if not certfile and not keyfile and default_folder is not None:
        from create_https_certificate import create_certificate
        import socket
        folder = Path(default_folder)
        certfile, keyfile = folder / 'server.crt', folder / 'server.key'
        if not certfile.exists() and not keyfile.exists():
            create_certificate(folder, [socket.gethostname(), 'localhost', '127.0.0.1'])
    if not certfile or not keyfile:
        raise ValueError('HTTPS requires both a certificate file and a private key file.')
    cert, key = Path(certfile).expanduser().resolve(), Path(keyfile).expanduser().resolve()
    if not cert.is_file() or not key.is_file():
        raise ValueError('HTTPS certificate or private key file was not found.')
    # Validate the pair before starting the server or probing an existing instance.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    return dict(ssl_certfile=str(cert), ssl_keyfile=str(key))


def local_tls_context(certfile):
    # Trust this service's certificate for loopback probes. A company certificate
    # need not name 127.0.0.1, so only this local probe skips hostname matching.
    context = ssl.create_default_context(cafile=str(certfile))
    context.check_hostname = False
    if hasattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN'):
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


def check_health(port=8080):
    options = tls_options()
    context = local_tls_context(options['ssl_certfile'])
    with urllib.request.urlopen(f'https://127.0.0.1:{port}/health', context=context, timeout=4) as response:
        if response.status != 200:
            raise RuntimeError('Application health check failed')
        return response.read()


if __name__ == '__main__':
    check_health()
