"""Opening web addresses with a certificate check that works on every computer.

Python's own HTTPS check uses its own list of trusted certificates. In the packaged
app, and on many Windows computers, that list is missing or cannot fetch the
intermediate certificates a site relies on, so downloads fail with
CERTIFICATE_VERIFY_FAILED ("unable to get local issuer certificate").

Every download and API call goes through `urlopen()` here, which checks
certificates with the operating system's own store when `truststore` is
installed, else with the `certifi` bundle, else with Python's default.
Standard library only; both packages are optional.
"""

from __future__ import annotations

import ssl
import urllib.request

_context: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    """The best certificate check available, built once and shared."""
    global _context
    if _context is None:
        _context = _make_context()
    return _context


def _make_context() -> ssl.SSLContext:
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def urlopen(request: urllib.request.Request | str, timeout: float):
    """`urllib.request.urlopen` with `ssl_context()`. Plain http:// addresses are unaffected."""
    return urllib.request.urlopen(request, timeout=timeout, context=ssl_context())
