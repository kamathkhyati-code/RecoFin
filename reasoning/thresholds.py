"""Tuned matching thresholds (B16).

Confidence floor above which a match is safe to auto-apply without human
review. Tuned from the B15 eval: exact matches sit at 1.0, well-formed
tolerance/fuzzy matches on the golden set score comfortably above 0.85,
while a coincidental near-duplicate match (amount/date proximity with no
real reference support) scores well below it -- so 0.85 is the line that
separates "confident enough to auto-apply" from "needs a human look."
"""
from __future__ import annotations

from reasoning.schemas import MatchResult

AUTO_MATCH_THRESHOLD = 0.85


def is_auto_matchable(match: MatchResult, threshold: float = AUTO_MATCH_THRESHOLD) -> bool:
    """True if a match's confidence clears the auto-apply floor."""
    return match.confidence >= threshold


def split_auto_and_review(
    matches: list[MatchResult], threshold: float = AUTO_MATCH_THRESHOLD
) -> tuple[list[MatchResult], list[MatchResult]]:
    """Split matches into (auto-apply, needs-human-review) by confidence."""
    auto = [m for m in matches if is_auto_matchable(m, threshold)]
    review = [m for m in matches if not is_auto_matchable(m, threshold)]
    return auto, review
