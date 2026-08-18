"""Auth business logic: registration and authentication.

Security behaviors included here (see the plan this was built from for
the full reasoning): generic invalid-credentials messaging with
timing-equalized dummy-hash checks (so probing a username can't tell
"wrong password" from "no such user" by response content or timing), a
real UNIQUE constraint as the source of truth for "already taken"
(TOCTOU-safe under concurrent registration, not just a SELECT-then-INSERT
precheck), and basic per-account lockout after repeated failed attempts.

Deliberately deferred, not silently missing: password reset (until it
exists, resetting password_hash is a manual DB operation), IP-based rate
limiting, email verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from recon_platform.auth.db import users_table

MIN_PASSWORD_LENGTH = 8
MIN_USERNAME_LENGTH = 3
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Checked against on the "no such user" path so that branch costs about
# the same as a real user's wrong-password branch, rather than returning
# early and leaking account existence via response time.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthError(Exception):
    """Raised for any registration/login failure. The message is always
    safe to show the user directly."""


@dataclass
class User:
    id: int
    username: str
    email: str


def register_user(engine: Engine, username: str, email: str, password: str) -> User:
    username = username.strip()
    email = email.strip().lower()

    if len(username) < MIN_USERNAME_LENGTH:
        raise AuthError(f"Username must be at least {MIN_USERNAME_LENGTH} characters.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise AuthError("Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    with engine.begin() as conn:
        try:
            result = conn.execute(
                users_table.insert().values(
                    username=username, email=email, password_hash=password_hash,
                )
            )
        except IntegrityError:
            raise AuthError("That username or email is already registered.") from None
        user_id = result.inserted_primary_key[0]

    return User(id=user_id, username=username, email=email)


def authenticate(engine: Engine, username: str, password: str) -> User:
    """Note: the error is raised *after* the `with engine.begin()` block
    exits, never inside it -- raising inside would propagate out of the
    transactional context manager and roll back whatever failed-attempt/
    lockout update was just written in the same block, silently
    discarding the lockout state this function exists to persist."""
    username = username.strip()
    error: str | None = None
    user: User | None = None

    with engine.begin() as conn:
        row = conn.execute(
            select(users_table).where(users_table.c.username == username)
        ).mappings().first()

        if row is None:
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
            error = "Invalid username or password."
        elif row["locked_until"] is not None and row["locked_until"] > _utcnow():
            error = "Too many failed attempts. Try again in a few minutes."
        elif not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            attempts = row["failed_attempts"] + 1
            locked_until = (
                _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                if attempts >= MAX_FAILED_ATTEMPTS
                else None
            )
            conn.execute(
                users_table.update()
                .where(users_table.c.id == row["id"])
                .values(failed_attempts=attempts, locked_until=locked_until)
            )
            error = "Invalid username or password."
        else:
            conn.execute(
                users_table.update()
                .where(users_table.c.id == row["id"])
                .values(failed_attempts=0, locked_until=None)
            )
            user = User(id=row["id"], username=row["username"], email=row["email"])

    if error is not None:
        raise AuthError(error)
    assert user is not None
    return user
