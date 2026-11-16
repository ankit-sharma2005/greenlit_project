"""Operator CLI: read accounts and change a role, never a password.

Run it inside the API container, where the database is reachable:

    python -m app.cli set-role --email you@example.com --role admin
    python -m app.cli list-users --limit 20

It only changes the role of an account that already exists, refuses to demote the
last admin, and writes one audit entry per change. It never creates users and
never reads, prints or stores a password or a hash.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ROLE_ADMIN, User
from app.services import audit

ROLES = ("admin", "member", "reviewer")
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


class CliError(RuntimeError):
    """A refusal the operator can fix; the message is safe to print."""


def set_role(
    session: Session, email: str, role: str, *, actor: str = "cli"
) -> tuple[str, str, str]:
    """Change one existing account's role; return (email, old role, new role)."""
    if role not in ROLES:
        raise CliError(f"Unknown role '{role}'. Choose one of: {', '.join(ROLES)}.")
    wanted = email.strip().lower()
    if not wanted:
        raise CliError("Give the account's email with --email.")
    user = session.scalar(select(User).where(User.email == wanted))
    if user is None:
        raise CliError(f"No account with the email {wanted}. This command never creates one.")

    previous = user.role
    if previous == role:
        return user.email, previous, role
    if previous == ROLE_ADMIN and role != ROLE_ADMIN:
        admins = session.scalar(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        if (admins or 0) <= 1:
            raise CliError("Refusing to demote the last admin. Promote another account first.")

    user.role = role
    audit.record(
        session,
        "user.role_changed",
        actor_id=None,
        target_type="user",
        target_id=str(user.id),
        metadata={"from": previous, "to": role, "actor": actor},
    )
    session.commit()
    return user.email, previous, role


def list_users(session: Session, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
    """The newest accounts, with only the fields an operator needs."""
    bounded = max(1, min(limit, MAX_LIST_LIMIT))
    rows = session.scalars(
        select(User).order_by(User.created_at.desc(), User.email).limit(bounded)
    ).all()
    return [
        {
            "email": row.email,
            "role": row.role,
            "created_at": row.created_at.date().isoformat() if row.created_at else "",
        }
        for row in rows
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    role = commands.add_parser("set-role", help="change the role of an existing account")
    role.add_argument("--email", required=True)
    role.add_argument("--role", required=True, choices=ROLES)

    listing = commands.add_parser("list-users", help="list accounts (email, role, created)")
    listing.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    args = _parser().parse_args(argv)
    session = SessionLocal()
    try:
        if args.command == "set-role":
            email, previous, current = set_role(session, args.email, args.role)
            print(f"{email}: {previous} -> {current}")
            return 0
        for row in list_users(session, args.limit):
            print(f"{row['email']}  {row['role']}  {row['created_at']}")
        return 0
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
