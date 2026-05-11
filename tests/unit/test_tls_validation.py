"""Tests for explicit TLS certificate validation in HTTP clients."""

from __future__ import annotations

import ssl
import subprocess
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


class TestRemoteRegistryTlsContext:
    """Verify remote_registry._tls_context() enforces strict TLS."""

    def test_returns_ssl_context(self) -> None:
        from reins.platform.remote_registry import _tls_context

        ctx = _tls_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_check_hostname_enabled(self) -> None:
        from reins.platform.remote_registry import _tls_context

        ctx = _tls_context()
        assert ctx.check_hostname is True

    def test_verify_mode_cert_required(self) -> None:
        from reins.platform.remote_registry import _tls_context

        ctx = _tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestHttpTlsContext:
    """Verify _http._tls_context() enforces strict TLS."""

    def test_returns_ssl_context(self) -> None:
        from reins.integrations._http import _tls_context

        ctx = _tls_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_check_hostname_enabled(self) -> None:
        from reins.integrations._http import _tls_context

        ctx = _tls_context()
        assert ctx.check_hostname is True

    def test_verify_mode_cert_required(self) -> None:
        from reins.integrations._http import _tls_context

        ctx = _tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED


class TestTlsContextUsedInUrlopen:
    """Grep-based tests verifying context= parameter is passed to urlopen."""

    def test_remote_registry_passes_context(self) -> None:
        source = (SRC_ROOT / "reins" / "platform" / "remote_registry.py").read_text()
        assert "context=_tls_context()" in source

    def test_http_module_passes_context(self) -> None:
        source = (SRC_ROOT / "reins" / "integrations" / "_http.py").read_text()
        assert "context=_tls_context()" in source

    def test_transport_uses_verify_true(self) -> None:
        source = (SRC_ROOT / "reins" / "execution" / "mcp" / "transport.py").read_text()
        assert "verify=True" in source
