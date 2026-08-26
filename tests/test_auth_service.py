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
from recon_platform.auth.service import (
    AuthError,
    authenticate,
    generate_password_reset_token,
    register_user,
    reset_password_with_token,
)


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


def test_reset_token_generated_and_used_successfully(engine):
    register_user(engine, "ivan", "ivan@example.com", "correcthorse123")

    token = generate_password_reset_token(engine, "ivan@example.com")
    assert token is not None

    reset_password_with_token(engine, token, "newpassword456")

    # Old password no longer works, new one does.
    with pytest.raises(AuthError, match="Invalid username or password"):
        authenticate(engine, "ivan", "correcthorse123")
    logged_in = authenticate(engine, "ivan", "newpassword456")
    assert logged_in.username == "ivan"


def test_reset_token_unknown_email_returns_none(engine):
    """None, not an error -- callers must show the same generic message
    for both cases, so returning (rather than raising) lets the caller
    stay uniform without a try/except."""
    assert generate_password_reset_token(engine, "nobody@example.com") is None


def test_reset_password_invalid_token_rejected(engine):
    register_user(engine, "judy", "judy@example.com", "correcthorse123")

    with pytest.raises(AuthError, match="invalid or has expired"):
        reset_password_with_token(engine, "not-a-real-token", "newpassword456")


def test_reset_password_expired_token_rejected(engine):
    from datetime import datetime, timedelta, timezone

    from recon_platform.auth.db import users_table

    register_user(engine, "mallory", "mallory@example.com", "correcthorse123")
    token = generate_password_reset_token(engine, "mallory@example.com")

    # Backdate the token's expiry directly, same technique as the SLA
    # tests use to simulate time passing without a real sleep.
    naive_utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    with engine.begin() as conn:
        conn.execute(
            users_table.update()
            .where(users_table.c.username == "mallory")
            .values(reset_token_expires_at=naive_utc_now - timedelta(minutes=1))
        )

    with pytest.raises(AuthError, match="invalid or has expired"):
        reset_password_with_token(engine, token, "newpassword456")


def test_reset_token_is_single_use(engine):
    register_user(engine, "nathan", "nathan@example.com", "correcthorse123")
    token = generate_password_reset_token(engine, "nathan@example.com")

    reset_password_with_token(engine, token, "newpassword456")

    with pytest.raises(AuthError, match="invalid or has expired"):
        reset_password_with_token(engine, token, "yetanotherpassword789")


def test_reset_password_too_short_rejected(engine):
    register_user(engine, "olivia", "olivia@example.com", "correcthorse123")
    token = generate_password_reset_token(engine, "olivia@example.com")

    with pytest.raises(AuthError, match="Password must be at least"):
        reset_password_with_token(engine, token, "short")


def test_reset_password_clears_lockout(engine):
    register_user(engine, "peggy", "peggy@example.com", "correcthorse123")

    for _ in range(5):
        with pytest.raises(AuthError):
            authenticate(engine, "peggy", "wrong-password")
    with pytest.raises(AuthError, match="Too many failed attempts"):
        authenticate(engine, "peggy", "correcthorse123")

    token = generate_password_reset_token(engine, "peggy@example.com")
    reset_password_with_token(engine, token, "newpassword456")

    # Resetting the password should also lift the lockout -- otherwise
    # the account owner would regain a working password but still be
    # locked out from using it.
    logged_in = authenticate(engine, "peggy", "newpassword456")
    assert logged_in.username == "peggy"
