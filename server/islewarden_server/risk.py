"""Reduces a player's findings to one number that orders the admin review queue.

Three deliberate rules; keep them when changing this module:
1. Deduplicate by (code, day). The launcher sends a heartbeat every 30 seconds, so one finding repeats
   hundreds of times per session; counting every repeat would inflate the score meaninglessly.
2. Info severity scores zero. It is context (unreadable logs, Prefetch disabled...), not an accusation.
3. The score decays over time (default half-life 7 days), so last month's findings don't keep a player
   at high risk forever.

The score never blocks anyone. Blocking comes from EnforceThreshold in the session manager or from an admin.
"""

from dataclasses import dataclass, field
from datetime import date

from .enums import RiskBand, Severity
from .settings import RiskSettings


@dataclass(frozen=True)
class FindingBucket:
    """Findings deduplicated by (code, day). hits is for display only and never multiplies the score."""

    code: str
    severity: Severity
    day: date
    hits: int


@dataclass(frozen=True)
class RiskAssessment:
    score: int
    band: RiskBand
    # Lines explaining the score, so admins can see why and explain it to the player.
    reasons: list[str] = field(default_factory=list)


NO_RISK = RiskAssessment(0, RiskBand.CLEAN, [])


class RiskScorer:
    def __init__(self, options: RiskSettings | None = None):
        self._options = options or RiskSettings()

    def assess(self, buckets: list[FindingBucket], today: date) -> RiskAssessment:
        scored = [(b, self._weight(b.severity) * self._decay((today - b.day).days))
                  for b in buckets if self._weight(b.severity) > 0]
        if not scored:
            return NO_RISK

        score = int(round(min(100.0, sum(points for _, points in scored))))

        groups: dict[tuple[str, Severity], list[tuple[FindingBucket, float]]] = {}
        for bucket, points in scored:
            groups.setdefault((bucket.code, bucket.severity), []).append((bucket, points))

        summaries = []
        for (code, severity), items in groups.items():
            days = len({b.day for b, _ in items})
            last = max(b.day for b, _ in items)
            summaries.append((sum(p for _, p in items), f"{code} ({severity.value.lower()}) — {days} ngày, "
                                                        f"gần nhất {last:%d/%m}"))
        summaries.sort(key=lambda s: s[0], reverse=True)

        return RiskAssessment(score, self.band_of(score), [text for _, text in summaries[:4]])

    def band_of(self, score: int) -> RiskBand:
        if score <= 0:
            return RiskBand.CLEAN
        if score < self._options.low_ceiling:
            return RiskBand.LOW
        if score < self._options.medium_ceiling:
            return RiskBand.MEDIUM
        return RiskBand.HIGH

    def _decay(self, age_in_days: int) -> float:
        return 1.0 if age_in_days <= 0 else 0.5 ** (age_in_days / max(0.5, self._options.half_life_days))

    def _weight(self, severity: Severity) -> float:
        return {
            Severity.LOW: self._options.low_weight,
            Severity.MEDIUM: self._options.medium_weight,
            Severity.HIGH: self._options.high_weight,
            Severity.CRITICAL: self._options.critical_weight,
        }.get(severity, 0.0)
