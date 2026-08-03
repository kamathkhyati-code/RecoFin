"""A15: labeled fixtures for the validation and normalization agents,
wired into C's eval harness (recon_platform/eval).

Validation fixtures cover every ReasonCode that can actually fire today.
UNSUPPORTED_CURRENCY is deliberately excluded: Fix #1 (sync fx_check_tool's
SUPPORTED_CURRENCIES with normalization's FX_TO_USD table) means every
value the Currency enum accepts is now supported, so that check can never
fire on a constructible Transaction -- it would be dead code represented
as a fixture, not a real label. AMBIGUOUS is exercised via a MockLLMGateway
(same pattern as A14), since it's the one reason code that only fires
through the LLM path, not a deterministic tool.

Normalization fixtures compare an exact serialized normalized-transaction
string against the expected one; run_eval's accuracy() metric over these
IS "normalization exactness" -- no new metric needed, reusing the harness
as-is.
"""
from __future__ import annotations

from recon_platform.eval.dataset import GoldenRecord

# ---- Validation fixtures ----
# Each record's input is {"batch": [txn field dicts...], "subject_txn_id":
# str, "use_mock_gateway": bool}. The "batch" lets DUPLICATE_TXN (which
# needs two rows sharing a txn_id) be expressed naturally, and lets
# completeness/format/dedupe all run through the real multi-row
# deterministic checks exactly as they do in the live graph, not a
# single-row simplification that would miss cross-row logic.

_CLEAN_ROW = {
    "txn_id": "T1", "date": "2026-01-15", "amount": "100.00",
    "currency": "USD", "counterparty": "ACME", "reference": "INV-1",
}


def build_validation_fixtures() -> list[GoldenRecord]:
    return [
        GoldenRecord(
            record_id="val_clean_row",
            input={"batch": [_CLEAN_ROW], "subject_txn_id": "T1", "use_mock_gateway": False},
            expected_label="OK",
        ),
        GoldenRecord(
            record_id="val_missing_field",
            input={
                "batch": [{**_CLEAN_ROW, "counterparty": ""}],
                "subject_txn_id": "T1",
                "use_mock_gateway": False,
            },
            expected_label="MISSING_FIELD",
        ),
        GoldenRecord(
            record_id="val_duplicate_txn",
            input={
                "batch": [
                    _CLEAN_ROW,
                    {**_CLEAN_ROW, "amount": "50.00"},  # same txn_id "T1", second occurrence
                ],
                "subject_txn_id": "T1",
                "use_mock_gateway": False,
            },
            expected_label="DUPLICATE_TXN",
        ),
        GoldenRecord(
            record_id="val_non_positive_amount",
            input={
                "batch": [{**_CLEAN_ROW, "amount": "0.00"}],
                "subject_txn_id": "T1",
                "use_mock_gateway": False,
            },
            expected_label="NON_POSITIVE_AMOUNT",
        ),
        GoldenRecord(
            record_id="val_ambiguous_no_reference",
            input={
                "batch": [{**_CLEAN_ROW, "reference": None}],
                "subject_txn_id": "T1",
                "use_mock_gateway": True,
            },
            expected_label="AMBIGUOUS",
        ),
    ]


# ---- Normalization fixtures ----
# Each record's input is a single txn's field dict (base currency always
# USD, no gateway/store -- entity_alias_tool falls back to name.strip()
# for anything not in ALIAS_TABLE, which is itself worth covering).

def build_normalization_fixtures() -> list[GoldenRecord]:
    return [
        GoldenRecord(
            record_id="norm_usd_alias_table_hit",
            input={
                "txn_id": "N1", "date": "2026-01-01", "amount": "100.00",
                "currency": "USD", "counterparty": "ACME CORP", "reference": "inv-1",
            },
            # USD->USD: unchanged amount. "ACME CORP" -> ALIAS_TABLE canonical "ACME".
            # reference trimmed+uppercased.
            expected_label='{"amount": "100.00", "currency": "USD", "counterparty": "ACME", "reference": "INV-1"}',
        ),
        GoldenRecord(
            record_id="norm_eur_fx_conversion",
            input={
                "txn_id": "N2", "date": "2026-01-01", "amount": "100.00",
                "currency": "EUR", "counterparty": "globex llc", "reference": None,
            },
            # 100.00 EUR * 1.10 = 110.00 USD. "globex llc" -> upper "GLOBEX LLC" -> ALIAS_TABLE "GLOBEX".
            expected_label='{"amount": "110.00", "currency": "USD", "counterparty": "GLOBEX", "reference": null}',
        ),
        GoldenRecord(
            record_id="norm_jpy_fx_rounding",
            input={
                "txn_id": "N3", "date": "2026-01-01", "amount": "1000",
                "currency": "JPY", "counterparty": "Random Co", "reference": "  po-55  ",
            },
            # 1000 * 0.0067 = 6.7000 -> quantized to 6.70. "Random Co" not in
            # ALIAS_TABLE -> falls back to name.strip() as-is (case preserved,
            # NOT uppercased -- only table hits get canonical-cased).
            # reference: trim + upper -> "PO-55".
            expected_label='{"amount": "6.70", "currency": "USD", "counterparty": "Random Co", "reference": "PO-55"}',
        ),
        GoldenRecord(
            record_id="norm_gbp_fx_conversion",
            input={
                "txn_id": "N4", "date": "2026-01-01", "amount": "200.00",
                "currency": "GBP", "counterparty": "Initech", "reference": None,
            },
            # 200.00 GBP * 1.27 = 254.00 USD. "Initech" -> upper "INITECH" -> in
            # ALIAS_TABLE -> "INITECH".
            expected_label='{"amount": "254.00", "currency": "USD", "counterparty": "INITECH", "reference": null}',
        ),
    ]
