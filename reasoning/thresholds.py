"""Tuned matching thresholds (B16).

Confidence floor above which a match is safe to auto-apply without human
review. Tuned from the B15 eval: exact and fuzzy matches sit comfortably
above 0.85 (exact is always 1.0; fuzzy on the golden set scores ~0.94),
while a coincidental near-duplicate match (amount/date proximity with no
real reference support) scores well below it -- so 0.85 is the line that
separates "confident enough to auto-apply" from "needs a human look."

Correction (post-C20 audit): tolerance matches do NOT reliably clear
0.85, and that's deliberate, not an oversight -- confidence is
round(0.6 + 0.35 * amt_score * date_score, 4) (matching_tools.py), so
any drift that consumes a meaningful fraction of the amount/date
tolerance budget stays well under the auto-apply floor by design (the
golden set's TL1/TL2 score 0.635/0.67, not "comfortably above 0.85" as
this docstring previously and incorrectly claimed). At realistic scale
(a 7,000-match synthetic run) roughly 55% of tolerance matches clear the
floor, driving an overall ~83% auto-match rate -- lower than an
unverified 90%+ claim, but the honest, measured number, and not
something to inflate by loosening this threshold without re-running the
adversarial suite it's tuned against.
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
