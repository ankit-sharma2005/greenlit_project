from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import UUID

from app.config import settings

_TOKEN_TTL_SECONDS = 15 * 60


def fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def issue_test_token(
    resource: str,
    workspace_id: UUID,
    user_id: UUID,
    payload_hash: str,
) -> str:
    payload = json.dumps(
        {
            "resource": resource,
            "workspace_id": str(workspace_id),
            "user_id": str(user_id),
            "payload_hash": payload_hash,
            "expires_at": int(time.time()) + _TOKEN_TTL_SECONDS,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        settings.secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def verify_test_token(
    token: str,
    resource: str,
    workspace_id: UUID,
    user_id: UUID,
    payload_hash: str,
) -> bool:
    try:
        encoded, supplied_signature = token.split(".", maxsplit=1)
        expected_signature = hmac.new(
            settings.secret_key.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        payload_bytes = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(payload_bytes)
        return (
            payload.get("resource") == resource
            and payload.get("workspace_id") == str(workspace_id)
            and payload.get("user_id") == str(user_id)
            and payload.get("payload_hash") == payload_hash
            and isinstance(payload.get("expires_at"), int)
            and payload["expires_at"] >= int(time.time())
        )
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
