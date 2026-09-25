from datetime import date, timedelta

from islewarden_server.enums import RiskBand, Severity
from islewarden_server.risk import FindingBucket, RiskScorer

TODAY = date(2026, 9, 25)
scorer = RiskScorer()


def bucket(code, severity, days_ago=0, hits=1):
    return FindingBucket(code, severity, TODAY - timedelta(days=days_ago), hits)


def test_no_findings_is_clean():
    risk = scorer.assess([], TODAY)
    assert (risk.score, risk.band) == (0, RiskBand.CLEAN)


def test_info_does_not_count():
    # An unreadable execution history is context, not an accusation.
    risk = scorer.assess([bucket("execution-history-unavailable", Severity.INFO, hits=500)], TODAY)
    assert (risk.score, risk.band) == (0, RiskBand.CLEAN)


def test_repeats_within_one_day_do_not_inflate_the_score():
    # A 30-second heartbeat repeats the same finding 360 times in a 3-hour session.
    once = scorer.assess([bucket("blocked-process", Severity.HIGH, hits=1)], TODAY)
    spammed = scorer.assess([bucket("blocked-process", Severity.HIGH, hits=360)], TODAY)
    assert once.score == spammed.score


def test_separate_days_add_up():
    one_day = scorer.assess([bucket("executed-tool", Severity.MEDIUM)], TODAY)
    three_days = scorer.assess([bucket("executed-tool", Severity.MEDIUM, d) for d in range(3)], TODAY)
    assert three_days.score > one_day.score


def test_older_findings_weigh_less():
    fresh = scorer.assess([bucket("blocked-process", Severity.HIGH)], TODAY)
    old = scorer.assess([bucket("blocked-process", Severity.HIGH, days_ago=14)], TODAY)
    assert 0 < old.score < fresh.score  # still counts, just less


def test_single_high_finding_needs_review_not_the_high_band():
    risk = scorer.assess([bucket("blocked-process", Severity.HIGH)], TODAY)
    assert risk.band == RiskBand.MEDIUM


def test_repeated_high_findings_across_days_reach_the_high_band():
    risk = scorer.assess([bucket("blocked-process", Severity.HIGH, 0), bucket("blocked-process", Severity.HIGH, 1),
                          bucket("executed-tool", Severity.MEDIUM, 2)], TODAY)
    assert risk.band == RiskBand.HIGH


def test_score_is_capped_at_100():
    assert scorer.assess([bucket("blocked-process", Severity.CRITICAL, d) for d in range(30)], TODAY).score == 100


def test_reasons_explain_the_score():
    risk = scorer.assess([bucket("executed-tool", Severity.MEDIUM, 0, hits=3),
                          bucket("executed-tool", Severity.MEDIUM, 1, hits=2)], TODAY)

    [reason] = risk.reasons
    assert "executed-tool" in reason
    assert "2 ngày" in reason  # grouped by day, not 5 hits
    assert reason == "executed-tool (medium) — 2 ngày, gần nhất 25/09"
