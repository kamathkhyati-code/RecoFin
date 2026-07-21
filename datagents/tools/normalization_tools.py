"""Normalization tools (A8/A9) - make transactions comparable before matching.
Converts amounts to a base currency (exact, via Decimal), resolves entity-name
variants to a canonical name (lookup -> cache -> optional LLM), and
canonicalizes reference codes. Together these let the matching step line up
book vs source.

A9: entity_alias_tool now checks a persistent AliasStore before calling the
LLM, and writes the LLM's answer back to the store. A second run against the
same store reads the cache and makes zero LLM calls for names it already
resolved.
"""
from __future__ import annotations
from decimal import ROUND_HALF_UP, Decimal
from datagents.schemas import Currency
from datagents.tools.alias_store import AliasStore
from recon_platform.gateway.llm_gateway import LLMGateway
from recon_platform.registry import registry
# Fixed demo FX rates: how many USD one unit of each currency is worth.
FX_TO_USD: dict[Currency, Decimal] = {
    Currency.USD: Decimal("1.00"),
    Currency.EUR: Decimal("1.10"),
    Currency.GBP: Decimal("1.27"),
    Currency.JPY: Decimal("0.0067"),
    Currency.CHF: Decimal("1.12"),
    Currency.CAD: Decimal("0.74"),
    Currency.AUD: Decimal("0.66"),
    Currency.INR: Decimal("0.012"),
}
# Known entity-name variants -> canonical name (keys are UPPER-cased).
ALIAS_TABLE: dict[str, str] = {
    "ACME": "ACME",
    "ACME-UK": "ACME",
    "ACME CORP": "ACME",
    "GLOBEX": "GLOBEX",
    "GLOBEX LLC": "GLOBEX",
    "INITECH": "INITECH",
    "UMBRELLA": "UMBRELLA",
}
_CENTS = Decimal("0.01")
@registry.register(
    "fx_rate_tool",
    description="Convert an amount to a base currency, exact to the cent.",
)
def fx_rate_tool(
    amount: Decimal,
    currency: Currency,
    base: Currency = Currency.USD,
) -> Decimal:
    """Convert `amount` in `currency` to `base`, rounded to the cent (Decimal-exact)."""
    in_usd = amount * FX_TO_USD[currency]
    in_base = in_usd / FX_TO_USD[base]
    return in_base.quantize(_CENTS, rounding=ROUND_HALF_UP)
@registry.register(
    "entity_alias_tool",
    description="Resolve an entity-name variant to its canonical name.",
)
def entity_alias_tool(
    name: str,
    gateway: LLMGateway | None = None,
    store: AliasStore | None = None,
) -> str:
    """Map a counterparty name to canonical form: table -> cache -> LLM."""
    key = name.strip().upper()
    if key in ALIAS_TABLE:
        return ALIAS_TABLE[key]
    if store is not None:
        cached = store.get(key)
        if cached is not None:
            return cached
    if gateway is not None:
        prompt = (
            "Return ONLY the canonical company name for this variant, "
            f"no extra text: {name}"
        )
        resolved = gateway.generate(prompt).strip()
        if store is not None:
            store.set(key, resolved)
        return resolved
    return name.strip()
@registry.register(
    "canonicalize_reference_tool",
    description="Put a reference code into canonical form (trim + upper).",
)
def canonicalize_reference(ref: str | None) -> str | None:
    """Trim whitespace and upper-case a reference code; None stays None."""
    if ref is None:
        return None
    return ref.strip().upper()
