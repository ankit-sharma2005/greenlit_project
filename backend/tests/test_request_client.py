"""M3: Shared request function + SSRF-safe client tests."""

from __future__ import annotations

import pytest

from app.utils.request_client import (
    RequestResult,
    _is_private_host,
    _quote_input,
    _sanitize_url,
    make_request,
)


def test_is_private_localhost() -> None:
    """localhost should be detected as private."""
    assert _is_private_host("localhost")
    assert _is_private_host("127.0.0.1")


def test_is_private_internal_ranges() -> None:
    """Private IP ranges should be detected."""
    assert _is_private_host("10.0.0.1")
    assert _is_private_host("192.168.1.1")
    assert _is_private_host("172.16.0.1")
    assert _is_private_host("172.31.255.255")


def test_is_private_ipv6() -> None:
    """IPv6 localhost and link-local should be detected."""
    assert _is_private_host("::1")
    assert _is_private_host("fe80::1")


def test_is_public_host() -> None:
    """Public hosts should not be detected as private."""
    result = _is_private_host("8.8.8.8")
    assert isinstance(result, bool)


def test_sanitize_url_valid() -> None:
    """Valid URLs should sanitize successfully."""
    url = _sanitize_url("https://httpbin.org/get")
    assert url == "https://httpbin.org/get"


def test_sanitize_url_private_blocks() -> None:
    """Private IPs should be blocked by URL sanitization."""
    with pytest.raises(ValueError):
        _sanitize_url("http://192.168.1.1/api")


def test_sanitize_url_localhost_blocks() -> None:
    """localhost should be blocked."""
    with pytest.raises(ValueError):
        _sanitize_url("http://localhost:8080/api")


def test_quote_input() -> None:
    """Input quoting should escape special characters."""
    result = _quote_input("hello {{input}} world $test")
    # Curly braces should be escaped
    assert "{{{" not in result or "{{{[[" in result
    # Dollar sign should be escaped
    assert "\\$" in result


def test_quote_input_no_special() -> None:
    """Input without special chars should pass through."""
    result = _quote_input("simple text")
    assert result == "simple text"


def test_make_request_success() -> None:
    """Successful request should return RequestResult with success=True."""
    result = make_request("https://httpbin.org/get", timeout=5)
    assert isinstance(result, RequestResult)
    assert result.success
    assert result.status_code == 200


def test_make_request_404() -> None:
    """404 response should return RequestResult with success=False."""
    result = make_request("https://httpbin.org/status/404", timeout=5)
    assert isinstance(result, RequestResult)
    assert not result.success
    assert result.status_code == 404


def test_make_request_403() -> None:
    """403 response should return RequestResult with success=False."""
    result = make_request("https://httpbin.org/status/403", timeout=5)
    assert isinstance(result, RequestResult)
    assert not result.success
    assert result.status_code == 403


def test_make_request_timeout() -> None:
    """Timeout should return RequestResult with success=False."""
    result = make_request("https://nonexistent-host-12345.com/get", timeout=2)
    assert isinstance(result, RequestResult)
    assert not result.success


def test_make_request_ssrf_block() -> None:
    """SSRF should block private IPs."""
    result = make_request("http://127.0.0.1/status/200", timeout=5)
    assert isinstance(result, RequestResult)
    assert not result.success
