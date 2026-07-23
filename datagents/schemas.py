"""Core data schemas for the data-agents pipeline (Intern A).

Reuses IssueRecord from recon_platform.state rather than redefining it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from recon_platform.state import IssueRecord


class SourceType(str, Enum):
    CSV = "csv"
    API = "api"
    SFTP = "sftp"


class Currency(str, Enum):
    """Supported settlement currencies (ISO 4217). Extend as golden data requires."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CHF = "CHF"
    CAD = "CAD"
    AUD = "AUD"
    INR = "INR"


class Transaction(BaseModel):
    """A single normalized financial transaction."""

    txn_id: str
    date: date
    amount: Decimal
    currency: Currency
    counterparty: str
    reference: str | None = None
    source: SourceType

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, v: object) -> object:
        # Uppercase/strip strings so "usd" -> Currency.USD; membership is
        # enforced by the Currency enum, which raises ValidationError on junk.
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("amount")
    @classmethod
    def amount_must_be_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite number")
        return v


class SourceConfig(BaseModel):
    """Configuration describing where and how to ingest one data source."""

    name: str
    source_type: SourceType
    location: str  # file path, URL, or SFTP path
    credentials_ref: str | None = None  # name of a secret, never the secret itself
    options: dict = Field(default_factory=dict)


class IngestResult(BaseModel):
    """Result returned by a source tool / the ingestion agent."""

    source_name: str
    transactions: list[Transaction] = Field(default_factory=list)
    issues: list[IssueRecord] = Field(default_factory=list)
    rows_read: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)
