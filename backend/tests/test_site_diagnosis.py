"""What a refusal is called, proven against a local server that refuses.

Each test is one real answer (status, headers, body) and the message a person
should read. The defect this covers: every HTML 401/403 was reported as "an
anti-bot or CSRF challenge", an nginx 403 and an expired-session login page
included, while a CDN that blocks automation and answers JSON was reported as an
expired session. Nothing here talks to the internet, and nothing retries a
challenge.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from app.services.connectors import ConnectorError, HttpConnector
from app.services.site_diagnosis import diagnose
from tests.support.refusal_server import MODES as REFUSAL_MODES
from tests.support.refusal_server import RefusalServer, start_refusal


@pytest.fixture
def refusal() -> Iterator[Callable[[str], RefusalServer]]:
    servers: list[RefusalServer] = []

    def start(mode: str) -> RefusalServer:
        server = start_refusal(mode)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _send(server: RefusalServer, *, headers: dict[str, str] | None = None) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        HttpConnector(allow_private=True, min_delay_ms=0, max_retries=0).render_and_send(
            url=server.url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            headers=headers,
            timeout_seconds=5,
        )
    return caught.value


def test_a_cloudflare_challenge_names_the_product_and_is_never_retried(
    refusal: Callable[[str], RefusalServer],
) -> None:
    server = refusal("cloudflare_challenge")
    error = _send(server)

    assert error.code == "blocked_by_site"
    assert "Cloudflare" in error.message
    assert "will not retry" in error.message
    # One request: asking a challenge again is what gets a runner banned.
    assert len(server.calls) == 1
    # The evidence is the header and the page's own text, not "it was HTML".
    evidence = " ".join(error.details["evidence"])
    assert "cf-mitigated" in evidence
    assert "just a moment" in evidence
    assert error.details["headers"]["cf-mitigated"] == "challenge"
    assert error.details["headers"]["cf-ray"] == "8f2a1c4d0e7b1234-LHR"


def test_a_plain_nginx_403_is_not_called_an_anti_bot_challenge(
    refusal: Callable[[str], RefusalServer],
) -> None:
    """The old classifier said "anti-bot or CSRF" for any HTML 403 page."""
    error = _send(refusal("nginx_forbidden"))

    assert error.code == "auth_error"
    assert "anti-bot" not in error.message.lower()
    assert "HTTP 403" in error.message
    # No session was sent, and the message says exactly that.
    assert "no session was sent" in error.message
    assert error.details["status_code"] == 403
    assert error.details["headers"]["server"] == "nginx/1.25.3"


def test_a_csrf_refusal_gets_its_own_code_and_advice(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("csrf_json"), headers={"Cookie": "session=abc"})

    assert error.code == "csrf_rejected"
    assert "CSRF" in error.message
    assert "fresh cURL" in error.message
    assert "anti-bot" not in error.message.lower()
    assert error.details["status_code"] == 403
    assert "csrf token" in " ".join(error.details["evidence"]).lower()


def test_a_cdn_that_blocks_automation_with_json_is_not_an_expired_session(
    refusal: Callable[[str], RefusalServer],
) -> None:
    """Akamai answers JSON, so the old classifier said "your session expired"."""
    error = _send(refusal("akamai_denied"))

    assert error.code == "blocked_by_site"
    assert "Akamai" in error.message
    assert "session expired" not in error.message
    assert error.details["headers"]["x-akamai-request-id"] == "1a2b3c4d"


def test_an_expired_session_login_page_says_the_session_is_missing(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("login_page"))

    assert error.code == "auth_error"
    assert "anti-bot" not in error.message.lower()
    assert "signed-in session" in error.message
    assert "Cookie or Authorization" in error.message


def test_a_401_with_a_sent_token_says_the_session_expired(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("bearer_401"), headers={"Authorization": "Bearer old-token"})

    assert error.code == "auth_error"
    assert "expired" in error.message
    assert "paste a fresh cURL" in error.message
    # The request did carry a token; the message must not claim otherwise.
    assert "carried no Cookie" not in error.message


def test_a_403_with_credentials_names_permission_not_the_anti_bot_story(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("permission_403"), headers={"Cookie": "session=abc"})

    assert error.code == "auth_error"
    assert "may not have access" in error.message
    assert "anti-bot" not in error.message.lower()
    assert "with the pasted session" in error.message


def test_rate_limiting_says_what_to_do_and_keeps_its_status(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("rate_limited"))

    assert error.code == "http_error"
    assert error.details["status_code"] == 429
    assert "rate-limiting" in error.message
    assert error.details["headers"]["retry-after"] == "0"


def test_the_session_cookie_never_reaches_the_detail(
    refusal: Callable[[str], RefusalServer],
) -> None:
    error = _send(refusal("csrf_json"), headers={"Cookie": "session=abc"})

    assert error.details["snippet"]
    assert "session=abc" not in str(error.details)
    # Only diagnostic headers travel; a Set-Cookie never does.
    assert all(name != "set-cookie" for name in error.details.get("headers", {}))


def test_a_refused_case_keeps_the_evidence_in_its_stored_detail() -> None:
    """The run report, not just the check panel, says who refused and why."""
    from app.services.run_executor import _failure_detail

    detail = _failure_detail(
        "http_error",
        "the site refused this request",
        {
            "status_code": 403,
            "target": "chat.example.test/api/message",
            "snippet": '{"error":"forbidden"}',
            "headers": {"cf-mitigated": "challenge"},
            "evidence": ["body says 'just a moment'"],
        },
    )

    assert detail is not None
    assert detail["status"] == 403
    assert detail["headers"] == {"cf-mitigated": "challenge"}
    assert detail["evidence"] == ["body says 'just a moment'"]


def test_a_200_is_never_diagnosed_as_a_refusal() -> None:
    assert (
        diagnose(
            200,
            {"server": "cloudflare"},
            "<html>Just a moment...</html>",
            sent_credentials=True,
        )
        is None
    )


@pytest.mark.parametrize("mode", sorted(REFUSAL_MODES))
def test_each_refusal_mode_is_a_structured_error_not_a_crash(
    refusal: Callable[[str], RefusalServer], mode: str
) -> None:
    """Whatever the site answers, the result is a code, a status and a snippet."""
    error = _send(refusal(mode))

    assert error.code in {"auth_error", "blocked_by_site", "csrf_rejected", "http_error"}
    assert error.details["status_code"] == REFUSAL_MODES[mode].status
    assert error.details["target"].endswith("/chat")
    assert error.message
