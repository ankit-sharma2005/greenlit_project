"""A loopback HTTPS server with a certificate that is not trusted or has expired.

Real company apps sit behind TLS, and the common breakages are a self-signed
certificate and an expired one. Both must read differently, so the certificate is
generated here with ``cryptography`` (no network, no fixture file in the tree).
"""

from __future__ import annotations

import datetime as dt
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _certificate(expired: bool) -> ssl.SSLContext:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    not_before = now - dt.timedelta(days=30)
    not_after = now + dt.timedelta(days=30)
    if expired:
        not_before = now - dt.timedelta(days=60)
        not_after = now - dt.timedelta(days=1)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile=_CertFile(certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")),
        keyfile=_CertFile(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("ascii")
        ),
    )
    return context


class _CertFile(str):
    """A PEM path ``load_cert_chain`` can read: cryptography needs real files."""

    def __new__(cls, pem: str) -> _CertFile:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as handle:
            handle.write(pem)
            path = handle.name
        return super().__new__(cls, path)


class TlsQuirkServer:
    """A running HTTPS quirk server that only answers one case."""

    def __init__(self, *, expired: bool) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                body = b'{"answer": "Hello over TLS"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.socket = _certificate(expired).wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"https://{host}:{port}/chat"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
