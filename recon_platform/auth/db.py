"""Auth persistence layer -- SQLAlchemy Core, no framework coupling.

Deliberately UI-framework-agnostic, same as
recon_platform/gateway/llm_gateway.py: this module takes a connection
URL as a plain argument rather than reading st.secrets itself, so it
stays testable without Streamlit installed and reusable if this project
ever gets a second frontend. demo_app.py is the one Streamlit-aware glue
layer that resolves DATABASE_URL from st.secrets and caches the engine
via @st.cache_resource.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine
from sqlalchemy.engine import Engine

metadata = MetaData()


def _utcnow() -> datetime:
    """Naive UTC now -- SQLite's default DateTime storage round-trips as
    naive, and comparing a naive value against an aware one raises
    TypeError. Standardizing on naive-UTC everywhere in this module
    avoids that mismatch across both the SQLite fallback and Postgres."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


users_table = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), unique=True, nullable=False),
    Column("email", String(255), unique=True, nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("created_at", DateTime, default=_utcnow),
    # Basic brute-force throttling (v1 scope). Deliberately deferred:
    # IP-based rate limiting, password reset flow, email verification --
    # see service.py's docstring.
    Column("failed_attempts", Integer, default=0, nullable=False),
    Column("locked_until", DateTime, nullable=True),
)

DEFAULT_SQLITE_PATH = "recofin_users.db"


def make_engine(database_url: str | None = None) -> Engine:
    """Create (and migrate) the auth engine.

    database_url=None falls back to a local SQLite file -- fine for
    local dev, but ephemeral on Streamlit Community Cloud (wiped on
    every redeploy, since the whole container rebuilds from git on each
    push). pool_pre_ping=True because both free-tier Postgres and
    Streamlit Cloud idle-sleep; without it the first query after a
    wake-up fails on a stale connection instead of transparently
    reconnecting.
    """
    url = database_url or f"sqlite:///{DEFAULT_SQLITE_PATH}"
    engine = create_engine(url, pool_pre_ping=True)
    metadata.create_all(engine)
    return engine


def is_ephemeral(database_url: str | None) -> bool:
    """True when running on the local-SQLite fallback rather than a
    configured external database. Callers use this to decide whether to
    warn about (or outright disable) registration -- an account created
    here vanishes on Streamlit Community Cloud's next redeploy, and
    silently accepting signups that then disappear is worse than
    blocking signup with an explanation."""
    return not database_url
