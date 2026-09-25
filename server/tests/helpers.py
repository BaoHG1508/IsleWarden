import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from islewarden_server import crypto
from islewarden_server.crypto import Crypto
from islewarden_server.db import Database
from islewarden_server.discord import DiscordNotifier
from islewarden_server.enums import EnforcementMode, Severity
from islewarden_server.login import steam
from islewarden_server.login.discord_api import DiscordApi
from islewarden_server.login.discord_gate import DiscordGate
from islewarden_server.login.http import HttpResponse, HttpUnavailable
from islewarden_server.login.pending import PendingLogins
from islewarden_server.login.service import LoginService
from islewarden_server.models import (DeviceFingerprint, Finding, HeartbeatRequest, LoginCompleteRequest, ScanReport,
                                      SessionStartRequest)
from islewarden_server.policy import PolicyProvider
from islewarden_server.records import BypassRecord
from islewarden_server.sessions import SessionManager
from islewarden_server.settings import Settings
from islewarden_server.store import Store
from islewarden_server.timeutil import iso, utc_now
from islewarden_server.whitelist import WhitelistBridge

CONSENT = "test-v1"
COMMON_CPU = "BFEBFBFF000906EA"
PLAY_ROLE = "role-play"
BASE_URL = "https://ac.test"
_UNIQUE_MACHINE = object()


def finding(code: str, severity: Severity, message: str, detail: str | None = None) -> Finding:
    return Finding(code=code, severity=severity, message=message, detail=detail)


def report(*findings: Finding) -> ScanReport:
    clean = not any(f.severity.rank >= Severity.LOW.rank for f in findings)
    return ScanReport(timestamp_utc=utc_now(), machine="TEST-PC", clean=clean, findings=list(findings))


def write_policy(path: Path, mode: EnforcementMode, consent: str = CONSENT) -> None:
    path.write_text(json.dumps({"mode": mode.wire, "disclosureVersion": consent}), encoding="utf-8")


def fingerprint(components: dict[str, str] | None) -> DeviceFingerprint | None:
    return None if components is None else DeviceFingerprint(device_id="fp-" + uuid.uuid4().hex, components=components)


def query(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


def steam_assertion(steam_id: str, return_to: str) -> dict[str, str]:
    """What Steam sends back after a successful sign-in (its signature is checked by the fake)."""
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.op_endpoint": steam.ENDPOINT,
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{steam_id}",
        "openid.identity": f"https://steamcommunity.com/openid/id/{steam_id}",
        "openid.return_to": return_to,
        "openid.response_nonce": "2026-09-26T00:00:00Zabc",
        "openid.assoc_handle": "1234567890",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
        "openid.sig": "c2lnbmF0dXJl",
    }


def with_discord(settings: Settings) -> None:
    settings.discord.required = True


class FakeLoginServices:
    """Stands in for Steam OpenID and the Discord API. An OAuth code "code-X" signs in Discord user X; `members`
    holds each guild member's roles (absent = not in the guild)."""

    def __init__(self):
        self.steam_confirms = True
        self.discord_down = False
        self.members: dict[str, list[str]] = {}
        self.steam_checks = 0
        self.member_lookups = 0

    def send(self, method, url, *, headers=None, form=None) -> HttpResponse:
        if url.startswith(steam.ENDPOINT):
            self.steam_checks += 1
            valid = self.steam_confirms and (form or {}).get("openid.mode") == "check_authentication"
            return HttpResponse(200, f"ns:http://specs.openid.net/auth/2.0\nis_valid:{'true' if valid else 'false'}\n")

        if self.discord_down:
            raise HttpUnavailable("Discord is down (test).")

        path = urlsplit(url).path
        if path.endswith("/oauth2/token"):
            code = (form or {}).get("code", "")
            if code.startswith("code-"):
                return _json({"access_token": "token-" + code[len("code-"):], "token_type": "Bearer"})
            return _json({"error": "invalid_grant"}, 400)
        if path.endswith("/users/@me"):
            user_id = headers["Authorization"][len("Bearer token-"):]
            return _json({"id": user_id, "username": "user" + user_id, "global_name": None})
        if "/members/" in path:
            self.member_lookups += 1
            user_id = path.rsplit("/", 1)[1]
            if user_id in self.members:
                return _json({"roles": self.members[user_id]})
            return _json({"message": "Unknown Member", "code": 10007}, 404)
        return HttpResponse(404, "")


def _json(body, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(body))


@dataclass(frozen=True)
class BrowserLogin:
    """What the launcher holds after the browser part: the one-time code and its own PKCE verifier."""

    code: str
    verifier: str


class AccessFixture:
    """The access services over a throwaway SQLite database, with a policy file in the given mode and fake Steam
    and Discord endpoints. The Discord gate is off unless a test turns it on (with_discord)."""

    def __init__(self, directory: Path, mode: EnforcementMode = EnforcementMode.ENFORCE, configure=None):
        self.settings = Settings(database_path=str(directory / "access.db"),
                                 policy_path=str(directory / "server-policy.json"))
        self.settings.discord.required = False
        self.settings.discord.guild_id = "guild-1"
        self.settings.discord.required_role_ids = [PLAY_ROLE]
        if configure:
            configure(self.settings)
        write_policy(Path(self.settings.policy_path), mode)
        self.database = Database(self.settings.database_path)
        self.database.initialize()
        self.store = Store(self.database)
        self.http = FakeLoginServices()
        discord_api = DiscordApi(self.settings, self.http)
        gate = DiscordGate(self.settings, self.store, discord_api)
        self.sessions = SessionManager(self.settings, self.store, Crypto("test-pepper"),
                                       PolicyProvider(self.settings), WhitelistBridge(self.settings, self.store),
                                       DiscordNotifier(self.settings), gate)
        self.logins = LoginService(PendingLogins(), steam.SteamOpenId(self.http), discord_api, gate, self.sessions,
                                   self.store)

    def register(self, steam_id: str, components=_UNIQUE_MACHINE):
        """Registers a device the way a finished login does; by default a unique machine plus a CPU everyone
        shares."""
        if components is _UNIQUE_MACHINE:
            components = {"machineGuid": str(uuid.uuid4()), "cpuId": COMMON_CPU}
        return self.sessions.register_device(steam_id, "TEST-PC", CONSENT, fingerprint(components))

    def browser(self, steam_id: str, discord_user_id: str | None, tamper=None) -> BrowserLogin:
        """Plays the browser part of a login and returns what the launcher's loopback listener would receive.
        discord_user_id None = the player cancels on Discord; tamper alters the Steam assertion on its way back."""
        verifier, state = crypto.new_secret(), crypto.new_secret()
        start = self.logins.start(51234, state, crypto.pkce_challenge(verifier), BASE_URL)

        return_to = query(start.redirect_url)["openid.return_to"]
        login_id = query(return_to)["login"]
        assertion = steam_assertion(steam_id, return_to)
        assertion["login"] = login_id
        if tamper:
            tamper(assertion)

        step = self.logins.steam_callback(login_id, assertion, BASE_URL)
        if step.redirect_url.startswith("https://discord.com/"):
            step = self.logins.discord_callback(query(step.redirect_url)["state"],
                                                None if discord_user_id is None else "code-" + discord_user_id,
                                                BASE_URL)

        assert step.redirect_url.startswith("http://127.0.0.1:51234/callback?")
        loopback = query(step.redirect_url)
        assert loopback["state"] == state
        return BrowserLogin(loopback["code"], verifier)

    def complete(self, browser: BrowserLogin, components=None, verifier: str | None = None):
        return self.logins.complete(LoginCompleteRequest(
            code=browser.code, code_verifier=verifier or browser.verifier, machine_name="TEST-PC",
            consent_version=CONSENT, fingerprint=fingerprint(components or {"machineGuid": str(uuid.uuid4())})))

    def login(self, steam_id: str, discord_user_id: str | None, components=None):
        return self.complete(self.browser(steam_id, discord_user_id), components)

    def backdate_discord_check(self, steam_id: str, ago: timedelta) -> None:
        """Pretends the player's Discord role was last checked `ago` earlier."""
        link = self.store.get_discord_link(steam_id)
        self.store.update_discord_role_state(steam_id, link.role_state, utc_now() - ago)

    def start(self, device, *findings: Finding, consent_version: str = CONSENT):
        """device: a DeviceRegistration or a LoginResponse (both carry device_id and device_key)."""
        return self.sessions.start_session(SessionStartRequest(
            device_id=device.device_id, device_key=device.device_key, consent_version=consent_version,
            agent_version="test", game_build_id=None, report=report(*findings)))

    def heartbeat(self, lease, *findings: Finding, resumed: bool = False):
        return self.sessions.heartbeat(HeartbeatRequest(session_id=lease.session_id, token=lease.token,
                                                        report=report(*findings), resumed=resumed))

    def session(self, lease):
        return self.store.get_session(lease.session_id)

    def grant_bypass(self, steam_id: str, expires_utc=None) -> None:
        self.store.upsert_bypass(BypassRecord(steam_id, "streamer chạy OBS", utc_now(), expires_utc))

    def backdate_heartbeat(self, lease, ago: timedelta) -> None:
        """Pretends the last heartbeat arrived `ago` earlier."""
        with self.database.connect() as c:
            c.execute("UPDATE sessions SET last_heartbeat_utc = ? WHERE session_id = ?",
                      (iso(utc_now() - ago), lease.session_id))
