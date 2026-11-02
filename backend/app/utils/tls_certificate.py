"""Is the certificate at this URL expired?

OpenSSL reports a self-signed certificate as ``self-signed certificate`` even when
it has also expired, which would make an expired certificate read like an
untrusted one. After verification fails, this probe connects without verifying
(verification already failed, so nothing more is given away) and reads the
certificate's own expiry date.
"""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime
from urllib.parse import urlsplit

from cryptography import x509


def certificate_expired(url: str, timeout: float = 5.0) -> bool | None:
    """``True``/``False`` when the certificate was read, ``None`` when it was not."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host or parts.scheme != "https":
        return None
    port = parts.port or 443
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as sock,
            context.wrap_socket(sock, server_hostname=host) as tls,
        ):
            der = tls.getpeercert(binary_form=True)
    except OSError:
        return None
    if not der:
        return None
    try:
        certificate = x509.load_der_x509_certificate(der)
    except ValueError:
        return None
    return certificate.not_valid_after_utc < datetime.now(UTC)
