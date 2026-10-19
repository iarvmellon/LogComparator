"""Generate a self-signed certificate for an internal HTTPS deployment."""
import argparse
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


def create_certificate(folder, hosts, days=365):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    certificate, private_key = folder / 'server.crt', folder / 'server.key'
    if certificate.exists() or private_key.exists():
        raise ValueError('Certificate files already exist; choose another output folder.')
    if days < 1:
        raise ValueError('Certificate lifetime must be at least one day.')
    names = []
    for host in dict.fromkeys([*hosts, 'localhost', '127.0.0.1']):
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0] if hosts else 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    with private_key.open('xb') as stream:
        private_key.chmod(0o600)
        stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    with certificate.open('xb') as stream:
        stream.write(cert.public_bytes(serialization.Encoding.PEM))
    return certificate, private_key


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', action='append', default=[], help='IP or DNS name used in the browser; repeat for multiple names.')
    parser.add_argument('--output', type=Path, default=Path('certs'))
    parser.add_argument('--days', type=int, default=365)
    args = parser.parse_args()
    certificate, _ = create_certificate(args.output, args.host, args.days)
    print(f'Created {certificate} and server.key (self-signed, valid for {args.days} days).')
