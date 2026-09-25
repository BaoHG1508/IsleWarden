"""SQLite schema and connections. The schema is the one the C# server created, so either server can open the
same database file. WAL mode: concurrent readers, one writer; each operation opens its own connection.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from pydantic import ValidationError

from .models import Finding
from .records import FindingRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id       TEXT PRIMARY KEY,
    steam_id        TEXT NOT NULL,
    device_key_hash TEXT NOT NULL,
    machine_name    TEXT NOT NULL,
    fingerprint_id  TEXT,
    status          TEXT NOT NULL,
    consent_version TEXT NOT NULL,
    created_utc     TEXT NOT NULL,
    review_reason   TEXT
);
CREATE INDEX IF NOT EXISTS ix_devices_steam ON devices(steam_id);

-- Each hashed fingerprint component, so a single part (e.g. one MAC) can be banned.
CREATE TABLE IF NOT EXISTS device_components (
    device_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    PRIMARY KEY (device_id, kind),
    FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_components_hash ON device_components(kind, value_hash);

-- The Discord account each Steam ID signed in with, and the last role check. One-to-one both ways.
CREATE TABLE IF NOT EXISTS discord_links (
    steam_id     TEXT PRIMARY KEY,
    discord_id   TEXT NOT NULL UNIQUE,
    discord_name TEXT NOT NULL,
    linked_utc   TEXT NOT NULL,
    role_state   TEXT NOT NULL,
    checked_utc  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type  TEXT NOT NULL,
    subject_value TEXT NOT NULL,
    reason        TEXT,
    created_utc   TEXT NOT NULL,
    expires_utc   TEXT
);
CREATE INDEX IF NOT EXISTS ix_bans_subject ON bans(subject_type, subject_value);

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    device_id         TEXT NOT NULL,
    steam_id          TEXT NOT NULL,
    token_hash        TEXT NOT NULL,
    state             TEXT NOT NULL,
    started_utc       TEXT NOT NULL,
    expires_utc       TEXT NOT NULL,
    last_heartbeat_utc TEXT NOT NULL,
    ended_utc         TEXT,
    end_code          TEXT,
    end_reason        TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_state ON sessions(state);
CREATE INDEX IF NOT EXISTS ix_sessions_steam ON sessions(steam_id);

-- Anti-cheat bypass per Steam ID (streamers, staff...). Admin-granted only; stops applying once expired.
CREATE TABLE IF NOT EXISTS ac_bypass (
    steam_id    TEXT PRIMARY KEY,
    reason      TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    expires_utc TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    device_id    TEXT NOT NULL,
    steam_id     TEXT NOT NULL,
    clean        INTEGER NOT NULL,
    findings_json TEXT NOT NULL,
    processes_json TEXT,
    received_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reports_session ON reports(session_id);

-- Findings split out of findings_json so they can be searched and aggregated.
-- Deleting a report deletes its findings (ON DELETE CASCADE).
CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL,
    steam_id      TEXT NOT NULL,
    code          TEXT NOT NULL,
    severity      TEXT NOT NULL,
    severity_rank INTEGER NOT NULL,
    message       TEXT NOT NULL,
    detail        TEXT,
    received_utc  TEXT NOT NULL,
    FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_findings_steam ON findings(steam_id, received_utc);
CREATE INDEX IF NOT EXISTS ix_findings_code ON findings(code, received_utc);
CREATE INDEX IF NOT EXISTS ix_findings_report ON findings(report_id);

-- Every admin action: what was done, when, and on which evidence.
CREATE TABLE IF NOT EXISTS admin_actions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    action       TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_value TEXT NOT NULL,
    note         TEXT,
    report_id    INTEGER,
    created_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_actions_subject ON admin_actions(subject_type, subject_value);

-- Reports used as grounds for a ban. The summary is kept so the evidence survives
-- after the original report is pruned by retention.
CREATE TABLE IF NOT EXISTS ban_evidence (
    ban_id    INTEGER NOT NULL,
    report_id INTEGER,
    summary   TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    PRIMARY KEY (ban_id, report_id)
);

-- Desired whitelist state (what gets synced to the game server).
CREATE TABLE IF NOT EXISTS whitelist (
    steam_id  TEXT PRIMARY KEY,
    added_utc TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: autocommit; multi-statement writes use transaction() explicitly.
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            _migrate(connection)
            _backfill_findings(connection)


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    # IMMEDIATE takes the write lock up front, so two writers wait on busy_timeout instead of deadlocking.
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def parse_findings(findings_json: str) -> list[FindingRow]:
    """Parses stored findings; malformed JSON yields no rows instead of failing the whole report."""
    try:
        items = json.loads(findings_json)
        if not isinstance(items, list):
            return []
        findings = [Finding.model_validate(item) for item in items]
    except (ValueError, ValidationError):
        return []
    return [FindingRow(f.code, f.severity, f.message, f.detail) for f in findings]


def insert_finding(connection: sqlite3.Connection, row: FindingRow, report_id: int, steam_id: str,
                   received_utc: str) -> None:
    connection.execute(
        """
        INSERT INTO findings (report_id, steam_id, code, severity, severity_rank, message, detail, received_utc)
        VALUES (:report, :steam, :code, :severity, :rank, :message, :detail, :received)
        """,
        {"report": report_id, "steam": steam_id, "code": row.code, "severity": row.severity.value.lower(),
         "rank": row.rank, "message": row.message, "detail": row.detail, "received": received_utc})


def _migrate(connection: sqlite3.Connection) -> None:
    """Adds columns to databases created by older versions (CREATE TABLE IF NOT EXISTS leaves them alone)."""
    _add_column_if_missing(connection, "reports", "processes_json", "TEXT")
    _add_column_if_missing(connection, "devices", "review_reason", "TEXT")
    _add_column_if_missing(connection, "sessions", "end_code", "TEXT")
    _add_column_if_missing(connection, "sessions", "end_reason", "TEXT")


def _add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    exists = connection.execute(
        f"SELECT COUNT(*) FROM pragma_table_info('{table}') WHERE name = ?", (column,)).fetchone()[0]
    if not exists:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _backfill_findings(connection: sqlite3.Connection) -> None:
    """Splits reports stored before the findings table existed. Runs only while that table is empty."""
    done = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM findings) OR NOT EXISTS(SELECT 1 FROM reports)").fetchone()[0]
    if done:
        return

    rows = connection.execute("SELECT id, steam_id, findings_json, received_utc FROM reports").fetchall()
    with transaction(connection):
        for row in rows:
            for finding in parse_findings(row["findings_json"]):
                insert_finding(connection, finding, row["id"], row["steam_id"], row["received_utc"])
