"""Real-world quirk coverage: each test states what a first real test must say.

Every test runs the real ``HttpConnector`` against the local quirk server in
``tests/support/quirk_server.py``. The assertion is the message a person should
read, not an implementation detail: a clear structured failure at worst, never a
crash, a hang, a wrong score or a leaked secret.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from app.services.connectors import ConnectorError, HttpConnector, Trace
from tests.support.quirk_server import ANSWER, QuirkServer, start_quirk


@pytest.fixture
def quirk() -> Iterator[Callable[..., QuirkServer]]:
    servers: list[QuirkServer] = []

    def start(mode: str, **kwargs: int) -> QuirkServer:
        server = start_quirk(mode, **kwargs)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _connector(max_retries: int = 3) -> HttpConnector:
    return HttpConnector(allow_private=True, min_delay_ms=0, max_retries=max_retries)


def _send(
    server: QuirkServer,
    *,
    connector: HttpConnector | None = None,
    path: str = "/chat",
    response_format: str = "json",
    answer_path: str | None = None,
    timeout_seconds: int = 5,
) -> Trace:
    client = connector or _connector(max_retries=0)
    return client.render_and_send(
        url=f"{server.base}{path}",
        body_template='{"question": {{input}}}',
        input_text="hello",
        timeout_seconds=timeout_seconds,
        response_format=response_format,
        answer_path=answer_path,
    )


@pytest.mark.parametrize(
    ("mode", "headers"),
    [
        ("auth_bearer", {"Authorization": "Bearer test-token"}),
        ("auth_api_key", {"X-Api-Key": "test-key"}),
        ("auth_basic", {"Authorization": "Basic ZGVtbzpkZW1v"}),
        ("auth_cookie", {"Cookie": "session=abc"}),
    ],
)
def test_each_auth_style_is_sent_and_accepted(
    quirk: Callable[..., QuirkServer], mode: str, headers: dict[str, str]
) -> None:
    server = quirk(mode)
    trace = _send_with_headers(server, headers)
    assert trace.output == ANSWER


def _send_with_headers(server: QuirkServer, headers: dict[str, str]) -> Trace:
    return _connector(max_retries=0).render_and_send(
        url=server.url,
        body_template='{"question": {{input}}}',
        input_text="hello",
        headers=headers,
        timeout_seconds=5,
    )


def test_a_token_that_expires_mid_run_stops_with_a_clear_error(
    quirk: Callable[..., QuirkServer],
) -> None:
    server = quirk("expire", expire_after=1)
    first = _send(server)
    assert first.output == ANSWER
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == "auth_error"
    assert "expired" in error.message.lower() or "session" in error.message.lower()
    # A rejected credential is not a "try again" answer: one request, no storm.
    assert server.calls == 2


def test_an_anti_bot_challenge_is_a_blocked_site_not_a_wrong_answer(
    quirk: Callable[..., QuirkServer],
) -> None:
    server = quirk("challenge")
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == "blocked_by_site"
    assert "blocked" in error.message.lower()
    assert "verify you are human" in str(error.details.get("snippet", "")).lower()
    # A challenge page is never retried: asking again is what gets you banned.
    assert server.calls == 1


def test_a_same_host_redirect_is_followed(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("redirect_same")
    trace = _send(server)
    assert trace.output == ANSWER
    assert "/chat" in server.paths_seen()
    assert "/chat-next" in server.paths_seen()


def test_a_cross_host_redirect_is_refused_and_names_the_target(
    quirk: Callable[..., QuirkServer],
) -> None:
    server = quirk("redirect_other_host")
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == "redirect_blocked"
    assert "localhost" in error.message
    # The other host was never contacted: this is the SSRF guard, not a hint.
    assert "/elsewhere" not in server.paths_seen()


def test_a_redirect_loop_stops_after_three_hops(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("redirect_loop")
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == "redirect_loop"
    assert "redirect" in error.message.lower()
    assert server.calls <= 4


@pytest.mark.parametrize(
    ("mode", "answer_path", "expected"),
    [
        ("openai", None, ANSWER),
        ("nested", "data.result.answer", ANSWER),
        ("messages_array", None, ANSWER),
        ("gzip", None, ANSWER),
    ],
)
def test_a_known_response_shape_is_mapped(
    quirk: Callable[..., QuirkServer], mode: str, answer_path: str | None, expected: str
) -> None:
    server = quirk(mode)
    trace = _send(server, answer_path=answer_path)
    assert trace.output == expected


@pytest.mark.parametrize(
    ("mode", "code", "hint"),
    [
        ("html_200", "invalid_json", "html"),
        ("empty", "invalid_json", "empty"),
        ("invalid_utf8", "invalid_json", "read"),
        ("plain_text", "invalid_json", "read"),
        ("null_answer", "wrong_answer_path", "path"),
    ],
)
def test_an_unreadable_answer_names_what_was_tried(
    quirk: Callable[..., QuirkServer], mode: str, code: str, hint: str
) -> None:
    server = quirk(mode)
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == code
    assert hint in (error.message + " " + str(error.details.get("message", ""))).lower()


def test_a_huge_json_body_is_capped_not_parsed(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("huge")
    with pytest.raises(ConnectorError) as caught:
        _send(server, timeout_seconds=30)
    error = caught.value
    assert error.code == "response_too_large"
    assert "MB" in error.message or "too large" in error.message.lower()


def test_a_stream_without_a_final_event_is_flagged_incomplete(
    quirk: Callable[..., QuirkServer],
) -> None:
    server = quirk("stream_no_done")
    trace = _send(server, response_format="sse")
    assert "Hello" in trace.output
    assert trace.incomplete is True


def test_a_stream_that_stalls_keeps_its_partial_answer(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("stream_stall")
    trace = _send(server, response_format="sse", timeout_seconds=2)
    assert trace.output == "partial"
    assert trace.incomplete is True


def test_a_secret_in_a_challenge_page_is_redacted(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("challenge")
    with pytest.raises(ConnectorError) as caught:
        _send_with_headers(server, {"Authorization": "Bearer super-secret-token"})
    assert "super-secret-token" not in str(caught.value.details)


def _send_url(url: str, *, timeout_seconds: int = 5) -> Trace:
    return _connector(max_retries=0).render_and_send(
        url=url,
        body_template='{"question": {{input}}}',
        input_text="hello",
        timeout_seconds=timeout_seconds,
    )


def test_a_self_signed_certificate_is_named_as_such() -> None:
    from tests.support.tls_server import TlsQuirkServer

    server = TlsQuirkServer(expired=False)
    try:
        with pytest.raises(ConnectorError) as caught:
            _send_url(server.url)
    finally:
        server.close()
    assert caught.value.code == "tls_error"
    assert "certificate" in caught.value.message.lower()


def test_an_expired_certificate_says_expired() -> None:
    from tests.support.tls_server import TlsQuirkServer

    server = TlsQuirkServer(expired=True)
    try:
        with pytest.raises(ConnectorError) as caught:
            _send_url(server.url)
    finally:
        server.close()
    assert caught.value.code == "tls_error"
    assert "expired" in caught.value.message.lower()


def test_a_dns_failure_is_not_a_timeout() -> None:
    with pytest.raises(ConnectorError) as caught:
        _send_url("http://greenlit-no-such-host.invalid/chat")
    error = caught.value
    assert error.code == "dns_error"
    assert "greenlit-no-such-host.invalid" in error.message


def test_a_connection_reset_is_reported(quirk: Callable[..., QuirkServer]) -> None:
    server = quirk("reset")
    with pytest.raises(ConnectorError) as caught:
        _send(server)
    error = caught.value
    assert error.code == "connection_reset"
    assert "closed" in error.message.lower()
