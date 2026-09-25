"""Core workflow: device registration, and granting, renewing and ending play leases.

A join request passes INDEPENDENT gates in order (device, ban, Discord, consent, anti-cheat) and whichever gate
blocks returns its own code, so the player learns what is actually blocking them. A lease that ends carries its
own code too: lost heartbeats, admin revoke, launcher release, ban, lost Discord role, anti-cheat.

An anti-cheat bypass is admin-granted per Steam ID and relaxes exactly two things: the anti-cheat gate (at
join and on every heartbeat) and device approval. It never relaxes bans, rejected devices, the Discord role or
consent. It is looked up by the Steam ID that owns the requesting device on every call; the launcher holds no
flag, so one player's bypass can't be carried to another account.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from . import access, crypto
from .access import AccessBlock, GateResult
from .crypto import Crypto
from .discord import DiscordNotifier
from .enums import AccessGate, DeviceStatus, EnforcementMode, GateStatus, SessionDecision, SessionState
from .login.discord_gate import JOIN_MAX_AGE, DiscordGate
from .models import DeviceFingerprint, Finding, HeartbeatRequest, Policy, ScanReport, SessionEndRequest, \
    SessionStartRequest
from .policy import PolicyProvider
from .records import BanRecord, BanSubject, BypassRecord, DeviceRecord, SessionRecord, is_identifying_component
from .settings import Settings
from .store import Store
from .timeutil import utc_now
from .whitelist import WhitelistBridge
from .wire import dumps

log = logging.getLogger("islewarden.sessions")

MAX_RELEASE_REASON_LENGTH = 64


@dataclass(frozen=True)
class DeviceRegistration:
    device_id: str
    # Returned to the launcher exactly once; only its hash is stored.
    device_key: str
    steam_id: str
    status: DeviceStatus


@dataclass(frozen=True)
class SessionStartResponse:
    """When granted, session_id + token are the play lease, separate from the device key (the identity)."""

    decision: SessionDecision
    session_id: str | None = None
    token: str | None = None
    expires_utc: datetime | None = None
    heartbeat_seconds: int = 30
    message: str | None = None
    block: AccessBlock | None = None
    # The gates evaluated, in order; stops at the first one that blocks.
    gates: list[GateResult] = field(default_factory=list)
    # Time left on the lease is expires_utc - server_time; never compare with the player's own clock.
    server_time: datetime | None = None


@dataclass(frozen=True)
class HeartbeatResponse:
    state: SessionState
    expires_utc: datetime | None = None
    message: str | None = None
    block: AccessBlock | None = None
    server_time: datetime | None = None
    # Reports are still recorded, but findings never end the lease.
    anti_cheat_bypassed: bool = False


class SessionManager:
    def __init__(self, settings: Settings, store: Store, crypto_: Crypto, policies: PolicyProvider,
                 whitelist: WhitelistBridge, discord: DiscordNotifier, discord_gate: DiscordGate):
        self._settings = settings
        self._store = store
        self._crypto = crypto_
        self._policies = policies
        self._whitelist = whitelist
        self._discord = discord
        self._discord_gate = discord_gate

    def register_device(self, steam_id: str, machine_name: str, consent_version: str,
                        fingerprint: DeviceFingerprint | None) -> DeviceRegistration:
        """Issues a device key to a Steam ID that just signed in. A machine this Steam ID registered before keeps
        its record (only the key is replaced), so signing in again never resets a pending or rejected device."""
        device_key = crypto.new_secret()
        fingerprint_id = None if fingerprint is None else fingerprint.device_id
        components = None if fingerprint is None else {
            kind: self._crypto.hash_component(kind, value) for kind, value in fingerprint.components.items()}

        existing = self._find_own_device(steam_id, fingerprint_id, components)
        if existing is not None:
            self._store.rekey_device(existing.device_id, crypto.hash_token(device_key), machine_name, fingerprint_id,
                                     consent_version, components)
            log.info("Steam %s đăng nhập lại trên thiết bị %s (%s).", steam_id, existing.device_id,
                     existing.status.value)
            return DeviceRegistration(existing.device_id, device_key, steam_id, existing.status)

        device_id = crypto.new_id()
        # Auto-approval suits a small server, but a flagged device always waits for an admin.
        review = self._find_review_reason(steam_id, components)
        status = (DeviceStatus.APPROVED if self._settings.auto_approve_devices and review is None
                  else DeviceStatus.PENDING)

        self._store.insert_device(
            DeviceRecord(device_id, steam_id, crypto.hash_token(device_key), machine_name, fingerprint_id, status,
                         consent_version, utc_now(), review),
            components)

        log.info("Đăng ký thiết bị %s cho Steam %s (%s)%s.", device_id, steam_id, status.value,
                 "" if review is None else f" — cần xem: {review}")
        if review is not None:
            self._discord.notify_event(f"🔎 Máy mới cần duyệt: Steam `{steam_id}` — {review}")

        # The player is not told why: naming the flag would coach ban evaders.
        return DeviceRegistration(device_id, device_key, steam_id, status)

    def start_session(self, request: SessionStartRequest) -> SessionStartResponse:
        now = utc_now()
        gates: list[GateResult] = []

        # 1. Device: valid key, not rejected, approved (or approval bypassed).
        device = self._store.get_device(request.device_id)
        if device is None or not crypto.verify_token(request.device_key, device.device_key_hash):
            return _blocked(SessionDecision.DENIED, gates, access.device_unknown(), now)
        if device.status == DeviceStatus.REJECTED:
            return _blocked(SessionDecision.DENIED, gates, access.device_rejected(), now)

        bypass = self._find_bypass(device.steam_id)
        if device.status == DeviceStatus.PENDING:
            if bypass is None:
                return _blocked(SessionDecision.PENDING_APPROVAL, gates, access.device_pending(), now)
            gates.append(GateResult(AccessGate.DEVICE, GateStatus.BYPASSED, "miễn trừ: bỏ qua bước duyệt máy"))
        else:
            gates.append(GateResult(AccessGate.DEVICE, GateStatus.PASSED))

        # 2. Ban. A bypass never relaxes this gate.
        ban = self._find_ban(device)
        if ban is not None:
            self._discord.notify_event(
                f"⛔ Chặn theo ban list: Steam `{device.steam_id}` — {ban.reason or ban.subject_type} (B-{ban.id})")
            return _blocked(SessionDecision.BANNED, gates, access.banned(ban), now)
        gates.append(GateResult(AccessGate.BAN, GateStatus.PASSED))

        # 3. Discord role. A bypass never relaxes this gate either.
        if self._discord_gate.enabled:
            discord_block, link = self._discord_gate.check(device.steam_id, JOIN_MAX_AGE)
            if discord_block is not None:
                return _blocked(SessionDecision.DENIED, gates, discord_block, now)
            gates.append(GateResult(AccessGate.DISCORD, GateStatus.PASSED, None if link is None else link.discord_name))

        # 4. Consent: the current disclosure must be accepted before the server stores any scan data.
        policy = self._policies.get_policy()
        if request.consent_version != policy.disclosure_version:
            return _blocked(SessionDecision.CONSENT_REQUIRED, gates,
                            access.consent_required(policy.disclosure_version), now)
        gates.append(GateResult(AccessGate.CONSENT, GateStatus.PASSED, policy.disclosure_version))

        # 5. Anti-cheat. The session id exists up front so the report is filed under it, granted or not.
        session_id = crypto.new_id()
        report_id = self._store_report(session_id, device, request.report)
        self._discord.notify_findings(device.steam_id, request.report, bypass is not None)

        blocking = self._blocking_findings(policy, request.report)
        if blocking:
            if bypass is None:
                return _blocked(SessionDecision.DENIED, gates, access.anti_cheat(blocking, report_id), now)
            gates.append(GateResult(AccessGate.ANTI_CHEAT, GateStatus.BYPASSED, f"miễn trừ: {bypass.reason}"))
        else:
            gates.append(GateResult(AccessGate.ANTI_CHEAT, GateStatus.PASSED,
                                    "chế độ observe — chỉ ghi nhận, không chặn"
                                    if policy.mode == EnforcementMode.OBSERVE else None))

        token = crypto.new_secret()
        expires = now + self._settings.lease_grace
        self._store.insert_session(SessionRecord(session_id, device.device_id, device.steam_id,
                                                 crypto.hash_token(token), SessionState.ACTIVE, now, expires, now,
                                                 None))

        self._whitelist.grant(device.steam_id)
        log.info("Cấp suất chơi %s cho Steam %s%s.", session_id, device.steam_id,
                 "" if bypass is None else " (miễn trừ anti-cheat)")

        return SessionStartResponse(SessionDecision.GRANTED, session_id, token, expires,
                                    self._settings.heartbeat_seconds, gates=gates, server_time=now)

    def heartbeat(self, request: HeartbeatRequest) -> HeartbeatResponse:
        now = utc_now()
        session = self._store.get_session(request.session_id)
        if session is None or not crypto.verify_token(request.token, session.token_hash):
            return _ended(SessionState.ENDED, access.lease_invalid(), now)
        if session.state != SessionState.ACTIVE:
            return _ended(session.state, access.from_ended(session), now)

        device = self._store.get_device(session.device_id)
        bypass = self._find_bypass(session.steam_id)
        report_id = self._store_report(session.session_id, device, request.report, session.steam_id)
        self._discord.notify_findings(session.steam_id, request.report, bypass is not None)

        # An admin may ban or reject the device mid-session, or the new scan may find a violation.
        if device is not None:
            ban = self._find_ban(device)
            if ban is not None:
                return self.revoke(session, access.banned(ban))
            if device.status == DeviceStatus.REJECTED:
                return self.revoke(session, access.device_rejected())
        if self._discord_gate.enabled:
            discord_block, _ = self._discord_gate.check(session.steam_id, self._discord_gate.recheck_interval)
            if discord_block is not None:
                return self.revoke(session, discord_block)

        blocking = self._blocking_findings(self._policies.get_policy(), request.report)
        if blocking and bypass is None:
            return self.revoke(session, access.anti_cheat(blocking, report_id))

        expires = now + self._settings.lease_grace
        if not self._store.try_renew_session(session.session_id, now, expires):
            # Ended concurrently (sweeper, admin) while this heartbeat was being handled.
            ended = self._store.get_session(session.session_id) or session
            return _ended(ended.state, access.from_ended(ended), now)

        if request.resumed:
            log.info("Launcher nối lại suất chơi %s (Steam %s) sau %.0f giây không tín hiệu.", session.session_id,
                     session.steam_id, (now - session.last_heartbeat_utc).total_seconds())

        return HeartbeatResponse(SessionState.ACTIVE, expires, server_time=now,
                                 anti_cheat_bypassed=bypass is not None)

    def end_session(self, request: SessionEndRequest) -> None:
        """The launcher hands the lease back: end it now and drop the whitelist instead of waiting for expiry."""
        session = self._store.get_session(request.session_id)
        if session is None or not crypto.verify_token(request.token, session.token_hash):
            return

        reason = request.reason.strip() if request.reason and request.reason.strip() else None
        if reason is not None:
            reason = reason[:MAX_RELEASE_REASON_LENGTH]

        block = access.lease_released(reason)
        if not self._store.try_end_session(session.session_id, SessionState.ENDED, block.code, block.detail,
                                           utc_now()):
            return

        self._remove_whitelist_if_last(session, block)
        log.info("Launcher trả suất chơi %s (Steam %s): %s", session.session_id, session.steam_id,
                 reason or "không nêu lý do")

    def revoke(self, session: SessionRecord, block: AccessBlock) -> HeartbeatResponse:
        """Ends a lease (ban, anti-cheat, admin); drops the whitelist unless another lease is still active."""
        now = utc_now()
        if self._store.try_end_session(session.session_id, SessionState.REVOKED, block.code,
                                       access.stored_reason(block), now):
            self._remove_whitelist_if_last(session, block)
            self._discord.notify_event(
                f"🚫 Thu hồi suất chơi Steam `{session.steam_id}` — [{block.code}] {block.detail or block.label}")
            log.warning("Thu hồi suất chơi %s (Steam %s): [%s] %s", session.session_id, session.steam_id,
                        block.code, block.detail or block.label)
        return _ended(SessionState.REVOKED, block, now)

    def expire(self, session: SessionRecord, stale_before: datetime) -> None:
        """Expires a lease whose heartbeats stopped past the grace period. stale_before is the sweeper's cutoff:
        a session renewed after it is left alone."""
        block = access.lease_expired(self._settings.lease_grace)
        if not self._store.try_end_session(session.session_id, SessionState.EXPIRED, block.code, block.detail,
                                           utc_now(), stale_before):
            return

        self._remove_whitelist_if_last(session, block)
        self._discord.notify_event(f"⌛ Mất tín hiệu launcher — gỡ whitelist Steam `{session.steam_id}`")
        log.info("Suất chơi %s hết hạn do mất heartbeat (Steam %s).", session.session_id, session.steam_id)

    def _remove_whitelist_if_last(self, session: SessionRecord, block: AccessBlock) -> None:
        """A launcher that restarted and took a new lease while the old one was still valid must not drop the
        player, so the whitelist (and the kick, if enabled) only goes with the Steam ID's last active lease."""
        if self._store.has_other_active_session(session.steam_id, session.session_id):
            return
        self._whitelist.revoke(session.steam_id)
        self._whitelist.kick(session.steam_id, block.label)

    def _find_own_device(self, steam_id: str, fingerprint_id: str | None,
                         components: dict[str, str] | None) -> DeviceRecord | None:
        """This Steam ID's earlier record of the same machine: same fingerprint, else the device sharing the most
        identifying components (a replaced NIC or disk still counts as the same machine)."""
        devices = self._store.list_devices_of_steam_id(steam_id)  # newest first
        if fingerprint_id is not None and fingerprint_id != "UNKNOWN":
            same = next((d for d in devices if d.fingerprint_id == fingerprint_id), None)
            if same is not None:
                return same
        if components is None:
            return None

        identifying = {(kind, value) for kind, value in components.items() if is_identifying_component(kind)}
        shared = [(device, sum(1 for pair in self._store.get_device_components(device.device_id)
                               if pair in identifying))
                  for device in devices]
        shared = [(device, count) for device, count in shared if count > 0]
        if not shared:
            return None
        return max(shared, key=lambda pair: (pair[1], pair[0].created_utc))[0]

    def _find_bypass(self, steam_id: str) -> BypassRecord | None:
        return self._store.find_active_bypass(steam_id) if self._settings.allow_anti_cheat_bypass else None

    def _find_review_reason(self, steam_id: str, components: dict[str, str] | None) -> str | None:
        """Risk flags that hold a new device for review even under auto-approval: no fingerprint (can't be
        banned by hardware), or hardware shared with a banned account's device or another Steam ID's."""
        identifying = [(kind, value) for kind, value in (components or {}).items()
                       if is_identifying_component(kind)]
        if not identifying:
            return "không có fingerprint phần cứng — không ban theo máy được"

        matches = self._store.find_devices_sharing_components(steam_id, identifying)
        if not matches:
            return None

        def kinds(owner: str) -> str:
            return ", ".join(dict.fromkeys(kind for _, sid, kind in matches if sid == owner))

        for device_id, owner, _ in matches:
            if self._store.find_active_ban([(BanSubject.STEAM_ID, owner), (BanSubject.DEVICE, device_id)]):
                return f"trùng linh kiện ({kinds(owner)}) với máy của tài khoản đang bị ban {owner}"

        other = matches[0][1]
        return f"trùng linh kiện ({kinds(other)}) với máy đã đăng ký cho Steam ID {other}"

    def _find_ban(self, device: DeviceRecord) -> BanRecord | None:
        subjects = [(BanSubject.STEAM_ID, device.steam_id), (BanSubject.DEVICE, device.device_id)]
        subjects += [(BanSubject.COMPONENT, value_hash)
                     for kind, value_hash in self._store.get_device_components(device.device_id)
                     if is_identifying_component(kind)]
        return self._store.find_active_ban(subjects)

    def _blocking_findings(self, policy: Policy, report: ScanReport) -> list[Finding]:
        """Findings at or above the block threshold; always empty in Observe mode."""
        if policy.mode != EnforcementMode.ENFORCE:
            return []
        threshold = self._settings.enforce_threshold.rank
        blocking = [f for f in report.findings if f.severity.rank >= threshold]
        return sorted(blocking, key=lambda f: f.severity.rank, reverse=True)

    def _store_report(self, session_id: str, device: DeviceRecord | None, report: ScanReport,
                      steam_id: str | None = None) -> int:
        findings_json = dumps([f.to_json() for f in report.findings])
        processes_json = None if report.processes is None else dumps(report.processes)
        return self._store.insert_report(
            session_id, device.device_id if device else "?",
            device.steam_id if device else (steam_id or "?"), report.clean, findings_json, processes_json)


def _blocked(decision: SessionDecision, gates: list[GateResult], block: AccessBlock,
             now: datetime) -> SessionStartResponse:
    gates.append(GateResult(block.gate, GateStatus.BLOCKED))
    return SessionStartResponse(decision, message=block.label, block=block, gates=gates, server_time=now)


def _ended(state: SessionState, block: AccessBlock, now: datetime) -> HeartbeatResponse:
    return HeartbeatResponse(state, message=block.label, block=block, server_time=now)
