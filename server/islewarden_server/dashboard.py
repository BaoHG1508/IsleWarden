"""Queries behind the admin dashboard: overview, player profiles, report search, action log.

Kept apart from Store (the launcher's write path). The dataclasses below are the JSON the React dashboard
reads; dashboard/src/types.ts is its hand-maintained copy, so change both together.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import Database
from .enums import RiskBand, Severity
from .records import BanRecord, BypassRecord, DeviceRecord, DiscordLinkRecord, FindingRow, SessionRecord
from .risk import FindingBucket, RiskAssessment, RiskScorer
from .store import read_ban, read_bypass, read_device, read_discord_link, read_session
from .timeutil import MIN_UTC, iso, parse_iso, parse_iso_or_none, utc_now


@dataclass(frozen=True)
class OverviewSnapshot:
    active_sessions: int
    players_last24h: int
    reports_last24h: int
    findings_last24h: dict[str, int]
    pending_devices: int
    active_bans: int
    whitelisted: int
    high_risk_players: int
    report_count: int
    oldest_report_utc: datetime | None
    database_bytes: int


@dataclass(frozen=True)
class PlayerSummary:
    steam_id: str
    score: int
    band: RiskBand
    reasons: list[str]
    last_seen_utc: datetime | None
    sessions: int
    devices: int
    banned: bool
    whitelisted: bool
    watched: bool
    bypassed: bool
    discord_name: str | None


@dataclass(frozen=True)
class FlaggedSoftware:
    """One flagged piece of software, merged from identical findings."""

    code: str
    severity: str
    message: str
    detail: str | None
    hits: int
    first_utc: datetime
    last_utc: datetime


@dataclass(frozen=True)
class FindingGroup:
    code: str
    severity: str
    rank: int
    hits: int
    days: int
    first_utc: datetime
    last_utc: datetime


@dataclass(frozen=True)
class AdminActionRecord:
    id: int
    action: str
    subject_type: str
    subject_value: str
    note: str | None
    report_id: int | None
    created_utc: datetime


@dataclass(frozen=True)
class PlayerDetail:
    steam_id: str
    risk: RiskAssessment
    banned: bool
    whitelisted: bool
    watched: bool
    # Expired or not, so admins can renew or remove it.
    bypass: BypassRecord | None
    discord: DiscordLinkRecord | None
    devices: list[DeviceRecord]
    sessions: list[SessionRecord]
    findings: list[FindingGroup]
    software: list[FlaggedSoftware]
    bans: list[BanRecord]
    actions: list[AdminActionRecord]


@dataclass(frozen=True)
class ReportSummary:
    id: int
    received_utc: datetime
    steam_id: str
    device_id: str
    session_id: str
    clean: bool
    finding_count: int
    worst_rank: int
    top_code: str | None


@dataclass(frozen=True)
class ReportDetail:
    summary: ReportSummary
    findings: list[FindingRow]
    # Only present when an admin explicitly asks; see the reports endpoint.
    processes: list[str] | None


@dataclass(frozen=True)
class ReportFilter:
    steam_id: str | None = None
    code: str | None = None
    min_rank: int | None = None
    only_dirty: bool = False
    limit: int = 100
    before_id: int | None = None


_REPORT_COLUMNS = """
    SELECT r.id, r.received_utc, r.steam_id, r.device_id, r.session_id, r.clean,
           (SELECT COUNT(*) FROM findings f WHERE f.report_id = r.id) AS finding_count,
           (SELECT COALESCE(MAX(f.severity_rank), 0) FROM findings f WHERE f.report_id = r.id) AS worst,
           (SELECT f.code FROM findings f WHERE f.report_id = r.id ORDER BY f.severity_rank DESC LIMIT 1) AS top_code
    FROM reports r
"""


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class DashboardStore:
    def __init__(self, database: Database, scorer: RiskScorer):
        self._db = database
        self._scorer = scorer

    # ---- Overview ----

    def overview(self, high_risk_window_days: int) -> OverviewSnapshot:
        since = iso(utc_now() - timedelta(hours=24))
        now = iso(utc_now())
        with self._db.connect() as c:
            findings = {row[0]: row[1] for row in c.execute(
                "SELECT severity, COUNT(*) FROM findings WHERE received_utc >= ? GROUP BY severity", (since,))}
            oldest = _scalar(c, "SELECT MIN(received_utc) FROM reports")
            snapshot = dict(
                active_sessions=_scalar(c, "SELECT COUNT(*) FROM sessions WHERE state = 'Active'"),
                players_last24h=_scalar(
                    c, "SELECT COUNT(DISTINCT steam_id) FROM sessions WHERE started_utc >= ?", since),
                reports_last24h=_scalar(c, "SELECT COUNT(*) FROM reports WHERE received_utc >= ?", since),
                pending_devices=_scalar(c, "SELECT COUNT(*) FROM devices WHERE status = 'Pending'"),
                active_bans=_scalar(c, "SELECT COUNT(*) FROM bans WHERE expires_utc IS NULL OR expires_utc > ?", now),
                whitelisted=_scalar(c, "SELECT COUNT(*) FROM whitelist"),
                report_count=_scalar(c, "SELECT COUNT(*) FROM reports"),
                database_bytes=_scalar(
                    c, "SELECT (SELECT * FROM pragma_page_count()) * (SELECT * FROM pragma_page_size())"),
            )

        high_risk = sum(1 for p in self.list_players(high_risk_window_days, limit=500) if p.band == RiskBand.HIGH)
        return OverviewSnapshot(
            active_sessions=snapshot["active_sessions"],
            players_last24h=snapshot["players_last24h"],
            reports_last24h=snapshot["reports_last24h"],
            findings_last24h=findings,
            pending_devices=snapshot["pending_devices"],
            active_bans=snapshot["active_bans"],
            whitelisted=snapshot["whitelisted"],
            high_risk_players=high_risk,
            report_count=snapshot["report_count"],
            oldest_report_utc=parse_iso_or_none(oldest),
            database_bytes=snapshot["database_bytes"])

    # ---- Players ----

    def list_players(self, window_days: int, limit: int = 200) -> list[PlayerSummary]:
        since = iso(utc_now() - timedelta(days=max(1, window_days)))
        now = iso(utc_now())
        today = utc_now().date()

        with self._db.connect() as c:
            buckets = _read_buckets(c, since, steam_id=None)
            sessions = {row[0]: (row[1], parse_iso(row[2])) for row in c.execute(
                "SELECT steam_id, COUNT(*), MAX(started_utc) FROM sessions WHERE started_utc >= ? GROUP BY steam_id",
                (since,))}
            devices = {row[0]: row[1] for row in c.execute("SELECT steam_id, COUNT(*) FROM devices GROUP BY steam_id")}
            banned = _string_set(c, "SELECT DISTINCT subject_value FROM bans WHERE subject_type = 'steam_id' "
                                    "AND (expires_utc IS NULL OR expires_utc > ?)", now)
            whitelisted = _string_set(c, "SELECT steam_id FROM whitelist")
            watched = _watched_players(c)
            bypassed = _string_set(c, "SELECT steam_id FROM ac_bypass WHERE expires_utc IS NULL OR expires_utc > ?",
                                   now)
            discord_names = {row[0]: row[1] for row in c.execute("SELECT steam_id, discord_name FROM discord_links")}

        steam_ids = set(buckets) | set(sessions) | banned | watched | bypassed
        players = []
        for steam_id in steam_ids:
            risk = self._scorer.assess(buckets.get(steam_id, []), today)
            count, last_seen = sessions.get(steam_id, (0, None))
            players.append(PlayerSummary(
                steam_id, risk.score, risk.band, risk.reasons, last_seen if count else None, count,
                devices.get(steam_id, 0), steam_id in banned, steam_id in whitelisted, steam_id in watched,
                steam_id in bypassed, discord_names.get(steam_id)))

        players.sort(key=lambda p: (p.score, p.last_seen_utc or MIN_UTC), reverse=True)
        return players[:_clamp(limit, 1, 1000)]

    def get_player(self, steam_id: str, window_days: int) -> PlayerDetail | None:
        since = iso(utc_now() - timedelta(days=max(1, window_days)))
        today = utc_now().date()

        with self._db.connect() as c:
            devices = [read_device(row) for row in c.execute(
                "SELECT * FROM devices WHERE steam_id = ? ORDER BY created_utc DESC", (steam_id,))]
            buckets = _read_buckets(c, since, steam_id).get(steam_id, [])
            actions = _list_actions(c, steam_id, limit=50)

            # Never registered, no findings and no admin action: no profile.
            if not devices and not buckets and not actions:
                return None

            sessions = [read_session(row) for row in c.execute(
                "SELECT * FROM sessions WHERE steam_id = ? ORDER BY started_utc DESC LIMIT 25", (steam_id,))]

            findings = [FindingGroup(row[0], row[1], row[2], row[3], row[4], parse_iso(row[5]), parse_iso(row[6]))
                        for row in c.execute(
                            """
                            SELECT code, severity, severity_rank, COUNT(*) AS hits,
                                   COUNT(DISTINCT substr(received_utc, 1, 10)) AS days,
                                   MIN(received_utc) AS first_utc, MAX(received_utc) AS last_utc
                            FROM findings
                            WHERE steam_id = ? AND received_utc >= ?
                            GROUP BY code, severity, severity_rank
                            ORDER BY severity_rank DESC, last_utc DESC
                            """, (steam_id, since))]

            # Identical findings merged, so the admin sees *what* was flagged rather than hundreds of repeats
            # of the same tool from every heartbeat.
            software = [FlaggedSoftware(row[0], row[1], row[2], row[3], row[4], parse_iso(row[5]),
                                        parse_iso(row[6]))
                        for row in c.execute(
                            """
                            SELECT code, severity, message, detail, COUNT(*) AS hits,
                                   MIN(received_utc) AS first_utc, MAX(received_utc) AS last_utc
                            FROM findings
                            WHERE steam_id = ? AND received_utc >= ? AND severity_rank > 0
                            GROUP BY code, severity, message, detail
                            ORDER BY MAX(severity_rank) DESC, last_utc DESC
                            LIMIT 60
                            """, (steam_id, since))]

            bans = [read_ban(row) for row in c.execute(
                """
                SELECT * FROM bans
                WHERE (subject_type = 'steam_id' AND subject_value = :steam)
                   OR (subject_type = 'device' AND subject_value IN (SELECT device_id FROM devices WHERE steam_id = :steam))
                ORDER BY created_utc DESC
                """, {"steam": steam_id})]

            bypass_row = c.execute("SELECT * FROM ac_bypass WHERE steam_id = ?", (steam_id,)).fetchone()
            discord_row = c.execute("SELECT * FROM discord_links WHERE steam_id = ?", (steam_id,)).fetchone()
            whitelisted = c.execute("SELECT 1 FROM whitelist WHERE steam_id = ?", (steam_id,)).fetchone() is not None
            watched = steam_id in _watched_players(c)

        now = utc_now()
        active = any(b.expires_utc is None or b.expires_utc > now for b in bans)
        return PlayerDetail(
            steam_id, self._scorer.assess(buckets, today), active, whitelisted, watched,
            read_bypass(bypass_row) if bypass_row else None, read_discord_link(discord_row) if discord_row else None,
            devices, sessions, findings, software, bans, actions)

    # ---- Reports ----

    def list_reports(self, report_filter: ReportFilter) -> list[ReportSummary]:
        where, params = [], []
        if report_filter.steam_id and report_filter.steam_id.strip():
            where.append("r.steam_id = ?")
            params.append(report_filter.steam_id.strip())
        if report_filter.only_dirty:
            where.append("r.clean = 0")
        if report_filter.code and report_filter.code.strip():
            where.append("EXISTS (SELECT 1 FROM findings f WHERE f.report_id = r.id AND f.code = ?)")
            params.append(report_filter.code.strip())
        if report_filter.min_rank is not None:
            where.append("EXISTS (SELECT 1 FROM findings f WHERE f.report_id = r.id AND f.severity_rank >= ?)")
            params.append(report_filter.min_rank)
        if report_filter.before_id is not None:
            where.append("r.id < ?")
            params.append(report_filter.before_id)

        sql = _REPORT_COLUMNS + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT ?"
        params.append(_clamp(report_filter.limit, 1, 500))
        with self._db.connect() as c:
            return [_read_report_summary(row) for row in c.execute(sql, params)]

    def get_report(self, report_id: int, include_processes: bool) -> ReportDetail | None:
        with self._db.connect() as c:
            row = c.execute(_REPORT_COLUMNS + " WHERE r.id = ?", (report_id,)).fetchone()
            if row is None:
                return None
            findings = [FindingRow(r[0], Severity.parse(r[1]), r[2], r[3]) for r in c.execute(
                "SELECT code, severity, message, detail FROM findings WHERE report_id = ? ORDER BY severity_rank DESC",
                (report_id,))]
            processes = None
            if include_processes:
                processes = _parse_processes(_scalar(c, "SELECT processes_json FROM reports WHERE id = ?", report_id))
        return ReportDetail(_read_report_summary(row), findings, processes)

    # ---- Admin action log ----

    def insert_action(self, action: str, subject_type: str, subject_value: str, note: str | None,
                      report_id: int | None = None) -> int:
        with self._db.connect() as c:
            return c.execute(
                "INSERT INTO admin_actions (action, subject_type, subject_value, note, report_id, created_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (action, subject_type, subject_value, note, report_id, iso(utc_now()))).lastrowid

    def list_actions(self, limit: int = 100) -> list[AdminActionRecord]:
        with self._db.connect() as c:
            return _list_actions(c, None, limit)

    def link_evidence(self, ban_id: int, report_id: int | None, summary: str) -> None:
        """Links a report as grounds for a ban; the summary outlives the report when retention prunes it."""
        with self._db.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO ban_evidence (ban_id, report_id, summary, created_utc) VALUES (?, ?, ?, ?)",
                (ban_id, report_id, summary, iso(utc_now())))

    # ---- Maintenance ----

    def prune_reports(self, days: int) -> int:
        """Deletes reports older than `days`; their findings go too (ON DELETE CASCADE)."""
        cutoff = iso(utc_now() - timedelta(days=max(1, days)))
        with self._db.connect() as c:
            deleted = c.execute("DELETE FROM reports WHERE received_utc < ?", (cutoff,)).rowcount
            if deleted > 0:
                c.execute("PRAGMA incremental_vacuum")
        return deleted


def _read_buckets(c: sqlite3.Connection, since: str, steam_id: str | None) -> dict[str, list[FindingBucket]]:
    """Findings grouped by (player, code, day): the unit the risk score counts."""
    sql = """
        SELECT steam_id, code, severity, substr(received_utc, 1, 10) AS day, COUNT(*) AS hits
        FROM findings
        WHERE received_utc >= ? AND severity_rank > 0
    """
    params: list = [since]
    if steam_id is not None:
        sql += " AND steam_id = ?"
        params.append(steam_id)
    sql += " GROUP BY steam_id, code, severity, day"

    result: dict[str, list[FindingBucket]] = {}
    for row in c.execute(sql, params):
        bucket = FindingBucket(row[1], Severity.parse(row[2]), date.fromisoformat(row[3]), row[4])
        result.setdefault(row[0], []).append(bucket)
    return result


def _watched_players(c: sqlite3.Connection) -> set[str]:
    """A player is watched when their latest watch/unwatch action is "watch"."""
    return _string_set(c, """
        SELECT subject_value FROM admin_actions
        WHERE action = 'watch' AND id IN (
            SELECT MAX(id) FROM admin_actions
            WHERE action IN ('watch', 'unwatch') AND subject_type = 'steam_id'
            GROUP BY subject_value)
    """)


def _list_actions(c: sqlite3.Connection, subject_value: str | None, limit: int) -> list[AdminActionRecord]:
    sql = "SELECT id, action, subject_type, subject_value, note, report_id, created_utc FROM admin_actions"
    params: list = []
    if subject_value is not None:
        sql += " WHERE subject_value = ?"
        params.append(subject_value)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(_clamp(limit, 1, 500))
    return [AdminActionRecord(row[0], row[1], row[2], row[3], row[4], row[5], parse_iso(row[6]))
            for row in c.execute(sql, params)]


def _parse_processes(stored: str | None) -> list[str]:
    try:
        processes = json.loads(stored) if stored else []
    except ValueError:
        return []
    return [str(p) for p in processes] if isinstance(processes, list) else []


def _read_report_summary(row: sqlite3.Row) -> ReportSummary:
    return ReportSummary(row[0], parse_iso(row[1]), row[2], row[3], row[4], row[5] != 0, row[6], row[7], row[8])


def _scalar(c: sqlite3.Connection, sql: str, *params):
    row = c.execute(sql, params).fetchone()
    return None if row is None else row[0]


def _string_set(c: sqlite3.Connection, sql: str, *params) -> set[str]:
    return {row[0] for row in c.execute(sql, params)}
