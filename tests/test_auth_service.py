"""Auth service: registration + login, including the security behaviors
that matter even for a demo -- see recon_platform/auth/service.py's
docstring for what's covered vs. deliberately deferred.

Uses a temp file-based SQLite DB per test (via pytest's tmp_path), not
sqlite:///:memory: -- an in-memory SQLite DB is per-connection, and
SQLAlchemy's default pool opens more than one connection over a test's
lifetime, so state wouldn't reliably persist between the register and
authenticate calls within the same test.
"""

from __future__ import annotations

import pytest

from recon_platform.auth.db import make_engine
from recon_platform.auth.service import AuthError, authenticate, register_user


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "test_auth.db"
    return make_engine(f"sqlite:///{db_path}")


def test_register_then_authenticate_succeeds(engine):
    user = register_user(engine, "alice", "alice@example.com", "correcthorse123")
    assert user.username == "alice"
    assert user.email == "alice@example.com"

    logged_in = authenticate(engine, "alice", "correcthorse123")
    assert logged_in.username == "alice"


def test_wrong_password_rejected_with_generic_message(engine):
    register_user(engine, "bob", "bob@example.com", "correcthorse123")

    with pytest.raises(AuthError, match="Invalid username or password"):
        authenticate(engine, "bob", "wrong-password")


def test_nonexistent_user_rejected_with_same_generic_message(engine):
    """Same message as a wrong password -- proves the API doesn't leak
    which usernames exist via a different error string."""
    with pytest.raises(AuthError, match="Invalid username or password"):
        authenticate(engine, "nobody-registered", "whatever123")


def test_duplicate_username_rejected(engine):
    register_user(engine, "carol", "carol@example.com", "correcthorse123")

    with pytest.raises(AuthError, match="already registered"):
        register_user(engine, "carol", "different@example.com", "correcthorse123")


def test_duplicate_email_rejected(engine):
    register_user(engine, "dave", "dave@example.com", "correcthorse123")

    with pytest.raises(AuthError, match="already registered"):
        register_user(engine, "dave2", "dave@example.com", "correcthorse123")


def test_short_password_rejected(engine):
    with pytest.raises(AuthError, match="Password must be at least"):
        register_user(engine, "eve", "eve@example.com", "short")


def test_short_username_rejected(engine):
    with pytest.raises(AuthError, match="Username must be at least"):
        register_user(engine, "ab", "ab@example.com", "correcthorse123")


def test_invalid_email_rejected(engine):
    with pytest.raises(AuthError, match="valid email"):
        register_user(engine, "frank", "not-an-email", "correcthorse123")


@pytest.mark.parametrize(
    "bad_email",
    [
        "a@b.c",  # single-char TLD -- the old "@" + "." check let this through
        "a@.com",  # empty label before the dot
        "a@b..com",  # empty label between dots
        "@nobody.com",  # empty local part
        "a@-bad.com",  # label can't start with a hyphen
    ],
)
def test_malformed_email_domain_rejected(engine, bad_email):
    with pytest.raises(AuthError, match="valid email"):
        register_user(engine, "gwen", bad_email, "correcthorse123")


def test_account_locks_after_repeated_failed_attempts(engine):
    register_user(engine, "grace", "grace@example.com", "correcthorse123")

    for _ in range(5):
        with pytest.raises(AuthError):
            authenticate(engine, "grace", "wrong-password")

    # Even the correct password is now rejected while locked.
    with pytest.raises(AuthError, match="Too many failed attempts"):
        authenticate(engine, "grace", "correcthorse123")


def test_successful_login_resets_failed_attempt_counter(engine):
    register_user(engine, "heidi", "heidi@example.com", "correcthorse123")

    for _ in range(3):
        with pytest.raises(AuthError):
            authenticate(engine, "heidi", "wrong-password")

    # Correct password before hitting the lockout threshold should
    # succeed and clear the counter.
    logged_in = authenticate(engine, "heidi", "correcthorse123")
    assert logged_in.username == "heidi"

    # Confirm the counter actually reset: three more failures shouldn't
    # be enough to lock the account (5 needed from a fresh count).
    for _ in range(3):
        with pytest.raises(AuthError, match="Invalid username or password"):
            authenticate(engine, "heidi", "wrong-password")
