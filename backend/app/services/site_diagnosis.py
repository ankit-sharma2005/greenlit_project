"""Why a site refused a request: read the answer instead of guessing by shape.

A 401/403 used to be called "an anti-bot or CSRF challenge" whenever the body
looked like HTML, which is true of almost every refusal a real site sends: an
nginx 403 page, a login page after the session expired, a permission-denied
page. The opposite happened too — a CDN that blocks automation and answers
JSON (Akamai, AWS WAF) was reported as "your session expired; paste a fresh
cURL", which is advice that cannot work.

This module classifies a refusal from the evidence a server actually gives:

* anti-bot evidence — a challenge header (``cf-mitigated``, DataDome,
  PerimeterX, Imperva, Sucuri, AWS WAF) or the challenge page's own text;
* CSRF evidence — the words an anti-forgery rejection uses;
* otherwise the status is the status: 401 is a session the site did not accept,
  403 is a refusal (permission, firewall or request shape), 429 is rate limiting.

Nothing here retries, solves a challenge or imitates a browser. A site that
refuses automation gets a clear limitation, not a bypass.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.services.target_error import redact_snippet

BLOCKED = "blocked_by_site"
CSRF = "csrf_rejected"
AUTH = "auth_error"

# Response headers whose value is a diagnosis in itself. The value is not
# compared case-sensitively: CDNs are not consistent about it.
_ANTI_BOT_HEADERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("cf-mitigated", ("challenge", "block", "managed"), "Cloudflare"),
    ("x-datadome", (), "DataDome"),
    ("x-dd-b", (), "DataDome"),
    ("x-px-block", (), "PerimeterX"),
    ("x-px-original-cookie", (), "PerimeterX"),
    ("x-iinfo", (), "Imperva"),
    ("x-sucuri-block", (), "Sucuri"),
    ("x-amzn-waf-action", ("block", "captcha", "challenge"), "AWS WAF"),
)

# The words a challenge page uses instead of an answer. Each marker names the
# product it belongs to, or "a bot check" when several use the same sentence.
_ANTI_BOT_BODY: tuple[tuple[str, str], ...] = (
    ("just a moment", "Cloudflare"),
    ("cf-browser-verification", "Cloudflare"),
    ("attention required", "Cloudflare"),
    ("enable javascript and cookies to continue", "Cloudflare"),
    ("checking your browser", "a bot check"),
    ("verify you are human", "a bot check"),
    ("captcha-delivery.com", "DataDome"),
    ("px-captcha", "PerimeterX"),
    ("incapsula incident id", "Imperva"),
    ("_incapsula_resource", "Imperva"),
    ("the request could not be satisfied", "CloudFront"),
)

# CloudFront and Akamai answer with their own prose, not a challenge form.
_AKAMAI_BODY = ("access denied",)

# What an anti-forgery rejection says. Deliberately narrow: a page that merely
# mentions CSRF in a help article is not a CSRF rejection.
_CSRF_BODY = (
    "csrf token",
    "csrf verification",
    "csrf failed",
    "invalid csrf",
    "missing csrf",
    "xsrf",
    "anti-forgery",
    "antiforgery",
    "forgery token",
)

# Response headers worth keeping on a failure: they say who refused and why,
# and none of them carries a credential.
_DIAGNOSTIC_HEADERS = (
    "content-type",
    "server",
    "cf-mitigated",
    "cf-ray",
    "cf-cache-status",
    "www-authenticate",
    "retry-after",
    "x-datadome",
    "x-dd-b",
    "x-px-block",
    "x-iinfo",
    "x-akamai-request-id",
    "x-amzn-waf-action",
    "x-sucuri-id",
    "x-request-id",
    "via",
)


@dataclass(frozen=True)
class Diagnosis:
    """One refusal, named: the code a report stores and the advice a person reads."""

    code: str
    message: str
    evidence: tuple[str, ...] = ()
    provider: str | None = None


def diagnostic_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """The response headers that explain a refusal, redacted and bounded."""
    kept: dict[str, str] = {}
    for name, value in (headers or {}).items():
        key = str(name).lower()
        if key not in _DIAGNOSTIC_HEADERS:
            continue
        kept[key] = redact_snippet(str(value), limit=120)
    return kept


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name:
            return str(value)
    return ""


def _anti_bot(headers: Mapping[str, str], body: str) -> tuple[str, list[str]] | None:
    """The product that challenged this request, with the evidence that says so."""
    lowered = body.lower()
    evidence: list[str] = []
    provider: str | None = None
    for name, values, product in _ANTI_BOT_HEADERS:
        value = _header(headers, name)
        if not value:
            continue
        if values and not any(marker in value.lower() for marker in values):
            continue
        provider = product
        evidence.append(f"header {name}: {value[:60]}")
    for marker, product in _ANTI_BOT_BODY:
        if marker in lowered:
            provider = provider or product
            evidence.append(f"body says {marker!r}")
    if any(marker in lowered for marker in _AKAMAI_BODY) and (
        "reference #" in lowered or "akamai" in lowered
    ):
        provider = provider or "Akamai"
        evidence.append("body is an Akamai access-denied page")
    if not evidence:
        return None
    return provider or "a bot", evidence


def _csrf(body: str) -> list[str]:
    lowered = body.lower()
    return [f"body says {marker!r}" for marker in _CSRF_BODY if marker in lowered]


def diagnose(
    status: int,
    headers: Mapping[str, str] | None,
    body: str,
    *,
    sent_credentials: bool,
) -> Diagnosis | None:
    """Name a refusal from what the server sent back, or ``None`` if it is not one.

    ``sent_credentials`` is whether the request carried a ``Cookie`` or
    ``Authorization`` header: it turns "your session expired" from a guess into
    a statement about the request GreenLit actually made.
    """
    if status not in (401, 403, 429):
        return None
    response_headers = headers or {}
    text = body or ""

    if status in (401, 403):
        challenge = _anti_bot(response_headers, text)
        if challenge is not None:
            provider, evidence = challenge
            # "an Akamai check", "a Cloudflare check": the name is the product's.
            article = "an" if provider[:1].lower() in "aeiou" else "a"
            return Diagnosis(
                code=BLOCKED,
                message=(
                    f"the site blocked this request with {article} {provider} anti-bot check "
                    f"(HTTP {status}); it does not accept automated requests, so GreenLit "
                    "will not retry — use a test account in a browser, or ask the owner to "
                    "allow this runner"
                ),
                evidence=tuple(evidence),
                provider=provider,
            )
        csrf = _csrf(text)
        if csrf:
            return Diagnosis(
                code=CSRF,
                message=(
                    "the site rejected the request because its CSRF/anti-forgery token is "
                    f"missing or stale (HTTP {status}); paste a fresh cURL copied from the "
                    "same browser tab right after sending a message, so the copied headers "
                    "carry the current token"
                ),
                evidence=tuple(csrf),
            )

    if status == 429:
        return Diagnosis(
            code="http_error",
            message=(
                "the site is rate-limiting this runner (HTTP 429); wait a minute and try "
                "again, or lower the request rate in the run limits"
            ),
            evidence=("status 429",),
        )

    if status == 401:
        if sent_credentials:
            return Diagnosis(
                code=AUTH,
                message=(
                    "your app rejected the session (HTTP 401): the cookie or token in the "
                    "pasted cURL has expired; sign in again and paste a fresh cURL"
                ),
                evidence=("status 401", "the request carried a Cookie or Authorization header"),
            )
        return Diagnosis(
            code=AUTH,
            message=(
                "your app needs a signed-in session (HTTP 401) and this request carried no "
                "Cookie or Authorization header; sign in with a test account and paste a "
                "cURL copied from that tab"
            ),
            evidence=("status 401", "no Cookie or Authorization header was sent"),
        )

    if sent_credentials:
        message = (
            "the site refused this request (HTTP 403) with the pasted session: the account "
            "may not have access to this endpoint, or the site's firewall refused the "
            "request as sent (headers, method or body)"
        )
    else:
        message = (
            "the site refused this request (HTTP 403) and no session was sent: use a test "
            "account and paste a cURL that carries its Cookie or Authorization header"
        )
    return Diagnosis(
        code=AUTH,
        message=message,
        evidence=(
            "status 403",
            "the request carried a Cookie or Authorization header"
            if sent_credentials
            else "no Cookie or Authorization header was sent",
            "no anti-bot or CSRF evidence in the response",
        ),
    )


def evidence_lines(evidence: Iterable[str]) -> list[str]:
    """Evidence as a bounded list, so a report never grows without limit."""
    return [str(line)[:120] for line in list(evidence)[:8]]
