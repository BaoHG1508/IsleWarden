"""Access control vocabulary: the independent gates, stable block codes, and the wording players see.

A join is never collapsed into "allowed / not allowed": when a player asks why they can't get in, the answer
must name the gate that blocks. See docs/ACCESS-CONTROL-REFERENCE.md.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from .enums import AccessGate, GateStatus, SessionState
from .models import Finding
from .records import BanRecord, SessionRecord


class AccessCodes:
    """Stable codes the launcher and admin tooling act on. Never change a released value; only add new ones."""

    DEVICE_UNKNOWN = "device-unknown"
    DEVICE_PENDING = "device-pending"
    DEVICE_REJECTED = "device-rejected"
    BANNED = "banned"
    DISCORD_NOT_LINKED = "discord-not-linked"
    DISCORD_NOT_MEMBER = "discord-not-member"
    DISCORD_ROLE_MISSING = "discord-role-missing"
    CONSENT_REQUIRED = "consent-required"
    ANTICHEAT_BLOCKED = "anticheat-blocked"
    # Lease codes stay apart from anti-cheat: a player dropped for lost heartbeats who reads "anti-cheat"
    # will assume they are suspected of cheating.
    LEASE_EXPIRED = "lease-expired"
    LEASE_REVOKED = "lease-revoked"
    LEASE_RELEASED = "lease-released"
    LEASE_INVALID = "lease-invalid"


class LoginCodes:
    """Why a login failed, returned in the error's "code". A missing Discord membership or role reuses
    AccessCodes.DISCORD_NOT_MEMBER / DISCORD_ROLE_MISSING."""

    EXPIRED = "login-expired"
    STEAM_FAILED = "steam-login-failed"
    DISCORD_FAILED = "discord-login-failed"
    DISCORD_LINKED_ELSEWHERE = "discord-linked-elsewhere"
    STEAM_LINKED_ELSEWHERE = "steam-linked-elsewhere"


@dataclass(frozen=True)
class GateResult:
    gate: AccessGate
    status: GateStatus
    note: str | None = None


@dataclass(frozen=True)
class AccessBlock:
    """Why a join was blocked or a lease ended. support_code: R-<report id> or B-<ban id>."""

    gate: AccessGate
    code: str
    label: str
    detail: str | None = None
    until: datetime | None = None
    support_code: str | None = None


# Built in one place so the launcher, the kick message and the dashboard use the same wording per code.


def device_unknown() -> AccessBlock:
    return AccessBlock(AccessGate.DEVICE, AccessCodes.DEVICE_UNKNOWN,
                       "Máy này chưa đăng nhập hoặc khoá thiết bị không hợp lệ.",
                       "Chạy lại lệnh login để đăng nhập Steam và Discord.")


def device_pending() -> AccessBlock:
    return AccessBlock(AccessGate.DEVICE, AccessCodes.DEVICE_PENDING, "Máy đang chờ admin duyệt.")


def device_rejected(detail: str | None = None) -> AccessBlock:
    return AccessBlock(AccessGate.DEVICE, AccessCodes.DEVICE_REJECTED, "Máy này đã bị admin từ chối.", detail)


def banned(ban: BanRecord) -> AccessBlock:
    label = "Bạn đang bị cấm vĩnh viễn." if ban.expires_utc is None else "Bạn đang bị cấm có thời hạn."
    return AccessBlock(AccessGate.BAN, AccessCodes.BANNED, label, ban.reason, ban.expires_utc, f"B-{ban.id}")


def discord_not_linked() -> AccessBlock:
    return AccessBlock(AccessGate.DISCORD, AccessCodes.DISCORD_NOT_LINKED,
                       "Steam ID này chưa liên kết tài khoản Discord.",
                       "Chạy lại lệnh login để đăng nhập Steam và Discord.")


def discord_not_member() -> AccessBlock:
    return AccessBlock(AccessGate.DISCORD, AccessCodes.DISCORD_NOT_MEMBER,
                       "Tài khoản Discord của bạn không ở trong Discord của server.",
                       "Vào lại Discord của server rồi thử lại.")


def discord_role_missing() -> AccessBlock:
    return AccessBlock(AccessGate.DISCORD, AccessCodes.DISCORD_ROLE_MISSING,
                       "Tài khoản Discord của bạn chưa có role được phép vào chơi.",
                       "Liên hệ admin trên Discord để được cấp role.")


def consent_required(version: str) -> AccessBlock:
    return AccessBlock(AccessGate.CONSENT, AccessCodes.CONSENT_REQUIRED,
                       "Nội dung thông báo đã thay đổi — cần đồng ý lại trước khi vào.", f"phiên bản {version}")


def anti_cheat(blocking: list[Finding], report_id: int) -> AccessBlock:
    """blocking: the findings at or above the threshold, so the player is told exactly what blocks them."""
    return AccessBlock(AccessGate.ANTI_CHEAT, AccessCodes.ANTICHEAT_BLOCKED,
                       "Phát hiện phần mềm không được phép trên máy. Tắt nó rồi thử lại.",
                       _summarize(blocking), support_code=f"R-{report_id}")


def lease_expired(grace: timedelta) -> AccessBlock:
    return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_EXPIRED,
                       "Mất tín hiệu launcher quá lâu — suất chơi đã hết hạn.",
                       f"không nhận được heartbeat trong {grace.total_seconds():.0f} giây")


def lease_revoked(reason: str | None) -> AccessBlock:
    return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_REVOKED, "Admin đã thu hồi suất chơi.", reason)


def lease_released(reason: str | None) -> AccessBlock:
    return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_RELEASED, "Launcher đã trả suất chơi.", reason)


def lease_invalid() -> AccessBlock:
    return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_INVALID, "Suất chơi không hợp lệ — hãy mở lại launcher.")


def stored_reason(block: AccessBlock) -> str | None:
    """What goes into sessions.end_reason: the detail, prefixed with the support code if any."""
    if block.support_code is None:
        return block.detail
    if block.detail is None:
        return f"[{block.support_code}]"
    return f"[{block.support_code}] {block.detail}"


def from_ended(session: SessionRecord) -> AccessBlock:
    """Rebuilds the reason for a finished session from its stored code and detail."""
    code, reason = session.end_code, session.end_reason
    if code == AccessCodes.BANNED:
        return AccessBlock(AccessGate.BAN, AccessCodes.BANNED, "Bạn đang bị cấm.", reason)
    if code == AccessCodes.ANTICHEAT_BLOCKED:
        return AccessBlock(AccessGate.ANTI_CHEAT, AccessCodes.ANTICHEAT_BLOCKED,
                           "Phát hiện phần mềm không được phép trên máy.", reason)
    if code == AccessCodes.DEVICE_REJECTED:
        return device_rejected(reason)
    if code == AccessCodes.DISCORD_NOT_LINKED:
        return discord_not_linked()
    if code == AccessCodes.DISCORD_NOT_MEMBER:
        return discord_not_member()
    if code == AccessCodes.DISCORD_ROLE_MISSING:
        return discord_role_missing()
    if code == AccessCodes.LEASE_EXPIRED:
        return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_EXPIRED,
                           "Mất tín hiệu launcher quá lâu — suất chơi đã hết hạn.", reason)
    if code == AccessCodes.LEASE_REVOKED:
        return lease_revoked(reason)
    if code == AccessCodes.LEASE_RELEASED:
        return lease_released(reason)

    # Sessions that ended before end codes existed: infer from the state.
    if session.state == SessionState.EXPIRED:
        return AccessBlock(AccessGate.LEASE, AccessCodes.LEASE_EXPIRED,
                           "Mất tín hiệu launcher quá lâu — suất chơi đã hết hạn.", reason)
    if session.state == SessionState.REVOKED:
        return lease_revoked(reason)
    return lease_released(reason)


def _summarize(findings: list[Finding]) -> str:
    text = "; ".join(f"{f.code}: {f.message}" for f in findings[:3])
    return f"{text} (+{len(findings) - 3} phát hiện khác)" if len(findings) > 3 else text
