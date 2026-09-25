from datetime import timedelta

import pytest
from helpers import finding

from islewarden_server.dashboard import DashboardStore, ReportFilter
from islewarden_server.db import Database
from islewarden_server.enums import RiskBand, Severity
from islewarden_server.records import BanSubject
from islewarden_server.risk import RiskScorer
from islewarden_server.store import Store
from islewarden_server.timeutil import iso, utc_now
from islewarden_server.wire import dumps

STEAM = "76561198000000001"


class DashboardFixture:
    def __init__(self, directory):
        self.database = Database(str(directory / "dashboard.db"))
        self.database.initialize()
        self.store = Store(self.database)
        self.dashboard = DashboardStore(self.database, RiskScorer())

    def report(self, steam_id, *findings, processes=None) -> int:
        return self.store.insert_report("session-1", "device-1", steam_id, not findings,
                                        dumps([f.to_json() for f in findings]),
                                        None if processes is None else dumps(processes))

    def backdate_report(self, report_id: int, days: int) -> None:
        when = iso(utc_now() - timedelta(days=days))
        with self.database.connect() as c:
            c.execute("UPDATE reports SET received_utc = ? WHERE id = ?", (when, report_id))
            c.execute("UPDATE findings SET received_utc = ? WHERE report_id = ?", (when, report_id))

    def execute(self, sql: str) -> None:
        with self.database.connect() as c:
            c.execute(sql)

    def count_evidence(self, ban_id: int) -> int:
        with self.database.connect() as c:
            return c.execute("SELECT COUNT(*) FROM ban_evidence WHERE ban_id = ?", (ban_id,)).fetchone()[0]


@pytest.fixture
def fx(tmp_path):
    return DashboardFixture(tmp_path)


def test_report_insert_also_fills_the_findings_table(fx):
    report_id = fx.report(STEAM,
                          finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy", "C:\\tools\\ce.exe"),
                          finding("executed-tool", Severity.MEDIUM, "Đã từng chạy: ISLEUNLOCKER.EXE"))

    report = fx.dashboard.get_report(report_id, include_processes=False)

    assert len(report.findings) == 2
    assert report.summary.worst_rank == 3  # High
    assert report.summary.top_code == "blocked-process"
    assert not report.summary.clean


def test_process_list_only_comes_back_when_explicitly_asked(fx):
    report_id = fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"),
                          processes=["chrome", "TheIsle", "notepad"])

    assert fx.dashboard.get_report(report_id, include_processes=False).processes is None
    assert len(fx.dashboard.get_report(report_id, include_processes=True).processes) == 3


def test_player_profile_groups_flagged_software_instead_of_repeating_every_heartbeat(fx):
    cheat = finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy", "C:\\tools\\ce.exe")
    for _ in range(20):
        fx.report(STEAM, cheat)

    player = fx.dashboard.get_player(STEAM, window_days=14)

    [software] = player.software
    assert software.hits == 20  # still counts all 20 hits
    assert software.message == "Cheat Engine đang chạy"
    [group] = player.findings
    assert group.hits == 20
    assert group.days == 1  # but only one distinct day
    assert player.risk.band == RiskBand.MEDIUM  # repetition doesn't inflate it to High


def test_unknown_player_has_no_profile(fx):
    assert fx.dashboard.get_player("76561198999999999", window_days=14) is None


def test_player_list_ranks_riskiest_first_and_keeps_clean_players_out(fx):
    fx.report("76561198000000002", finding("suspicious-process-name", Severity.LOW, "tên nghi vấn"))
    fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))
    fx.report("76561198000000003")  # clean

    players = fx.dashboard.list_players(window_days=14)

    assert players[0].steam_id == STEAM
    assert players[0].score > players[1].score
    assert all(p.steam_id != "76561198000000003" for p in players)  # no findings and no session: not listed


def test_report_filtering_by_code_and_severity(fx):
    fx.report(STEAM, finding("executed-tool", Severity.MEDIUM, "Đã từng chạy: X"))
    fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))
    fx.report(STEAM)

    assert len(fx.dashboard.list_reports(ReportFilter(steam_id=STEAM))) == 3
    assert len(fx.dashboard.list_reports(ReportFilter(only_dirty=True))) == 2
    assert len(fx.dashboard.list_reports(ReportFilter(code="executed-tool"))) == 1
    assert len(fx.dashboard.list_reports(ReportFilter(min_rank=Severity.HIGH.rank))) == 1
    assert fx.dashboard.list_reports(ReportFilter(steam_id="76561198000000009")) == []


def test_report_paging_and_limits(fx):
    ids = [fx.report(STEAM) for _ in range(5)]

    assert [r.id for r in fx.dashboard.list_reports(ReportFilter(limit=2))] == [ids[4], ids[3]]
    assert [r.id for r in fx.dashboard.list_reports(ReportFilter(before_id=ids[2]))] == [ids[1], ids[0]]
    assert len(fx.dashboard.list_reports(ReportFilter(limit=0))) == 1  # clamped to at least one


def test_watch_flag_follows_the_latest_action(fx):
    fx.report(STEAM, finding("suspicious-process-name", Severity.LOW, "tên nghi vấn"))

    fx.dashboard.insert_action("watch", BanSubject.STEAM_ID, STEAM, "rủi ro thấp, để mắt")
    assert fx.dashboard.get_player(STEAM, 14).watched

    fx.dashboard.insert_action("unwatch", BanSubject.STEAM_ID, STEAM, None)
    assert not fx.dashboard.get_player(STEAM, 14).watched


def test_pruning_old_reports_takes_their_findings_with_them(fx):
    old = fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))
    fresh = fx.report(STEAM, finding("executed-tool", Severity.MEDIUM, "Đã từng chạy: X"))
    fx.backdate_report(old, days=60)

    assert fx.dashboard.prune_reports(days=30) == 1
    assert fx.dashboard.get_report(old, False) is None
    assert fx.dashboard.get_report(fresh, False) is not None

    # The pruned report's findings go too (ON DELETE CASCADE), so they no longer count toward the score.
    [group] = fx.dashboard.get_player(STEAM, window_days=90).findings
    assert group.code == "executed-tool"


def test_evidence_survives_even_when_the_report_is_pruned(fx):
    report_id = fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))
    ban_id = fx.store.insert_ban(BanSubject.STEAM_ID, STEAM, "chạy Cheat Engine", None)
    fx.dashboard.link_evidence(ban_id, report_id, "blocked-process: Cheat Engine đang chạy")
    fx.backdate_report(report_id, days=60)
    fx.dashboard.prune_reports(days=30)

    assert fx.count_evidence(ban_id) == 1


def test_existing_reports_are_split_into_findings_on_upgrade(fx):
    report_id = fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))

    # A database from an older version: reports exist but the findings table is empty.
    fx.execute("DELETE FROM findings")
    assert fx.dashboard.get_report(report_id, False).findings == []

    fx.database.initialize()

    [row] = fx.dashboard.get_report(report_id, False).findings
    assert row.code == "blocked-process"
    assert row.severity == Severity.HIGH


def test_overview_counts_what_the_admin_needs_first(fx):
    fx.report(STEAM, finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy"))
    fx.store.insert_ban(BanSubject.STEAM_ID, "76561198000000004", "test", None)

    overview = fx.dashboard.overview(high_risk_window_days=14)

    assert overview.reports_last24h == 1
    assert overview.active_bans == 1
    assert overview.findings_last24h["high"] == 1
    assert overview.database_bytes > 0
