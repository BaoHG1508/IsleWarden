"""The HTTP surface as the C# launcher and the React dashboard see it: paths, status codes, camelCase JSON and
enum spellings. These shapes are a contract; see launcher/IsleWarden.Core/Protocol and dashboard/src/types.ts."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import PLAY_ROLE, FakeLoginServices, query, steam_assertion

from islewarden_server import crypto
from islewarden_server.app import BodySizeLimit, create_app
from islewarden_server.models import NoteRequest
from islewarden_server.settings import Settings

ADMIN_KEY = "test-admin-key"
ADMIN = {"X-Admin-Key": ADMIN_KEY}
STEAM = "76561198000000021"
DISCORD_USER = "400000000000000001"
CONSENT = "iw-v2"  # disclosureVersion of the example policy
DOTNET_O = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}\+00:00$")
EXAMPLE_POLICY = Path(__file__).resolve().parents[1] / "server-policy.json"


def make_settings(tmp_path, discord_required=False, **overrides) -> Settings:
    policy = tmp_path / "server-policy.json"
    if not policy.exists():
        policy.write_text(EXAMPLE_POLICY.read_text(encoding="utf-8"), encoding="utf-8")
    values = dict(database_path=str(tmp_path / "api.db"), policy_path=str(policy),
                  baseline_directory=str(tmp_path / "baselines"), admin_key=ADMIN_KEY, fingerprint_pepper="pepper",
                  consent_url="https://ac.example.com/consent.html")
    values.update(overrides)
    settings = Settings(**values)
    settings.discord.required = discord_required
    settings.discord.guild_id = "guild-1"
    settings.discord.required_role_ids = [PLAY_ROLE]
    return settings


def make_client(settings: Settings) -> TestClient:
    fake = FakeLoginServices()
    client = TestClient(create_app(settings, steam_http=fake, discord_http=fake))
    client.fake = fake
    return client


@pytest.fixture
def client(tmp_path):
    with make_client(make_settings(tmp_path)) as test_client:
        yield test_client


def scan(*findings, processes=None) -> dict:
    return {"timestampUtc": "2026-09-26T10:11:12.1234567+00:00", "machine": "TEST-PC",
            "clean": not findings, "findings": list(findings), "processes": processes}


def cheat_engine() -> dict:
    return {"code": "blocked-process", "severity": "high", "message": "Cheat Engine đang chạy", "detail": None}


def browser_login(client, steam_id=STEAM, discord_user=None) -> tuple[str, str]:
    """The browser part over HTTP: /login/start, Steam, then Discord when required. Returns (code, verifier)."""
    verifier, state = crypto.new_secret(), crypto.new_secret()
    started = client.get("/login/start", params={"port": 51234, "state": state,
                                                 "challenge": crypto.pkce_challenge(verifier)},
                         follow_redirects=False)
    assert started.status_code == 302, started.text
    return_to = query(started.headers["location"])["openid.return_to"]

    step = client.get(urlsplit(return_to).path, params={**query(return_to), **steam_assertion(steam_id, return_to)},
                      follow_redirects=False)
    assert step.status_code == 302, step.text
    location = step.headers["location"]
    if location.startswith("https://discord.com/"):
        step = client.get("/login/discord/callback", params={"state": query(location)["state"],
                                                             "code": f"code-{discord_user}"},
                          follow_redirects=False)
        location = step.headers["location"]

    assert location.startswith("http://127.0.0.1:51234/callback?")
    loopback = query(location)
    assert loopback["state"] == state
    return loopback["code"], verifier


def register(client, steam_id=STEAM, components=None, discord_user=None) -> dict:
    """A full login, as the launcher's `login` command does it."""
    code, verifier = browser_login(client, steam_id, discord_user)
    response = client.post("/api/login/complete", json={
        "code": code, "codeVerifier": verifier, "machineName": "TEST-PC", "consentVersion": CONSENT,
        "fingerprint": {"deviceId": "fp-1", "components": components or {"machineGuid": steam_id}}})
    assert response.status_code == 200, response.text
    return response.json()


def start(client, device, *findings, processes=None) -> dict:
    response = client.post("/api/session/start", json={
        "deviceId": device["deviceId"], "deviceKey": device["deviceKey"], "consentVersion": CONSENT,
        "agentVersion": "0.5.0", "gameBuildId": None, "report": scan(*findings, processes=processes)})
    assert response.status_code == 200, response.text
    return response.json()


def heartbeat(client, lease, *findings) -> dict:
    response = client.post("/api/session/heartbeat", json={
        "sessionId": lease["sessionId"], "token": lease["token"], "report": scan(*findings), "resumed": False})
    assert response.status_code == 200, response.text
    return response.json()


# ---- Launcher API ----


def test_policy_is_served_normalized_without_the_files_comments(client):
    body = client.get("/api/policy").json()

    assert body["consentUrl"] == "https://ac.example.com/consent.html"
    policy = body["policy"]
    assert (policy["mode"], policy["disclosureVersion"], policy["intervalSeconds"]) == ("observe", CONSENT, 30)
    assert policy["gameDirectory"] is None  # defaults are filled in, as the C# server did
    assert policy["blockedProcesses"][0] == {"name": "cheatengine-x86_64", "reason": "Cheat Engine",
                                             "severity": "high", "sha256": None}
    assert policy["executionHistory"]["lookbackDays"] == 7
    assert policy["startupOrder"] == {"enabled": True, "severity": "medium", "toleranceSeconds": 5}


def test_broken_policy_edit_keeps_the_last_good_policy(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        policy_file = Path(client.app.state.services.settings.policy_path)
        policy_file.write_text('{ "mode": "enforced" }', encoding="utf-8")  # not a valid mode

        assert client.get("/api/policy").json()["policy"]["disclosureVersion"] == CONSENT


def test_full_launcher_flow(client):
    device = register(client)
    assert set(device) == {"deviceId", "deviceKey", "steamId", "status", "discordName"}
    assert (device["steamId"], device["status"], device["discordName"]) == (STEAM, "approved", None)

    lease = start(client, device)
    assert lease["decision"] == "granted"
    assert (lease["block"], lease["message"], lease["heartbeatSeconds"]) == (None, None, 30)
    assert lease["gates"] == [
        {"gate": "device", "status": "passed", "note": None},
        {"gate": "ban", "status": "passed", "note": None},
        {"gate": "consent", "status": "passed", "note": CONSENT},
        {"gate": "antiCheat", "status": "passed", "note": "chế độ observe — chỉ ghi nhận, không chặn"},
    ]
    assert DOTNET_O.match(lease["expiresUtc"]) and DOTNET_O.match(lease["serverTime"])
    assert client.get("/api/admin/whitelist", headers=ADMIN).json() == [STEAM]

    beat = heartbeat(client, lease)
    assert set(beat) == {"state", "expiresUtc", "message", "block", "serverTime", "antiCheatBypassed"}
    assert (beat["state"], beat["antiCheatBypassed"]) == ("active", False)

    end = client.post("/api/session/end",
                      json={"sessionId": lease["sessionId"], "token": lease["token"], "reason": "launcher-closed"})
    assert end.status_code == 204

    after = heartbeat(client, lease)
    assert after["state"] == "ended"
    assert after["block"] == {"gate": "lease", "code": "lease-released", "label": "Launcher đã trả suất chơi.",
                              "detail": "launcher-closed", "until": None, "supportCode": None}
    assert client.get("/api/admin/whitelist", headers=ADMIN).json() == []


def test_blocked_join_explains_the_gate(tmp_path):
    settings = make_settings(tmp_path)
    Path(settings.policy_path).write_text('{"mode": "enforce", "disclosureVersion": "iw-v2"}', encoding="utf-8")
    with make_client(settings) as client:
        lease = start(client, register(client), cheat_engine())

    assert lease["decision"] == "denied"
    assert lease["sessionId"] is None and lease["token"] is None
    assert lease["block"]["gate"] == "antiCheat"
    assert lease["block"]["code"] == "anticheat-blocked"
    assert re.fullmatch(r"R-\d+", lease["block"]["supportCode"])
    assert lease["gates"][-1] == {"gate": "antiCheat", "status": "blocked", "note": None}


def test_unknown_device_is_denied_at_the_device_gate(client):
    response = client.post("/api/session/start", json={
        "deviceId": "nope", "deviceKey": "nope", "consentVersion": CONSENT, "agentVersion": "x", "report": scan()})

    assert response.json()["decision"] == "denied"
    assert response.json()["block"]["code"] == "device-unknown"


def test_request_property_names_match_case_insensitively(client):
    code, verifier = browser_login(client)

    response = client.post("/api/login/complete", json={"Code": code, "CODEVERIFIER": verifier, "machineName": "PC",
                                                        "ConsentVersion": CONSENT})

    assert response.status_code == 200
    assert response.json()["status"] == "pending"  # no fingerprint: always held for review


def test_failed_login_redeem_is_a_403_with_a_code(client):
    response = client.post("/api/login/complete", json={"code": "nope", "codeVerifier": "nope", "machineName": "PC",
                                                        "consentVersion": CONSENT})

    assert response.status_code == 403
    assert response.json() == {"error": "Mã đăng nhập không hợp lệ hoặc đã hết hạn. Hãy chạy lại lệnh login.",
                               "code": "login-expired"}


def test_login_start_sends_the_browser_to_steam(client):
    response = client.get("/login/start", params={"port": 51234, "state": "s" * 16, "challenge": "c" * 43},
                          follow_redirects=False)

    assert response.status_code == 302
    params = query(response.headers["location"])
    assert params["openid.realm"] == "http://testserver"
    assert params["openid.return_to"].startswith("http://testserver/login/steam/callback?login=")


def test_public_url_is_used_for_the_return_url(tmp_path):
    with make_client(make_settings(tmp_path, public_url="https://ac.example.com/")) as client:
        response = client.get("/login/start", params={"port": 51234, "state": "s" * 16, "challenge": "c" * 43},
                              follow_redirects=False)

    assert query(response.headers["location"])["openid.realm"] == "https://ac.example.com"


def test_login_problems_are_explained_on_an_html_page(client):
    bad_link = client.get("/login/start", params={"port": 51234, "state": "x", "challenge": "c" * 43})
    expired = client.get("/login/steam/callback", params={"login": "nope"})

    assert (bad_link.status_code, expired.status_code) == (400, 400)
    assert bad_link.headers["content-type"].startswith("text/html")
    assert "Liên kết đăng nhập không hợp lệ" in bad_link.text
    assert "đã hết hạn" in expired.text


def test_discord_login_and_gate_over_http(tmp_path):
    with make_client(make_settings(tmp_path, discord_required=True)) as client:
        client.fake.members[DISCORD_USER] = [PLAY_ROLE]

        device = register(client, discord_user=DISCORD_USER)
        lease = start(client, device)
        profile = client.get(f"/api/admin/players/{STEAM}", headers=ADMIN).json()
        [player] = client.get("/api/admin/players", headers=ADMIN).json()
        unlinked = client.delete(f"/api/admin/players/{STEAM}/discord", headers=ADMIN)
        beat = heartbeat(client, lease)
        again = client.delete(f"/api/admin/players/{STEAM}/discord", headers=ADMIN)
        action = client.get("/api/admin/actions", headers=ADMIN).json()[0]

    assert device["discordName"] == "user" + DISCORD_USER
    assert lease["gates"][2] == {"gate": "discord", "status": "passed", "note": "user" + DISCORD_USER}
    assert set(profile["discord"]) == {"steamId", "discordId", "discordName", "linkedUtc", "roleState", "checkedUtc"}
    assert (profile["discord"]["discordId"], profile["discord"]["roleState"]) == (DISCORD_USER, "ok")
    assert player["discordName"] == "user" + DISCORD_USER
    assert unlinked.json() == {"steamId": STEAM, "unlinked": True}
    assert (beat["state"], beat["block"]["code"], beat["block"]["gate"]) == ("revoked", "discord-not-linked",
                                                                             "discord")
    assert again.status_code == 404
    assert (action["action"], action["note"]) == ("discord-unlink", f"user{DISCORD_USER} ({DISCORD_USER})")


def test_invalid_body_is_a_400_the_launcher_can_print(client):
    response = client.post("/api/session/start", json={"deviceId": "x"})

    assert response.status_code == 400
    assert response.json()["error"].startswith("Dữ liệu gửi lên không hợp lệ")


# ---- Admin API ----


def test_admin_api_is_locked_until_an_admin_key_is_set(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, admin_key=None))) as client:
        response = client.get("/api/admin/config", headers=ADMIN)

    assert response.status_code == 503
    assert "AdminKey" in response.json()["detail"]


def test_admin_api_rejects_a_wrong_or_missing_key(client):
    assert client.get("/api/admin/config", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/api/admin/config").status_code == 401


def test_config_keeps_the_names_the_dashboard_shows(client):
    config = client.get("/api/admin/config", headers=ADMIN).json()

    assert (config["mode"], config["enforceThreshold"], config["leaseGraceSeconds"]) == ("Observe", "High", 75)
    assert config["risk"]["windowDays"] == 14
    assert "blocked-process" in config["codes"]
    assert (config["discordRequired"], config["discordGuildId"], config["discordRoleIds"],
            config["discordRecheckMinutes"]) == (False, "guild-1", [PLAY_ROLE], 10)


def test_device_review(client):
    device = register(client)

    rejected = client.post(f"/api/admin/devices/{device['deviceId']}/reject", headers=ADMIN)
    assert rejected.json() == {"deviceId": device["deviceId"], "status": "Rejected"}

    [listed] = client.get("/api/admin/devices?status=rejected", headers=ADMIN).json()
    assert listed["status"] == "rejected"
    assert set(listed) == {"deviceId", "steamId", "deviceKeyHash", "machineName", "fingerprintId", "status",
                           "consentVersion", "createdUtc", "reviewReason"}
    assert client.post("/api/admin/devices/nope/approve", headers=ADMIN).status_code == 404
    assert client.get("/api/admin/devices?status=bogus", headers=ADMIN).status_code == 400


def test_ban_from_the_dashboard_drops_the_player_and_unban_lets_them_back(client):
    device = register(client)
    lease = start(client, device)

    banned = client.post(f"/api/admin/players/{STEAM}/ban", headers=ADMIN,
                         json={"reason": "aimbot", "scope": "all", "expiresUtc": "2026-12-31T23:59:59.000Z"})
    assert banned.json()["banned"] and banned.json()["scope"] == "all"

    beat = heartbeat(client, lease)
    assert (beat["state"], beat["block"]["code"]) == ("revoked", "banned")
    assert client.get("/api/admin/whitelist", headers=ADMIN).json() == []
    assert client.get("/api/admin/actions", headers=ADMIN).json()[0]["note"] == \
        "[all] aimbot — tới 2026-12-31 23:59:59Z"

    profile = client.get(f"/api/admin/players/{STEAM}", headers=ADMIN).json()
    assert profile["banned"] and profile["risk"] == {"score": 0, "band": "clean", "reasons": []}

    # steam_id + device + the machineGuid component
    assert client.post(f"/api/admin/players/{STEAM}/unban", headers=ADMIN, json={}).json()["removed"] == 3
    assert start(client, device)["decision"] == "granted"


def test_ban_list_endpoints(client):
    created = client.post("/api/admin/bans", headers=ADMIN, json={"subjectType": "steam_id", "subjectValue": " 7656 "})
    ban_id = created.json()["id"]

    [ban] = client.get("/api/admin/bans", headers=ADMIN).json()
    assert (ban["id"], ban["subjectType"], ban["subjectValue"], ban["expiresUtc"]) == (ban_id, "steam_id", "7656", None)
    assert client.post("/api/admin/bans", headers=ADMIN,
                       json={"subjectType": "ip", "subjectValue": "1.2.3.4"}).status_code == 400
    assert client.delete(f"/api/admin/bans/{ban_id}", headers=ADMIN).status_code == 204
    assert client.delete(f"/api/admin/bans/{ban_id}", headers=ADMIN).status_code == 404


def test_bypass_endpoints(client):
    assert client.post(f"/api/admin/players/{STEAM}/bypass", headers=ADMIN, json={"reason": " "}).status_code == 400
    assert client.post(f"/api/admin/players/{STEAM}/bypass", headers=ADMIN,
                       json={"reason": "OBS", "expiresUtc": "2020-01-01T00:00:00Z"}).status_code == 400

    granted = client.post(f"/api/admin/players/{STEAM}/bypass", headers=ADMIN, json={"reason": "streamer, OBS"})
    assert granted.json()["effective"] is True
    assert granted.json()["bypass"]["steamId"] == STEAM
    assert [b["reason"] for b in client.get("/api/admin/bypasses", headers=ADMIN).json()] == ["streamer, OBS"]

    assert client.delete(f"/api/admin/players/{STEAM}/bypass", headers=ADMIN).json()["removed"] is True
    assert client.delete(f"/api/admin/players/{STEAM}/bypass", headers=ADMIN).status_code == 404


def test_report_processes_are_only_returned_on_request_and_that_view_is_logged(client):
    start(client, register(client), cheat_engine(), processes=["chrome", "TheIsle"])

    [summary] = client.get(f"/api/admin/reports?steamId={STEAM}&onlyDirty=true", headers=ADMIN).json()
    assert (summary["findingCount"], summary["worstRank"], summary["topCode"]) == (1, 3, "blocked-process")

    plain = client.get(f"/api/admin/reports/{summary['id']}", headers=ADMIN).json()
    assert plain["processes"] is None
    assert plain["findings"] == [{"code": "blocked-process", "severity": "high",
                                  "message": "Cheat Engine đang chạy", "detail": None, "rank": 3}]

    detailed = client.get(f"/api/admin/reports/{summary['id']}?processes=true", headers=ADMIN).json()
    assert detailed["processes"] == ["chrome", "TheIsle"]
    assert client.get("/api/admin/actions", headers=ADMIN).json()[0]["action"] == "view-processes"


def test_revoke_session_and_prune(client):
    lease = start(client, register(client))

    revoked = client.post(f"/api/admin/sessions/{lease['sessionId']}/revoke", headers=ADMIN, json={"note": "spam"})
    assert revoked.json() == {"sessionId": lease["sessionId"], "revoked": True}
    assert client.post(f"/api/admin/sessions/{lease['sessionId']}/revoke", headers=ADMIN).status_code == 400
    assert heartbeat(client, lease)["block"]["detail"] == "spam"

    assert client.post("/api/admin/maintenance/prune", headers=ADMIN, json={"days": 0}).status_code == 400
    assert client.post("/api/admin/maintenance/prune", headers=ADMIN, json={"days": 30}).json() == \
        {"deleted": 0, "days": 30}


def test_overview_and_players(client):
    start(client, register(client))

    overview = client.get("/api/admin/overview", headers=ADMIN).json()
    assert (overview["activeSessions"], overview["reportsLast24h"], overview["whitelisted"]) == (1, 1, 1)
    [player] = client.get("/api/admin/players?window=14&limit=10", headers=ADMIN).json()
    assert (player["steamId"], player["sessions"], player["devices"], player["band"]) == (STEAM, 1, 1, "clean")


def test_baseline_upload_and_download(client):
    baseline = '{"version":1,"buildId":"24664737","createdUtc":"2026-09-20T08:00:00+00:00","include":["*.exe"],' \
               '"exclude":[],"files":[{"path":"TheIsle.exe","size":123,"sha256":"AB"}]}'

    assert client.get("/api/baselines/24664737").status_code == 404
    saved = client.put("/api/admin/baselines/24664737", headers=ADMIN, content=baseline.encode())
    assert saved.json() == {"buildId": "24664737", "saved": True}

    served = client.get("/api/baselines/24664737").json()
    assert served["files"] == [{"path": "TheIsle.exe", "size": 123, "sha256": "AB"}]
    assert served["appId"] is None and DOTNET_O.match(served["createdUtc"])

    assert client.put("/api/admin/baselines/bad%20id", headers=ADMIN, content=baseline.encode()).status_code == 400
    assert client.put("/api/admin/baselines/1", headers=ADMIN, content=b"not json").status_code == 400


# ---- Plumbing ----


def test_static_pages_and_health(client):
    assert client.get("/").json() == {"service": "IsleWarden.Server", "version": "0.5.0", "status": "ok"}
    assert client.get("/health").json()["status"] == "ok"
    assert "Thông báo chống gian lận" in client.get("/consent.html").text
    assert client.get("/admin/").headers["content-type"].startswith("text/html")


def test_timestamps_are_stored_in_the_format_the_csharp_server_used(client):
    start(client, register(client))

    database = client.app.state.services.database
    with database.connect() as c:
        row = c.execute("SELECT started_utc, expires_utc, last_heartbeat_utc FROM sessions").fetchone()
    assert all(DOTNET_O.match(value) for value in row)


def test_body_size_limit():
    app = FastAPI()

    @app.post("/echo")
    def echo(body: NoteRequest):
        return {"note": body.note}

    app.add_middleware(BodySizeLimit, max_bytes=64)
    client = TestClient(app)

    def chunks():
        yield b'{"note":"'
        yield b"x" * 100
        yield b'"}'

    assert client.post("/echo", json={"note": "ok"}).json() == {"note": "ok"}
    assert client.post("/echo", json={"note": "x" * 100}).status_code == 413  # declared Content-Length
    assert client.post("/echo", content=chunks(), headers={"content-type": "application/json"}).status_code == 413
