"""Learning Agent (B12) - mine recurring match/exception patterns into RuleSuggestions.

Looks at a run's confirmed matches and classified exceptions and proposes
concrete, bounded config changes: widen a tolerance, relax the fuzzy
threshold, flag a recurring exception pattern worth reviewing. Nothing
here changes matching behavior directly -- every suggestion goes to the
rule_store for approval; C12 wires approved ones back into config.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from reasoning.rule_store import RuleStore, rule_store
from reasoning.schemas import ExceptionRecord, MatchResult, RuleSuggestion

# Fewer than this many recurrences isn't a pattern, just noise.
_MIN_SUPPORT = 2


def _mine_tolerance_pattern(matches: list[MatchResult]) -> RuleSuggestion | None:
    tolerance_matches = [m for m in matches if m.rule == "tolerance"]
    if len(tolerance_matches) < _MIN_SUPPORT:
        return None

    deltas = [Decimal(m.metadata.get("amount_delta", "0")) for m in tolerance_matches]
    max_delta = max(deltas)
    avg_confidence = sum(m.confidence for m in tolerance_matches) / len(tolerance_matches)

    return RuleSuggestion(
        rule_type="widen_tolerance",
        description=(
            f"{len(tolerance_matches)} recurring tolerance matches observed; "
            f"consider widening amount_tol to cover a delta up to {max_delta}."
        ),
        suggested_params={"amount_tol": str(max_delta)},
        support_count=len(tolerance_matches),
        confidence=avg_confidence,
        rationale=(
            "Recurring pairs are matching via the tolerance strategy rather than "
            "exact, with amount deltas up to the observed maximum. Widening the "
            "tolerance could promote these to higher-confidence matches or catch "
            "similar pairs currently falling through to exceptions."
        ),
    )


def _mine_fuzzy_pattern(matches: list[MatchResult]) -> RuleSuggestion | None:
    fuzzy_matches = [m for m in matches if m.rule == "fuzzy"]
    if len(fuzzy_matches) < _MIN_SUPPORT:
        return None

    ratios = [m.metadata.get("similarity", 0.0) for m in fuzzy_matches]
    min_ratio_seen = min(ratios)
    avg_confidence = sum(m.confidence for m in fuzzy_matches) / len(fuzzy_matches)

    return RuleSuggestion(
        rule_type="lower_fuzzy_threshold",
        description=(
            f"{len(fuzzy_matches)} recurring fuzzy matches observed, with "
            f"reference similarity as low as {min_ratio_seen:.2f}."
        ),
        suggested_params={"min_ratio": round(min_ratio_seen, 2)},
        support_count=len(fuzzy_matches),
        confidence=avg_confidence,
        rationale=(
            "Recurring pairs are matching via fuzzy reference similarity; "
            "lowering min_ratio slightly could catch similar pairs earlier "
            "without a separate LLM escalation."
        ),
    )


def _mine_exception_pattern(exceptions: list[ExceptionRecord]) -> RuleSuggestion | None:
    counts = Counter(e.exc_type for e in exceptions)
    if not counts:
        return None

    exc_type, count = counts.most_common(1)[0]
    if count < _MIN_SUPPORT:
        return None

    return RuleSuggestion(
        rule_type="recurring_exception_pattern",
        description=f"{count} recurring '{exc_type.value}' exceptions observed.",
        suggested_params={"exc_type": exc_type.value},
        support_count=count,
        confidence=min(1.0, count / len(exceptions)),
        rationale=(
            f"'{exc_type.value}' is the most common exception type in this run "
            f"({count} occurrences). Worth reviewing whether classification or "
            f"upstream matching rules should adapt to catch this pattern."
        ),
    )


def learning_agent(
    matches: list[MatchResult],
    exceptions: list[ExceptionRecord],
    store: RuleStore | None = None,
) -> list[RuleSuggestion]:
    """Mine recurring patterns from a run's matches/exceptions into rule suggestions.

    Every suggestion found is both returned and persisted to the rule
    store, pending approval.
    """
    s = store if store is not None else rule_store

    suggestions: list[RuleSuggestion] = []
    for suggestion in (
        _mine_tolerance_pattern(matches),
        _mine_fuzzy_pattern(matches),
        _mine_exception_pattern(exceptions),
    ):
        if suggestion is not None:
            suggestions.append(suggestion)
            s.add(suggestion)

    return suggestions


def apply_approved_rules(store: RuleStore | None = None) -> dict[str, dict]:
    """C12: resolve approved rule suggestions into run_matching's tool_config.

    Multiple approved suggestions for the same tool are additive evidence
    that matching needs to be looser, never stricter -- take the most
    permissive (widest tolerance / lowest fuzzy threshold) across all of
    them, not just the latest.
    """
    s = store if store is not None else rule_store
    config: dict[str, dict] = {}

    for item in s.approved():
        suggestion = item.suggestion
        if suggestion.rule_type == "widen_tolerance":
            new_tol = Decimal(suggestion.suggested_params["amount_tol"])
            current = config.get("tolerance_tool", {}).get("amount_tol")
            if current is None or new_tol > current:
                config.setdefault("tolerance_tool", {})["amount_tol"] = new_tol
        elif suggestion.rule_type == "lower_fuzzy_threshold":
            new_ratio = suggestion.suggested_params["min_ratio"]
            current = config.get("fuzzy_tool", {}).get("min_ratio")
            if current is None or new_ratio < current:
                config.setdefault("fuzzy_tool", {})["min_ratio"] = new_ratio

    return config
