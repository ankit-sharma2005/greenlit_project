"""A small cookie-session client for the parts of the GreenLit API the runner uses.

Standard library only, and the same session shape as ``scripts/greenlit_ci.py``:
one login, one httpOnly cookie jar, no token handling in the harness. A 429 is
never retried here — the runner stops and says so, because looping on a rate
limit is exactly what the product's own rules forbid.
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


class GreenLitError(Exception):
    """A request failed in a way the experiment cannot continue through."""

    def __init__(
        self, message: str, *, status: int | None = None, code: str | None = None
    ):
        super().__init__(message)
        self.status = status
        self.code = code


class RateLimited(GreenLitError):
    """GreenLit answered 429: stop, never loop."""


class GreenLitClient:
    """One signed-in session against ``GREENLIT_API``."""

    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies)
        )

    # -- transport ---------------------------------------------------------
    def _open(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        headers = {"Accept": "application/json, text/csv, */*"}
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except OSError:  # pragma: no cover - unreadable error body
                body = ""
            if exc.code == 429:
                raise RateLimited(
                    f"GreenLit rate-limited this request (HTTP 429) for {method} {path}",
                    status=429,
                    code="rate_limited",
                ) from exc
            code = None
            message = f"GreenLit returned HTTP {exc.code} for {method} {path}"
            try:
                payload = json.loads(body)
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict):
                    code = error.get("code")
                    message = f"{message}: {error.get('message')}"
            except (json.JSONDecodeError, ValueError):
                pass
            raise GreenLitError(message, status=exc.code, code=code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GreenLitError(
                f"Could not reach GreenLit at {self.base_url}: {exc}"
            ) from exc

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        body, _ = self._open(
            method,
            path,
            data=data,
            content_type="application/json" if data else None,
            extra_headers=extra_headers,
        )
        if not body:
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise GreenLitError(
                f"GreenLit returned invalid JSON for {method} {path}"
            ) from exc
        if not isinstance(parsed, dict):
            raise GreenLitError(
                f"GreenLit returned an unexpected body for {method} {path}"
            )
        return parsed

    def request_text(self, method: str, path: str) -> str:
        body, _ = self._open(method, path)
        return body.decode("utf-8", "replace")

    # -- endpoints ---------------------------------------------------------
    def login(self, email: str, password: str) -> None:
        self.request_json(
            "POST", "/api/v1/auth/login", {"email": email, "password": password}
        )

    def health(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/v1/healthz")

    def criteria(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/v1/criteria")

    def selected_judge(self) -> dict[str, Any] | None:
        payload = self.request_json("GET", "/api/v1/judge-profiles")
        items = payload.get("items") or []
        for item in items:
            if isinstance(item, dict) and item.get("is_selected"):
                return item
        return None

    def ensure_dataset(self, name: str, csv_text: str) -> dict[str, Any]:
        """Return the approved version of ``name``, uploading and approving v1 once."""
        listing = self.request_json("GET", "/api/v1/datasets?limit=100")
        for dataset in listing.get("items") or []:
            if not isinstance(dataset, dict) or dataset.get("name") != name:
                continue
            versions = dataset.get("versions") or []
            approved = [
                v for v in versions if isinstance(v, dict) and v.get("approved")
            ]
            if approved:
                version = approved[-1]
                return {
                    "dataset_id": dataset["id"],
                    "version_id": version["id"],
                    "version_no": version.get("version_no"),
                    "created": False,
                }
            for version in versions:
                if isinstance(version, dict):
                    self.request_json(
                        "POST",
                        f"/api/v1/datasets/{dataset['id']}/versions/{version['version_no']}/approve",
                    )
                    refreshed = self.request_json(
                        "GET", f"/api/v1/datasets/{dataset['id']}"
                    )
                    approved = [
                        v
                        for v in refreshed.get("versions") or []
                        if isinstance(v, dict) and v.get("approved")
                    ]
                    if approved:
                        return {
                            "dataset_id": dataset["id"],
                            "version_id": approved[-1]["id"],
                            "version_no": approved[-1].get("version_no"),
                            "created": False,
                        }
            raise GreenLitError(
                f"dataset {name!r} exists but has no approvable version"
            )

        created = self._upload_dataset(name, csv_text)
        dataset_id = created["id"]
        versions = created.get("versions") or []
        if not versions:
            refreshed = self.request_json("GET", f"/api/v1/datasets/{dataset_id}")
            versions = refreshed.get("versions") or []
        if not versions:
            raise GreenLitError(f"dataset {name!r} was created without a version")
        version_no = versions[0].get("version_no", 1)
        self.request_json(
            "POST", f"/api/v1/datasets/{dataset_id}/versions/{version_no}/approve"
        )
        refreshed = self.request_json("GET", f"/api/v1/datasets/{dataset_id}")
        approved = [
            v
            for v in refreshed.get("versions") or []
            if isinstance(v, dict) and v.get("approved")
        ]
        if not approved:
            raise GreenLitError(f"dataset {name!r} could not be approved")
        return {
            "dataset_id": dataset_id,
            "version_id": approved[-1]["id"],
            "version_no": approved[-1].get("version_no"),
            "created": True,
        }

    def _upload_dataset(self, name: str, csv_text: str) -> dict[str, Any]:
        boundary = f"----greenlit-experiment-{uuid.uuid4().hex}"
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n',
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="questions.csv"\r\nContent-Type: text/csv\r\n\r\n'
            ),
            csv_text,
            f"\r\n--{boundary}--\r\n",
        ]
        body = "".join(parts).encode("utf-8")
        data, _ = self._open(
            "POST",
            "/api/v1/datasets",
            data=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise GreenLitError("dataset upload returned an unexpected body")
        return parsed

    def ensure_target(
        self, name: str, url: str, answer_path: str, context_path: str
    ) -> str:
        """Create the saved target named ``name`` or update it in place."""
        listing = self.request_json("GET", "/api/v1/saved-targets")
        for target in listing.get("items") or []:
            if not isinstance(target, dict) or target.get("name") != name:
                continue
            self.request_json(
                "PATCH",
                f"/api/v1/saved-targets/{target['id']}",
                {
                    "url": url,
                    "method": "POST",
                    "answer_path": answer_path,
                    "context_path": context_path,
                    "response_format": "json",
                    "allow_private_targets": True,
                },
            )
            return str(target["id"])
        created = self.request_json(
            "POST",
            "/api/v1/saved-targets",
            {
                "name": name,
                "url": url,
                "method": "POST",
                "answer_path": answer_path,
                "context_path": context_path,
                "response_format": "json",
                "timeout_seconds": 60,
                "allow_private_targets": True,
            },
        )
        return str(created["id"])

    def check_target(
        self, url: str, answer_path: str, context_path: str
    ) -> dict[str, Any]:
        """One first-contact request through the product's own connector."""
        return self.request_json(
            "POST",
            "/api/v1/connectors/test",
            {
                "connector_type": "http_endpoint",
                "url": url,
                "method": "POST",
                "body_template": '{"question": {{input}}}',
                "answer_path": answer_path,
                "context_path": context_path,
                "allow_private_targets": True,
                "timeout_seconds": 60,
            },
        )

    def start_run(
        self, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """Start one run.

        A unique ``Idempotency-Key`` per repeat is deliberate: without one GreenLit
        collapses two identical starts within a minute into the same run, which
        would silently turn five repeats into one.
        """
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self.request_json("POST", "/api/v1/runs", payload, extra_headers=headers)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.request_json("GET", f"/api/v1/runs/{run_id}")

    def report(self, run_id: str, fmt: str) -> str:
        return self.request_text("GET", f"/api/v1/runs/{run_id}/report?format={fmt}")

    def items(self, run_id: str) -> list[dict[str, Any]]:
        """Every case of one run, each with the judge's own per-case label.

        The label comes from ``GET /runs/{id}/items`` (``judge_label``,
        ``judge_score``, ``judge_reason``), which is null for a case the judge never
        scored. It is saved beside the run's CSV so the analysis can compare it with
        a human label by dataset row, without asking GreenLit again.
        """
        payload = self.request_json("GET", f"/api/v1/runs/{run_id}/items?limit=1000")
        items = payload.get("items") if isinstance(payload, dict) else None
        return [item for item in items or [] if isinstance(item, dict)]


def normalise_api_url(value: str) -> str:
    """Reject anything that is not a plain http(s) URL with a host."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise GreenLitError(f"GREENLIT_API must be a full http(s) URL, got {value!r}")
    return value.rstrip("/")
