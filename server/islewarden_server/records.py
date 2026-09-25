"""Database records. Serialized with wire.to_wire, so field names become the camelCase JSON the dashboard reads."""

from dataclasses import dataclass, field
from datetime import datetime

from .enums import DeviceStatus, DiscordRoleState, SessionState, Severity


class BanSubject:
    STEAM_ID = "steam_id"
    DEVICE = "device"
    COMPONENT = "component"

    ALL = (STEAM_ID, DEVICE, COMPONENT)


def is_identifying_component(kind: str) -> bool:
    """cpuId (ProcessorId) is the same on every CPU of one model, so banning or matching on it hits strangers."""
    return kind != "cpuId"


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    steam_id: str
    device_key_hash: str
    machine_name: str
    fingerprint_id: str | None
    status: DeviceStatus
    consent_version: str
    created_utc: datetime
    # Risk flag that held the device for admin review despite auto-approval; None = no flag.
    review_reason: str | None = None


@dataclass(frozen=True)
class DiscordLinkRecord:
    """The Discord account a Steam ID signed in with. One Discord account per Steam ID and vice versa."""

    steam_id: str
    discord_id: str
    discord_name: str
    linked_utc: datetime
    # Result of the last successful role check; reused while Discord can't be reached.
    role_state: DiscordRoleState
    checked_utc: datetime


@dataclass(frozen=True)
class BanRecord:
    id: int
    subject_type: str
    subject_value: str
    reason: str | None
    created_utc: datetime
    expires_utc: datetime | None


@dataclass(frozen=True)
class BypassRecord:
    """Admin-granted per Steam ID. Relaxes only the anti-cheat gate and device approval, never bans or consent."""

    steam_id: str
    reason: str
    created_utc: datetime
    expires_utc: datetime | None


@dataclass(frozen=True)
class SessionRecord:
    """A play lease, running or finished."""

    session_id: str
    device_id: str
    steam_id: str
    token_hash: str
    state: SessionState
    started_utc: datetime
    # Last heartbeat + grace period.
    expires_utc: datetime
    last_heartbeat_utc: datetime
    ended_utc: datetime | None
    # Access code saying why the session ended; None while it runs.
    end_code: str | None = None
    end_reason: str | None = None


@dataclass(frozen=True)
class FindingRow:
    """A finding flattened into the findings table; reports.findings_json stays the source of truth."""

    code: str
    severity: Severity
    message: str
    detail: str | None
    # The C# record exposed this computed property, so it is part of the JSON the dashboard receives.
    rank: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "rank", self.severity.rank)
