from enum import Enum


class DotnetEnum(str, Enum):
    """An enum whose value is the C# member name (PascalCase), which is what the database stores.

    HTTP responses use the camelCase form (``wire``) and a few admin fields use the plain name, both
    matching what the C# server wrote, so the launcher and the dashboard keep working unchanged.
    """

    @property
    def wire(self) -> str:
        return self.value[0].lower() + self.value[1:]

    @property
    def rank(self) -> int:
        return list(type(self)).index(self)

    @classmethod
    def parse(cls, raw):
        """Case-insensitive name or member index, like System.Text.Json's string enum converter."""
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, int) and not isinstance(raw, bool):
            members = list(cls)
            if 0 <= raw < len(members):
                return members[raw]
        elif isinstance(raw, str):
            wanted = raw.strip().lower()
            for member in cls:
                if member.value.lower() == wanted:
                    return member
        names = ", ".join(m.wire for m in cls)
        raise ValueError(f"'{raw}' is not a valid {cls.__name__} ({names})")


class Severity(DotnetEnum):
    """Finding severity in ascending order. Info never makes a report dirty."""

    INFO = "Info"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class EnforcementMode(DotnetEnum):
    OBSERVE = "Observe"
    ENFORCE = "Enforce"


class DeviceStatus(DotnetEnum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class SessionDecision(DotnetEnum):
    GRANTED = "Granted"
    DENIED = "Denied"
    PENDING_APPROVAL = "PendingApproval"
    CONSENT_REQUIRED = "ConsentRequired"
    BANNED = "Banned"


class SessionState(DotnetEnum):
    ACTIVE = "Active"
    REVOKED = "Revoked"
    EXPIRED = "Expired"
    ENDED = "Ended"


class AccessGate(DotnetEnum):
    """The gates of a join request, in the order they are evaluated."""

    DEVICE = "Device"
    BAN = "Ban"
    DISCORD = "Discord"
    CONSENT = "Consent"
    ANTI_CHEAT = "AntiCheat"
    LEASE = "Lease"


class GateStatus(DotnetEnum):
    PASSED = "Passed"
    BLOCKED = "Blocked"
    BYPASSED = "Bypassed"


class DiscordRoleState(DotnetEnum):
    OK = "Ok"
    NOT_MEMBER = "NotMember"
    ROLE_MISSING = "RoleMissing"


class RiskBand(DotnetEnum):
    CLEAN = "Clean"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
