"""Access control, modelled on docs/ACCESS-CONTROL-REFERENCE.md: independent gates that each block with their
own code, a lease kept apart from device identity, and a bypass that relaxes exactly what it should."""

import re
from datetime import timedelta

from fake_rcon import FakeEvrimaRconServer
from helpers import COMMON_CPU, AccessFixture, finding

from islewarden_server import access as blocks
from islewarden_server import rcon
from islewarden_server.access import AccessCodes
from islewarden_server.enums import (AccessGate, DeviceStatus, EnforcementMode, GateStatus, SessionDecision,
                                     SessionState, Severity)
from islewarden_server.models import SessionEndRequest
from islewarden_server.records import BanSubject
from islewarden_server.timeutil import utc_now

PLAYER = "76561198000000011"
STREAMER = "76561198000000012"
OTHER = "76561198000000013"

CHEAT_ENGINE = finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy")


# ---- Gates ----


def test_clean_join_passes_every_gate_in_order(access):
    start = access.start(access.register(PLAYER))

    assert start.decision == SessionDecision.GRANTED
    assert start.block is None
    assert [g.gate for g in start.gates] == [AccessGate.DEVICE, AccessGate.BAN, AccessGate.CONSENT,
                                             AccessGate.ANTI_CHEAT]
    assert all(g.status == GateStatus.PASSED for g in start.gates)
    assert access.store.list_whitelist() == [PLAYER]


def test_finding_over_the_threshold_blocks_at_the_anti_cheat_gate_with_a_report_support_code(access):
    start = access.start(access.register(PLAYER), CHEAT_ENGINE)

    assert start.decision == SessionDecision.DENIED
    assert start.block.gate == AccessGate.ANTI_CHEAT
    assert start.block.code == AccessCodes.ANTICHEAT_BLOCKED
    assert "blocked-process" in start.block.detail
    assert re.fullmatch(r"R-\d+", start.block.support_code)
    assert start.gates[-1].status == GateStatus.BLOCKED
    assert access.store.list_whitelist() == []


def test_observe_mode_records_findings_but_never_blocks(tmp_path):
    f = AccessFixture(tmp_path, EnforcementMode.OBSERVE)

    start = f.start(f.register(PLAYER), CHEAT_ENGINE)

    assert start.decision == SessionDecision.GRANTED
    assert next(g for g in start.gates if g.gate == AccessGate.ANTI_CHEAT).status == GateStatus.PASSED


def test_ban_is_reported_at_the_ban_gate_with_its_expiry_and_support_code(access):
    device = access.register(PLAYER)
    until = utc_now() + timedelta(days=3)
    ban_id = access.store.insert_ban(BanSubject.STEAM_ID, PLAYER, "aimbot", until)

    start = access.start(device)

    assert start.decision == SessionDecision.BANNED
    assert start.block.gate == AccessGate.BAN
    assert start.block.code == AccessCodes.BANNED
    assert start.block.detail == "aimbot"
    assert start.block.until == until
    assert start.block.support_code == f"B-{ban_id}"


def test_outdated_consent_is_its_own_gate(access):
    start = access.start(access.register(PLAYER), consent_version="old-version")

    assert start.decision == SessionDecision.CONSENT_REQUIRED
    assert start.block.code == AccessCodes.CONSENT_REQUIRED
    assert start.block.gate == AccessGate.CONSENT


def test_component_ban_on_cpu_id_does_not_block_everyone_with_that_cpu_model(access):
    # ProcessorId is the same on every CPU of one model; an old "ban all components" entry on it must not
    # lock out unrelated players.
    device = access.register(PLAYER, {"machineGuid": "guid-player", "cpuId": COMMON_CPU})
    cpu_hash = next(h for kind, h in access.store.get_device_components(device.device_id) if kind == "cpuId")
    access.store.insert_ban(BanSubject.COMPONENT, cpu_hash, "ban cũ theo mọi linh kiện", None)

    assert access.start(device).decision == SessionDecision.GRANTED


# ---- Lease ----


def test_lease_expiry_is_the_grace_period_measured_on_the_server_clock(tmp_path):
    def configure(s):
        s.heartbeat_seconds = 30
        s.missed_heartbeat_grace = 2.5

    f = AccessFixture(tmp_path, configure=configure)
    start = f.start(f.register(PLAYER))
    heartbeat = f.heartbeat(start)

    assert start.expires_utc - start.server_time == timedelta(seconds=75)
    assert heartbeat.expires_utc - heartbeat.server_time == timedelta(seconds=75)


def test_finding_mid_session_revokes_with_the_anti_cheat_code_and_keeps_saying_why(access):
    start = access.start(access.register(PLAYER))

    revoked = access.heartbeat(start, CHEAT_ENGINE)
    later = access.heartbeat(start)

    assert revoked.state == SessionState.REVOKED
    assert revoked.block.code == AccessCodes.ANTICHEAT_BLOCKED
    assert re.fullmatch(r"R-\d+", revoked.block.support_code)
    assert later.block.code == AccessCodes.ANTICHEAT_BLOCKED  # rebuilt from what was stored
    assert access.session(start).end_code == AccessCodes.ANTICHEAT_BLOCKED
    assert access.store.list_whitelist() == []


def test_admin_revoke_reaches_the_launcher_with_its_own_code_not_anti_cheat(access):
    start = access.start(access.register(PLAYER))

    access.sessions.revoke(access.session(start), blocks.lease_revoked("spam chat"))
    heartbeat = access.heartbeat(start)

    assert heartbeat.state == SessionState.REVOKED
    assert heartbeat.block.gate == AccessGate.LEASE
    assert heartbeat.block.code == AccessCodes.LEASE_REVOKED
    assert heartbeat.block.detail == "spam chat"


def test_release_ends_the_lease_at_once_with_the_launchers_reason_capped_at_64_chars(access):
    start = access.start(access.register(PLAYER))

    access.sessions.end_session(SessionEndRequest(session_id=start.session_id, token=start.token, reason="x" * 100))

    session = access.session(start)
    assert session.state == SessionState.ENDED
    assert session.end_code == AccessCodes.LEASE_RELEASED
    assert len(session.end_reason) == 64
    assert access.store.list_whitelist() == []


def test_expired_lease_tells_the_launcher_it_was_lost_signal_not_anti_cheat(access):
    start = access.start(access.register(PLAYER))
    access.backdate_heartbeat(start, timedelta(minutes=5))

    access.sessions.expire(access.session(start), utc_now() - access.settings.lease_grace)
    heartbeat = access.heartbeat(start)

    assert heartbeat.state == SessionState.EXPIRED
    assert heartbeat.block.gate == AccessGate.LEASE
    assert heartbeat.block.code == AccessCodes.LEASE_EXPIRED
    assert access.store.list_whitelist() == []


def test_sweeper_does_not_overwrite_an_earlier_revocation(access):
    start = access.start(access.register(PLAYER))
    access.sessions.revoke(access.session(start), blocks.lease_revoked("admin"))
    access.backdate_heartbeat(start, timedelta(minutes=5))

    access.sessions.expire(access.session(start), utc_now())

    assert access.session(start).state == SessionState.REVOKED
    assert access.session(start).end_code == AccessCodes.LEASE_REVOKED


def test_sweeper_leaves_a_lease_renewed_after_it_read_the_list(access):
    start = access.start(access.register(PLAYER))
    access.backdate_heartbeat(start, timedelta(minutes=5))
    stale_view = access.session(start)
    cutoff = utc_now() - access.settings.lease_grace

    access.heartbeat(start)  # renewed between the sweeper's read and its update
    access.sessions.expire(stale_view, cutoff)

    assert access.session(start).state == SessionState.ACTIVE
    assert access.store.list_whitelist() == [PLAYER]


def test_resumed_heartbeat_keeps_the_same_lease(access):
    start = access.start(access.register(PLAYER))
    access.backdate_heartbeat(start, timedelta(seconds=40))  # launcher was down for a while, still within grace

    heartbeat = access.heartbeat(start, resumed=True)

    assert heartbeat.state == SessionState.ACTIVE
    assert len(access.store.list_active_sessions()) == 1


def test_new_lease_taken_during_grace_keeps_the_player_whitelisted_when_the_old_one_expires(access):
    device = access.register(PLAYER)
    first = access.start(device)
    second = access.start(device)  # launcher restarted without resuming
    access.backdate_heartbeat(first, timedelta(minutes=5))

    access.sessions.expire(access.session(first), utc_now() - access.settings.lease_grace)

    assert access.session(second).state == SessionState.ACTIVE
    assert access.store.list_whitelist() == [PLAYER]


def test_device_rejected_mid_session_ends_the_lease(access):
    device = access.register(PLAYER)
    start = access.start(device)

    access.store.set_device_status(device.device_id, DeviceStatus.REJECTED)
    heartbeat = access.heartbeat(start)

    assert heartbeat.state == SessionState.REVOKED
    assert heartbeat.block.code == AccessCodes.DEVICE_REJECTED


def test_end_of_the_last_lease_removes_the_whitelist_then_kicks_with_the_lease_reason(tmp_path):
    with FakeEvrimaRconServer() as fake:
        def configure(s):
            s.whitelist.mode = "rcon"
            s.whitelist.rcon_host = "127.0.0.1"
            s.whitelist.rcon_port = fake.port
            s.whitelist.rcon_password = "rcon"
            s.whitelist.kick_on_revoke = True

        f = AccessFixture(tmp_path, configure=configure)
        start = f.start(f.register(PLAYER))

        f.sessions.end_session(SessionEndRequest(session_id=start.session_id, token=start.token,
                                                 reason="launcher-closed"))

        commands = fake.commands
        assert [c.opcode for c in commands] == [rcon.OP_ADD_WHITELIST, rcon.OP_REMOVE_WHITELIST, rcon.OP_KICK]
        assert commands[2].payload == f"{PLAYER},{blocks.lease_released(None).label}"


# ---- Anti-cheat bypass ----


def test_bypass_lets_a_flagged_streamer_in_and_keeps_them_in(access):
    device = access.register(STREAMER)
    access.grant_bypass(STREAMER)

    start = access.start(device, CHEAT_ENGINE)
    heartbeat = access.heartbeat(start, CHEAT_ENGINE)

    assert start.decision == SessionDecision.GRANTED
    assert next(g for g in start.gates if g.gate == AccessGate.ANTI_CHEAT).status == GateStatus.BYPASSED
    assert heartbeat.state == SessionState.ACTIVE
    assert heartbeat.anti_cheat_bypassed


def test_bypass_never_overrides_a_ban(access):
    device = access.register(STREAMER)
    access.grant_bypass(STREAMER)
    access.store.insert_ban(BanSubject.STEAM_ID, STREAMER, "toxic", None)

    assert access.start(device).decision == SessionDecision.BANNED


def test_expired_bypass_no_longer_applies(access):
    device = access.register(STREAMER)
    access.grant_bypass(STREAMER, expires_utc=utc_now() - timedelta(minutes=1))

    assert access.start(device, CHEAT_ENGINE).block.code == AccessCodes.ANTICHEAT_BLOCKED


def test_master_switch_disables_every_bypass_at_once(tmp_path):
    f = AccessFixture(tmp_path, configure=lambda s: setattr(s, "allow_anti_cheat_bypass", False))
    device = f.register(STREAMER)
    f.grant_bypass(STREAMER)

    assert f.start(device, CHEAT_ENGINE).block.code == AccessCodes.ANTICHEAT_BLOCKED


def test_bypass_belongs_to_its_own_steam_id_only(access):
    access.grant_bypass(STREAMER)

    assert access.start(access.register(PLAYER), CHEAT_ENGINE).block.code == AccessCodes.ANTICHEAT_BLOCKED


def test_revoking_a_bypass_mid_session_applies_from_the_next_heartbeat(access):
    access.grant_bypass(STREAMER)
    start = access.start(access.register(STREAMER), CHEAT_ENGINE)

    access.store.delete_bypass(STREAMER)
    heartbeat = access.heartbeat(start, CHEAT_ENGINE)

    assert heartbeat.state == SessionState.REVOKED
    assert heartbeat.block.code == AccessCodes.ANTICHEAT_BLOCKED


def test_bypass_skips_device_approval_but_never_a_rejection(tmp_path):
    f = AccessFixture(tmp_path, configure=lambda s: setattr(s, "auto_approve_devices", False))
    device = f.register(STREAMER)
    assert f.start(device).decision == SessionDecision.PENDING_APPROVAL

    f.grant_bypass(STREAMER)
    start = f.start(device)
    assert start.decision == SessionDecision.GRANTED
    assert next(g for g in start.gates if g.gate == AccessGate.DEVICE).status == GateStatus.BYPASSED

    f.store.set_device_status(device.device_id, DeviceStatus.REJECTED)
    assert f.start(device).block.code == AccessCodes.DEVICE_REJECTED


# ---- Registration risk flags ----


def test_device_sharing_hardware_with_a_banned_account_waits_for_review(access):
    access.register(OTHER, {"machineGuid": "guid-1", "diskSerial": "disk-1"})
    access.store.insert_ban(BanSubject.STEAM_ID, OTHER, "hack", None)

    alt = access.register(PLAYER, {"machineGuid": "guid-1", "diskSerial": "disk-2"})

    assert alt.status == DeviceStatus.PENDING
    review = access.store.get_device(alt.device_id).review_reason
    assert "bị ban" in review
    assert "machineGuid" in review
    assert OTHER in review
    assert access.start(alt).block.code == AccessCodes.DEVICE_PENDING


def test_device_sharing_hardware_with_another_account_waits_for_review(access):
    access.register(OTHER, {"diskSerial": "disk-shared"})

    second = access.register(PLAYER, {"diskSerial": "disk-shared"})

    assert second.status == DeviceStatus.PENDING
    assert OTHER in access.store.get_device(second.device_id).review_reason


def test_same_account_re_registering_its_own_machine_is_not_flagged(access):
    first = access.register(PLAYER, {"machineGuid": "guid-home"})

    again = access.register(PLAYER, {"machineGuid": "guid-home"})

    assert again.status == DeviceStatus.APPROVED
    assert again.device_id == first.device_id  # the same record, re-keyed


def test_shared_cpu_id_alone_is_not_a_risk_flag(access):
    access.register(OTHER, {"machineGuid": "guid-a", "cpuId": COMMON_CPU})

    device = access.register(PLAYER, {"machineGuid": "guid-b", "cpuId": COMMON_CPU})

    assert device.status == DeviceStatus.APPROVED
    assert access.store.get_device(device.device_id).review_reason is None


def test_device_without_fingerprint_waits_for_review(access):
    device = access.register(PLAYER, components=None)

    assert device.status == DeviceStatus.PENDING
    assert access.store.get_device(device.device_id).review_reason is not None
