"""Steam + Discord login (no invite codes) and the Discord gate: only a Discord member holding a required role gets
a device key and a lease, and losing the role ends the lease."""

from datetime import timedelta

import pytest
from helpers import BASE_URL, PLAY_ROLE, AccessFixture, finding, query, with_discord

from islewarden_server import crypto
from islewarden_server.access import AccessCodes, LoginCodes
from islewarden_server.enums import AccessGate, DeviceStatus, SessionDecision, SessionState, Severity

PLAYER = "76561198000000021"
OTHER = "76561198000000022"
DISCORD_USER = "400000000000000001"

CHEAT_ENGINE = finding("blocked-process", Severity.HIGH, "Cheat Engine đang chạy")


@pytest.fixture
def f(tmp_path):
    return AccessFixture(tmp_path, configure=with_discord)


# ---- Login ----


def test_steam_and_discord_login_issues_a_working_device_key_and_links_the_accounts(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]

    login = f.login(PLAYER, DISCORD_USER).response
    start = f.start(login)

    assert login.steam_id == PLAYER
    assert login.discord_name == "user" + DISCORD_USER
    assert f.store.get_discord_link(PLAYER).discord_id == DISCORD_USER
    assert start.decision == SessionDecision.GRANTED
    assert [g.gate for g in start.gates] == [AccessGate.DEVICE, AccessGate.BAN, AccessGate.DISCORD,
                                             AccessGate.CONSENT, AccessGate.ANTI_CHEAT]
    assert start.gates[2].note == "user" + DISCORD_USER


def test_member_without_the_role_gets_no_device_key(f):
    f.http.members[DISCORD_USER] = ["some-other-role"]

    result = f.login(PLAYER, DISCORD_USER)

    assert result.response is None
    assert result.code == AccessCodes.DISCORD_ROLE_MISSING
    assert f.store.list_devices_of_steam_id(PLAYER) == []
    assert f.store.get_discord_link(PLAYER) is None


def test_someone_outside_the_guild_gets_no_device_key(f):
    assert f.login(PLAYER, DISCORD_USER).code == AccessCodes.DISCORD_NOT_MEMBER


def test_cancelling_on_discord_ends_the_login_with_its_own_code(f):
    assert f.complete(f.browser(PLAYER, discord_user_id=None)).code == LoginCodes.DISCORD_FAILED


def test_code_is_redeemed_only_with_the_launchers_verifier_and_only_once(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    browser = f.browser(PLAYER, DISCORD_USER)

    stolen = f.complete(browser, verifier=crypto.new_secret())
    real = f.complete(browser)
    replay = f.complete(browser)

    assert stolen.code == LoginCodes.EXPIRED
    assert real.response is not None  # a wrong guess does not burn the real launcher's code
    assert replay.code == LoginCodes.EXPIRED


def test_assertion_that_steam_does_not_confirm_is_rejected(f):
    f.http.steam_confirms = False

    result = f.complete(f.browser(PLAYER, DISCORD_USER))

    assert result.code == LoginCodes.STEAM_FAILED
    assert f.http.steam_checks == 1


def test_assertion_made_for_another_return_url_is_rejected_without_asking_steam(f):
    def tamper(assertion):
        assertion["openid.return_to"] = "https://evil.test/login/steam/callback?login=x"

    result = f.complete(f.browser(PLAYER, DISCORD_USER, tamper=tamper))

    assert result.code == LoginCodes.STEAM_FAILED
    assert f.http.steam_checks == 0


def test_unsigned_claimed_id_is_rejected(f):
    def tamper(assertion):
        assertion["openid.signed"] = "signed,op_endpoint,identity,return_to,response_nonce,assoc_handle"

    assert f.complete(f.browser(PLAYER, DISCORD_USER, tamper=tamper)).code == LoginCodes.STEAM_FAILED


def test_claimed_id_that_is_not_a_steam_id64_is_rejected(f):
    def tamper(assertion):
        assertion["openid.claimed_id"] = assertion["openid.identity"] = "https://steamcommunity.com/openid/id/123"

    assert f.complete(f.browser(PLAYER, DISCORD_USER, tamper=tamper)).code == LoginCodes.STEAM_FAILED


def test_one_discord_account_cannot_let_in_two_steam_accounts(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    f.login(PLAYER, DISCORD_USER)

    second = f.login(OTHER, DISCORD_USER)

    assert second.code == LoginCodes.DISCORD_LINKED_ELSEWHERE
    assert f.store.list_devices_of_steam_id(OTHER) == []


def test_one_steam_account_cannot_switch_discord_accounts_on_its_own(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    f.http.members["400000000000000002"] = [PLAY_ROLE]
    f.login(PLAYER, DISCORD_USER)

    assert f.login(PLAYER, "400000000000000002").code == LoginCodes.STEAM_LINKED_ELSEWHERE


def test_logging_in_again_on_the_same_machine_keeps_the_device_and_retires_the_old_key(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]

    first = f.login(PLAYER, DISCORD_USER, {"machineGuid": "guid-home", "diskSerial": "disk-1"}).response
    again = f.login(PLAYER, DISCORD_USER, {"machineGuid": "guid-home", "diskSerial": "disk-replaced"}).response

    assert again.device_id == first.device_id
    assert len(f.store.list_devices_of_steam_id(PLAYER)) == 1
    assert f.start(first).block.code == AccessCodes.DEVICE_UNKNOWN
    assert f.start(again).decision == SessionDecision.GRANTED


def test_logging_in_again_does_not_lift_a_rejection(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    machine = {"machineGuid": "guid-home"}
    first = f.login(PLAYER, DISCORD_USER, machine).response
    f.store.set_device_status(first.device_id, DeviceStatus.REJECTED)

    assert f.login(PLAYER, DISCORD_USER, machine).response.status == DeviceStatus.REJECTED


def test_without_discord_required_steam_alone_is_enough(tmp_path):
    f = AccessFixture(tmp_path)

    login = f.login(PLAYER, discord_user_id=None).response

    assert login.discord_name is None
    assert f.store.get_discord_link(PLAYER) is None
    assert f.start(login).decision == SessionDecision.GRANTED


@pytest.mark.parametrize("port,state,challenge", [
    (80, "s" * 16, "c" * 43),            # privileged port
    (51234, "short", "c" * 43),          # state too short
    (51234, "s" * 16, "c" * 42),         # challenge must be exactly 43 characters
    (51234, "s" * 15 + "!", "c" * 43),   # only [A-Za-z0-9_-]
])
def test_start_rejects_a_malformed_launcher_link(f, port, state, challenge):
    step = f.logins.start(port, state, challenge, BASE_URL)

    assert step.redirect_url is None
    assert "không hợp lệ" in step.error_message


def test_start_sends_the_browser_to_steam_with_our_return_url(f):
    step = f.logins.start(51234, "s" * 16, "c" * 43, BASE_URL)

    params = query(step.redirect_url)
    assert step.redirect_url.startswith("https://steamcommunity.com/openid/login?")
    assert params["openid.mode"] == "checkid_setup"
    assert params["openid.realm"] == BASE_URL
    assert params["openid.return_to"].startswith(BASE_URL + "/login/steam/callback?login=")


def test_unknown_login_id_is_an_expired_page(f):
    assert "hết hạn" in f.logins.steam_callback("nope", {}, BASE_URL).error_message
    assert "hết hạn" in f.logins.discord_callback("nope", "code-1", BASE_URL).error_message


# ---- Discord gate ----


def test_device_without_a_discord_link_is_blocked_at_the_discord_gate(f):
    start = f.start(f.register(PLAYER))

    assert start.block.gate == AccessGate.DISCORD
    assert start.block.code == AccessCodes.DISCORD_NOT_LINKED
    assert f.store.list_whitelist() == []


def test_losing_the_role_ends_the_lease_at_the_next_recheck(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    start = f.start(f.login(PLAYER, DISCORD_USER).response)

    f.http.members[DISCORD_USER] = []
    before_recheck = f.heartbeat(start)
    f.backdate_discord_check(PLAYER, timedelta(minutes=f.settings.discord.role_recheck_minutes, seconds=1))
    after_recheck = f.heartbeat(start)

    assert before_recheck.state == SessionState.ACTIVE
    assert after_recheck.state == SessionState.REVOKED
    assert after_recheck.block.code == AccessCodes.DISCORD_ROLE_MISSING
    assert f.store.list_whitelist() == []


def test_roles_are_not_reasked_on_every_heartbeat(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    start = f.start(f.login(PLAYER, DISCORD_USER).response)
    lookups = f.http.member_lookups

    f.heartbeat(start)
    f.heartbeat(start)

    assert f.http.member_lookups == lookups


def test_discord_outage_falls_back_to_the_last_known_result(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    login = f.login(PLAYER, DISCORD_USER).response
    start = f.start(login)

    f.http.discord_down = True
    f.backdate_discord_check(PLAYER, timedelta(hours=1))
    heartbeat = f.heartbeat(start)
    second_join = f.start(login)

    assert heartbeat.state == SessionState.ACTIVE
    assert second_join.decision == SessionDecision.GRANTED


def test_admin_unlink_ends_the_lease_at_the_next_heartbeat(f):
    f.http.members[DISCORD_USER] = [PLAY_ROLE]
    start = f.start(f.login(PLAYER, DISCORD_USER).response)

    f.store.delete_discord_link(PLAYER)
    heartbeat = f.heartbeat(start)

    assert heartbeat.state == SessionState.REVOKED
    assert heartbeat.block.code == AccessCodes.DISCORD_NOT_LINKED


def test_anti_cheat_bypass_does_not_relax_the_discord_gate(f):
    device = f.register(PLAYER)
    f.grant_bypass(PLAYER)

    assert f.start(device, CHEAT_ENGINE).block.code == AccessCodes.DISCORD_NOT_LINKED
