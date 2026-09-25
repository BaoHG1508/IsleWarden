"""Data access for the launcher's path: devices, Discord links, bans, bypasses, leases, reports, whitelist."""

import sqlite3
from datetime import datetime
from typing import Iterable

from .db import Database, insert_finding, parse_findings, transaction
from .enums import DeviceStatus, DiscordRoleState, SessionState
from .records import BanRecord, BypassRecord, DeviceRecord, DiscordLinkRecord, SessionRecord
from .timeutil import iso, parse_iso, parse_iso_or_none, utc_now


def _now() -> str:
    return iso(utc_now())


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else iso(value)


class Store:
    def __init__(self, database: Database):
        self._db = database

    # ---- Devices ----

    def insert_device(self, device: DeviceRecord, component_hashes: dict[str, str] | None) -> None:
        with self._db.connect() as c, transaction(c):
            c.execute(
                """
                INSERT INTO devices (device_id, steam_id, device_key_hash, machine_name, fingerprint_id, status,
                                     consent_version, created_utc, review_reason)
                VALUES (:id, :steam, :key, :machine, :fp, :status, :consent, :created, :review)
                """,
                {"id": device.device_id, "steam": device.steam_id, "key": device.device_key_hash,
                 "machine": device.machine_name, "fp": device.fingerprint_id, "status": device.status.value,
                 "consent": device.consent_version, "created": iso(device.created_utc),
                 "review": device.review_reason})
            for kind, value_hash in (component_hashes or {}).items():
                c.execute(
                    "INSERT OR REPLACE INTO device_components (device_id, kind, value_hash) VALUES (?, ?, ?)",
                    (device.device_id, kind, value_hash))

    def get_device(self, device_id: str) -> DeviceRecord | None:
        with self._db.connect() as c:
            row = c.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return read_device(row) if row else None

    def set_device_status(self, device_id: str, status: DeviceStatus) -> None:
        with self._db.connect() as c:
            c.execute("UPDATE devices SET status = ? WHERE device_id = ?", (status.value, device_id))

    def list_devices(self, status: DeviceStatus | None = None) -> list[DeviceRecord]:
        with self._db.connect() as c:
            if status is None:
                rows = c.execute("SELECT * FROM devices ORDER BY created_utc DESC").fetchall()
            else:
                rows = c.execute("SELECT * FROM devices WHERE status = ? ORDER BY created_utc DESC",
                                 (status.value,)).fetchall()
        return [read_device(row) for row in rows]

    def list_devices_of_steam_id(self, steam_id: str) -> list[DeviceRecord]:
        with self._db.connect() as c:
            rows = c.execute("SELECT * FROM devices WHERE steam_id = ? ORDER BY created_utc DESC",
                             (steam_id,)).fetchall()
        return [read_device(row) for row in rows]

    def rekey_device(self, device_id: str, device_key_hash: str, machine_name: str, fingerprint_id: str | None,
                     consent_version: str, component_hashes: dict[str, str] | None) -> None:
        """A device its owner signed in from again: new key hash and fresh fingerprint; status, review reason and
        creation time are kept."""
        with self._db.connect() as c, transaction(c):
            c.execute(
                "UPDATE devices SET device_key_hash = ?, machine_name = ?, fingerprint_id = ?, consent_version = ? "
                "WHERE device_id = ?",
                (device_key_hash, machine_name, fingerprint_id, consent_version, device_id))
            if component_hashes is not None:
                c.execute("DELETE FROM device_components WHERE device_id = ?", (device_id,))
                for kind, value_hash in component_hashes.items():
                    c.execute("INSERT INTO device_components (device_id, kind, value_hash) VALUES (?, ?, ?)",
                              (device_id, kind, value_hash))

    def get_device_components(self, device_id: str) -> list[tuple[str, str]]:
        with self._db.connect() as c:
            rows = c.execute("SELECT kind, value_hash FROM device_components WHERE device_id = ?",
                             (device_id,)).fetchall()
        return [(row[0], row[1]) for row in rows]

    def find_devices_sharing_components(self, except_steam_id: str,
                                        components: Iterable[tuple[str, str]]) -> list[tuple[str, str, str]]:
        """(device_id, steam_id, kind) of OTHER Steam IDs' devices sharing a hashed component with the list."""
        components = list(components)
        if not components:
            return []
        predicates = " OR ".join("(c.kind = ? AND c.value_hash = ?)" for _ in components)
        params = [value for pair in components for value in pair] + [except_steam_id]
        with self._db.connect() as c:
            rows = c.execute(
                f"""
                SELECT d.device_id, d.steam_id, c.kind
                FROM device_components c JOIN devices d ON d.device_id = c.device_id
                WHERE ({predicates}) AND d.steam_id <> ?
                ORDER BY d.created_utc
                """, params).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    # ---- Discord links ----

    def get_discord_link(self, steam_id: str) -> DiscordLinkRecord | None:
        return self._query_discord_link("SELECT * FROM discord_links WHERE steam_id = ?", steam_id)

    def get_discord_link_by_discord_id(self, discord_id: str) -> DiscordLinkRecord | None:
        return self._query_discord_link("SELECT * FROM discord_links WHERE discord_id = ?", discord_id)

    def upsert_discord_link(self, link: DiscordLinkRecord) -> None:
        """Creates or refreshes a Steam ID's link. A Discord account already linked to another Steam ID raises
        sqlite3.IntegrityError (UNIQUE) instead of silently moving the link."""
        with self._db.connect() as c:
            c.execute(
                """
                INSERT INTO discord_links (steam_id, discord_id, discord_name, linked_utc, role_state, checked_utc)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(steam_id) DO UPDATE SET
                    discord_id = excluded.discord_id, discord_name = excluded.discord_name,
                    role_state = excluded.role_state, checked_utc = excluded.checked_utc
                """,
                (link.steam_id, link.discord_id, link.discord_name, iso(link.linked_utc), link.role_state.value,
                 iso(link.checked_utc)))

    def update_discord_role_state(self, steam_id: str, state: DiscordRoleState, checked_utc: datetime) -> None:
        with self._db.connect() as c:
            c.execute("UPDATE discord_links SET role_state = ?, checked_utc = ? WHERE steam_id = ?",
                      (state.value, iso(checked_utc), steam_id))

    def delete_discord_link(self, steam_id: str) -> bool:
        with self._db.connect() as c:
            return c.execute("DELETE FROM discord_links WHERE steam_id = ?", (steam_id,)).rowcount == 1

    def _query_discord_link(self, sql: str, value: str) -> DiscordLinkRecord | None:
        with self._db.connect() as c:
            row = c.execute(sql, (value,)).fetchone()
        return read_discord_link(row) if row else None

    # ---- Bans ----

    def insert_ban(self, subject_type: str, subject_value: str, reason: str | None,
                   expires_utc: datetime | None) -> int:
        with self._db.connect() as c:
            cursor = c.execute(
                "INSERT INTO bans (subject_type, subject_value, reason, created_utc, expires_utc) VALUES (?, ?, ?, ?, ?)",
                (subject_type, subject_value, reason, _now(), _iso_or_none(expires_utc)))
            return cursor.lastrowid

    def find_active_ban(self, subjects: Iterable[tuple[str, str]]) -> BanRecord | None:
        """First unexpired ban matching any of the (type, value) subjects."""
        subjects = list(subjects)
        if not subjects:
            return None
        predicates = " OR ".join("(subject_type = ? AND subject_value = ?)" for _ in subjects)
        params = [value for pair in subjects for value in pair] + [_now()]
        with self._db.connect() as c:
            row = c.execute(
                f"SELECT * FROM bans WHERE ({predicates}) AND (expires_utc IS NULL OR expires_utc > ?) "
                "ORDER BY created_utc LIMIT 1", params).fetchone()
        return read_ban(row) if row else None

    def list_bans(self) -> list[BanRecord]:
        with self._db.connect() as c:
            rows = c.execute("SELECT * FROM bans ORDER BY created_utc DESC").fetchall()
        return [read_ban(row) for row in rows]

    def delete_ban(self, ban_id: int) -> bool:
        with self._db.connect() as c:
            return c.execute("DELETE FROM bans WHERE id = ?", (ban_id,)).rowcount == 1

    # ---- Anti-cheat bypass ----

    def upsert_bypass(self, bypass: BypassRecord) -> None:
        """One bypass per Steam ID; granting again replaces it."""
        with self._db.connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO ac_bypass (steam_id, reason, created_utc, expires_utc) VALUES (?, ?, ?, ?)",
                (bypass.steam_id, bypass.reason, iso(bypass.created_utc), _iso_or_none(bypass.expires_utc)))

    def delete_bypass(self, steam_id: str) -> bool:
        with self._db.connect() as c:
            return c.execute("DELETE FROM ac_bypass WHERE steam_id = ?", (steam_id,)).rowcount == 1

    def find_active_bypass(self, steam_id: str) -> BypassRecord | None:
        with self._db.connect() as c:
            row = c.execute(
                "SELECT * FROM ac_bypass WHERE steam_id = ? AND (expires_utc IS NULL OR expires_utc > ?)",
                (steam_id, _now())).fetchone()
        return read_bypass(row) if row else None

    def list_bypasses(self) -> list[BypassRecord]:
        """Every bypass, expired ones included, so admins can see and clean them up."""
        with self._db.connect() as c:
            rows = c.execute("SELECT * FROM ac_bypass ORDER BY created_utc DESC").fetchall()
        return [read_bypass(row) for row in rows]

    # ---- Sessions ----

    def insert_session(self, session: SessionRecord) -> None:
        with self._db.connect() as c:
            c.execute(
                """
                INSERT INTO sessions (session_id, device_id, steam_id, token_hash, state, started_utc, expires_utc,
                                      last_heartbeat_utc, ended_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (session.session_id, session.device_id, session.steam_id, session.token_hash, session.state.value,
                 iso(session.started_utc), iso(session.expires_utc), iso(session.last_heartbeat_utc)))

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._db.connect() as c:
            row = c.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return read_session(row) if row else None

    def try_renew_session(self, session_id: str, heartbeat_utc: datetime, expires_utc: datetime) -> bool:
        """False if the session is no longer Active (it just ended concurrently)."""
        with self._db.connect() as c:
            cursor = c.execute(
                "UPDATE sessions SET last_heartbeat_utc = ?, expires_utc = ? WHERE session_id = ? AND state = 'Active'",
                (iso(heartbeat_utc), iso(expires_utc), session_id))
            return cursor.rowcount == 1

    def try_end_session(self, session_id: str, state: SessionState, end_code: str, end_reason: str | None,
                        ended_utc: datetime, stale_before: datetime | None = None) -> bool:
        """Ends the session only while it is still Active, so concurrent end paths (sweeper, admin, heartbeat)
        never overwrite each other's reason or drop the whitelist twice. True if this call ended it.

        stale_before: end it only if the last heartbeat is older than this, so the sweeper doesn't expire a
        lease renewed after it read its list.
        """
        sql = ("UPDATE sessions SET state = ?, ended_utc = ?, end_code = ?, end_reason = ? "
               "WHERE session_id = ? AND state = 'Active'")
        params: list = [state.value, iso(ended_utc), end_code, end_reason, session_id]
        if stale_before is not None:
            sql += " AND last_heartbeat_utc < ?"
            params.append(iso(stale_before))
        with self._db.connect() as c:
            return c.execute(sql, params).rowcount == 1

    def list_active_sessions(self) -> list[SessionRecord]:
        with self._db.connect() as c:
            rows = c.execute("SELECT * FROM sessions WHERE state = 'Active' ORDER BY started_utc").fetchall()
        return [read_session(row) for row in rows]

    def has_other_active_session(self, steam_id: str, except_session_id: str) -> bool:
        """Decides whether ending one lease should drop the player from the whitelist."""
        with self._db.connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM sessions WHERE steam_id = ? AND state = 'Active' AND session_id <> ?",
                (steam_id, except_session_id)).fetchone()[0]
        return count > 0

    # ---- Reports ----

    def insert_report(self, session_id: str, device_id: str, steam_id: str, clean: bool, findings_json: str,
                      processes_json: str | None = None) -> int:
        """Stores the raw findings JSON and splits each finding into the findings table for the dashboard.
        Returns the report id, shown to blocked players as a support code and usable as ban evidence.
        """
        received_utc = _now()
        with self._db.connect() as c, transaction(c):
            report_id = c.execute(
                """
                INSERT INTO reports (session_id, device_id, steam_id, clean, findings_json, processes_json, received_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, device_id, steam_id, 1 if clean else 0, findings_json, processes_json,
                 received_utc)).lastrowid
            for finding in parse_findings(findings_json):
                insert_finding(c, finding, report_id, steam_id, received_utc)
        return report_id

    # ---- Whitelist ----

    def add_to_whitelist(self, steam_id: str) -> None:
        with self._db.connect() as c:
            c.execute("INSERT OR IGNORE INTO whitelist (steam_id, added_utc) VALUES (?, ?)", (steam_id, _now()))

    def remove_from_whitelist(self, steam_id: str) -> None:
        with self._db.connect() as c:
            c.execute("DELETE FROM whitelist WHERE steam_id = ?", (steam_id,))

    def list_whitelist(self) -> list[str]:
        with self._db.connect() as c:
            return [row[0] for row in c.execute("SELECT steam_id FROM whitelist ORDER BY added_utc")]


# ---- Row readers (shared with the dashboard queries) ----


def read_device(row: sqlite3.Row) -> DeviceRecord:
    return DeviceRecord(row["device_id"], row["steam_id"], row["device_key_hash"], row["machine_name"],
                        row["fingerprint_id"], DeviceStatus.parse(row["status"]), row["consent_version"],
                        parse_iso(row["created_utc"]), row["review_reason"])


def read_ban(row: sqlite3.Row) -> BanRecord:
    return BanRecord(row["id"], row["subject_type"], row["subject_value"], row["reason"],
                     parse_iso(row["created_utc"]), parse_iso_or_none(row["expires_utc"]))


def read_discord_link(row: sqlite3.Row) -> DiscordLinkRecord:
    return DiscordLinkRecord(row["steam_id"], row["discord_id"], row["discord_name"], parse_iso(row["linked_utc"]),
                             DiscordRoleState.parse(row["role_state"]), parse_iso(row["checked_utc"]))


def read_bypass(row: sqlite3.Row) -> BypassRecord:
    return BypassRecord(row["steam_id"], row["reason"], parse_iso(row["created_utc"]),
                        parse_iso_or_none(row["expires_utc"]))


def read_session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(row["session_id"], row["device_id"], row["steam_id"], row["token_hash"],
                         SessionState.parse(row["state"]), parse_iso(row["started_utc"]),
                         parse_iso(row["expires_utc"]), parse_iso(row["last_heartbeat_utc"]),
                         parse_iso_or_none(row["ended_utc"]), row["end_code"], row["end_reason"])
