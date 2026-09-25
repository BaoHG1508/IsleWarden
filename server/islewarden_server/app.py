"""HTTP app: the launcher's API, the admin API behind X-Admin-Key, and the static pages.

Endpoints are plain functions (FastAPI runs them on a thread pool) because SQLite, RCON and the Discord
webhook are all blocking calls.
"""

import html
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__, access, crypto
from .crypto import Crypto
from .dashboard import DashboardStore, ReportFilter
from .db import Database
from .discord import DiscordNotifier
from .enforcer import LeaseEnforcer
from .enums import DeviceStatus, SessionState
from .login.discord_api import USER_AGENT as DISCORD_USER_AGENT
from .login.discord_api import DiscordApi
from .login.discord_gate import DiscordGate
from .login.http import Http, UrllibHttp
from .login.pending import PendingLogins
from .login.service import LoginService, LoginStep
from .login.steam import SteamOpenId
from .models import (FINDING_CODES, BanBySteamRequest, BanPlayerRequest, Baseline, BypassRequest,
                     CreateBanRequest, HeartbeatRequest, LoginCompleteRequest, NoteRequest, PruneRequest,
                     SessionEndRequest, SessionStartRequest, WatchRequest)
from .policy import PolicyProvider, is_valid_build_id
from .records import BanRecord, BanSubject, BypassRecord, is_identifying_component
from .risk import RiskScorer
from .sessions import SessionManager
from .settings import Settings
from .store import Store
from .sweeper import SessionSweeper
from .timeutil import iso, universal, utc_now
from .whitelist import WhitelistBridge
from .wire import loads_lenient, to_wire

log = logging.getLogger("islewarden")

STATIC_DIR = Path(__file__).parent / "static"

# Kestrel's default request body limit: a client can't make the server buffer an unbounded body.
MAX_BODY_BYTES = 30_000_000


@dataclass
class Services:
    settings: Settings
    database: Database
    store: Store
    policies: PolicyProvider
    whitelist: WhitelistBridge
    discord: DiscordNotifier
    sessions: SessionManager
    logins: LoginService
    dashboard: DashboardStore
    sweeper: SessionSweeper
    enforcer: LeaseEnforcer


def build_services(settings: Settings, *, steam_http: Http | None = None,
                   discord_http: Http | None = None) -> Services:
    """steam_http / discord_http replace the real HTTP clients in tests."""
    database = Database(settings.database_path)
    database.initialize()
    store = Store(database)
    policies = PolicyProvider(settings)
    whitelist = WhitelistBridge(settings, store)
    discord = DiscordNotifier(settings)
    discord_api = DiscordApi(settings, discord_http or UrllibHttp(user_agent=DISCORD_USER_AGENT))
    discord_gate = DiscordGate(settings, store, discord_api)
    sessions = SessionManager(settings, store, Crypto(settings.fingerprint_pepper), policies, whitelist, discord,
                              discord_gate)
    logins = LoginService(PendingLogins(), SteamOpenId(steam_http or UrllibHttp()), discord_api, discord_gate,
                          sessions, store)
    return Services(settings, database, store, policies, whitelist, discord, sessions, logins,
                    DashboardStore(database, RiskScorer(settings.risk)), SessionSweeper(settings, store, sessions),
                    LeaseEnforcer(settings, store, discord))


def create_app(settings: Settings, *, web_root: Path | None = STATIC_DIR, steam_http: Http | None = None,
               discord_http: Http | None = None) -> FastAPI:
    services = build_services(settings, steam_http=steam_http, discord_http=discord_http)
    _warn_if_misconfigured(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        services.sweeper.start()
        services.enforcer.start()
        yield
        services.enforcer.stop()
        services.sweeper.stop()

    app = FastAPI(title="IsleWarden.Server", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error(400, "Dữ liệu gửi lên không hợp lệ: " + _describe(exc.errors()))

    @app.get("/")
    def root():
        return {"service": "IsleWarden.Server", "version": __version__, "status": "ok"}

    @app.get("/health")
    def health():
        return {"status": "ok", "time": iso(utc_now())}

    app.include_router(player_api(services))
    app.include_router(login_api(services))
    app.include_router(admin_api(services))

    # consent.html, the dashboard at /admin/ and the older single-file admin.html.
    if web_root is not None and web_root.is_dir():
        app.mount("/", StaticFiles(directory=web_root, html=True), name="static")
    return app


def ok(value) -> JSONResponse:
    return JSONResponse(to_wire(value))


def error(status: int, message: str, code: str | None = None) -> JSONResponse:
    return JSONResponse({"error": message, "code": code}, status_code=status)


# ---- Launcher ----


def player_api(s: Services) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/policy")
    def get_policy():
        return ok(s.policies.envelope())

    @router.get("/baselines/{build_id}")
    def get_baseline(build_id: str):
        baseline = s.policies.try_get_baseline(build_id)
        return error(404, "Chưa có baseline cho build này.") if baseline is None else ok(baseline)

    @router.post("/session/start")
    def start_session(body: SessionStartRequest):
        return ok(s.sessions.start_session(body))

    @router.post("/session/heartbeat")
    def heartbeat(body: HeartbeatRequest):
        return ok(s.sessions.heartbeat(body))

    @router.post("/session/end")
    def end_session(body: SessionEndRequest):
        s.sessions.end_session(body)
        return Response(status_code=204)

    return router


# ---- Login (three browser steps and the launcher's redeem call) ----


def login_api(s: Services) -> APIRouter:
    router = APIRouter()

    def base_url(request: Request) -> str:
        public_url = s.settings.public_url
        if public_url and public_url.strip():
            return public_url.strip().rstrip("/")
        return f"{request.url.scheme}://{request.url.netloc}{request.scope.get('root_path', '')}"

    @router.get("/login/start")
    def login_start(request: Request, port: int | None = None, state: str | None = None,
                    challenge: str | None = None):
        return _respond(s.logins.start(port or 0, state or "", challenge or "", base_url(request)))

    @router.get("/login/steam/callback")
    def steam_callback(request: Request, login: str | None = None):
        # Repeated keys are joined with commas, as ASP.NET's query dictionary does.
        query = {key: ",".join(request.query_params.getlist(key)) for key in request.query_params.keys()}
        return _respond(s.logins.steam_callback(login, query, base_url(request)))

    @router.get("/login/discord/callback")
    def discord_callback(request: Request, state: str | None = None, code: str | None = None):
        return _respond(s.logins.discord_callback(state, code, base_url(request)))

    @router.post("/api/login/complete")
    def login_complete(body: LoginCompleteRequest):
        result = s.logins.complete(body)
        return error(403, result.error, result.code) if result.response is None else ok(result.response)

    return router


def _respond(step: LoginStep) -> Response:
    if step.redirect_url is not None:
        return RedirectResponse(step.redirect_url, status_code=302)
    return HTMLResponse(_error_page(step.error_message or ""), status_code=400)


def _error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Đăng nhập</title>
<style>body{{font-family:"Segoe UI",system-ui,sans-serif;background:#0f1720;color:#e7eef5;display:grid;place-items:center;min-height:90vh;margin:0}}
main{{max-width:520px;padding:24px 28px;background:#18232f;border:1px solid #294050;border-radius:12px}}h1{{font-size:19px;margin:0 0 10px;color:#e58}}</style>
</head><body><main><h1>Không đăng nhập được</h1><p>{html.escape(message)}</p></main></body></html>
"""


# ---- Admin ----


def admin_api(s: Services) -> APIRouter:
    """Every state-changing action is written to admin_actions, and a player's running-process list is only
    returned on an explicit ?processes=true, which is itself logged."""

    def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
        configured = s.settings.admin_key
        if not configured or not configured.strip():
            raise HTTPException(503, "Server chưa đặt AdminKey — endpoint quản trị đang bị khoá.")
        if not crypto.fixed_equals(x_admin_key or "", configured):
            raise HTTPException(401, "Sai hoặc thiếu X-Admin-Key.")

    router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
    store, dashboard, sessions, whitelist = s.store, s.dashboard, s.sessions, s.whitelist

    def devices_of(steam_id: str):
        return [d for d in store.list_devices() if d.steam_id == steam_id]

    def drop_player(ban_id: int, steam_id: str, reason: str | None, expires_utc) -> None:
        """Ends running leases now with the "banned" code instead of waiting for the next heartbeat, then drops
        the whitelist for anyone without a lease."""
        block = access.banned(BanRecord(ban_id, BanSubject.STEAM_ID, steam_id, reason, utc_now(), expires_utc))
        for session in store.list_active_sessions():
            if session.steam_id == steam_id:
                sessions.revoke(session, block)
        whitelist.revoke(steam_id)

    # ---- Devices ----

    @router.get("/devices")
    def list_devices(status: str | None = None):
        try:
            wanted = DeviceStatus.parse(status) if status and status.strip() else None
        except ValueError:
            return error(400, "Trạng thái thiết bị phải là pending, approved hoặc rejected.")
        return ok(store.list_devices(wanted))

    def set_status(device_id: str, status: DeviceStatus):
        if store.get_device(device_id) is None:
            return error(404, "Không tìm thấy thiết bị.")
        store.set_device_status(device_id, status)
        return ok({"deviceId": device_id, "status": status.value})

    @router.post("/devices/{device_id}/approve")
    def approve_device(device_id: str):
        return set_status(device_id, DeviceStatus.APPROVED)

    @router.post("/devices/{device_id}/reject")
    def reject_device(device_id: str):
        return set_status(device_id, DeviceStatus.REJECTED)

    # ---- Ban list ----

    @router.get("/bans")
    def list_bans():
        return ok(store.list_bans())

    @router.post("/bans")
    def create_ban(body: CreateBanRequest):
        if not body.subject_value or not body.subject_value.strip():
            return error(400, "Thiếu giá trị cần cấm.")
        subject_type = (body.subject_type or "").strip().lower()
        if subject_type not in BanSubject.ALL:
            return error(400, "Loại đối tượng cấm phải là steam_id, device hoặc component.")
        return ok({"id": store.insert_ban(subject_type, body.subject_value.strip(), body.reason, body.expires_utc)})

    @router.post("/bans/steam")
    def ban_steam_id(body: BanBySteamRequest):
        """Bans a Steam ID plus every device registered to it and their identifying hardware components."""
        if not body.steam_id or not body.steam_id.strip():
            return error(400, "Thiếu Steam ID.")
        steam_id = body.steam_id.strip()
        ban_id = store.insert_ban(BanSubject.STEAM_ID, steam_id, body.reason, body.expires_utc)
        for device in devices_of(steam_id):
            store.insert_ban(BanSubject.DEVICE, device.device_id, body.reason, body.expires_utc)
            for kind, value_hash in store.get_device_components(device.device_id):
                if is_identifying_component(kind):
                    store.insert_ban(BanSubject.COMPONENT, value_hash, body.reason, body.expires_utc)
        drop_player(ban_id, steam_id, body.reason, body.expires_utc)
        return ok({"steamId": steam_id, "banId": ban_id, "banned": True})

    @router.delete("/bans/{ban_id}")
    def delete_ban(ban_id: int):
        return Response(status_code=204 if store.delete_ban(ban_id) else 404)

    # ---- Sessions, whitelist, baselines ----

    @router.get("/sessions")
    def list_sessions():
        return ok(store.list_active_sessions())

    @router.get("/whitelist")
    def list_whitelist():
        return ok(store.list_whitelist())

    @router.put("/baselines/{build_id}")
    async def put_baseline(build_id: str, request: Request):
        if not is_valid_build_id(build_id):
            return error(400, "Build ID không hợp lệ.")
        content = await request.body()
        try:
            Baseline.model_validate(loads_lenient(content.decode("utf-8")))
        except (ValueError, ValidationError) as ex:
            return error(400, f"Baseline không hợp lệ: {ex}")
        os.makedirs(s.settings.baseline_directory, exist_ok=True)
        path = os.path.join(s.settings.baseline_directory, f"{build_id}.json")
        with open(path + ".tmp", "wb") as handle:
            handle.write(content)
        os.replace(path + ".tmp", path)
        return ok({"buildId": build_id, "saved": True})

    # ---- Overview and config ----

    @router.get("/overview")
    def overview():
        return ok(dashboard.overview(s.settings.risk.window_days))

    @router.get("/config")
    def config():
        policy = s.policies.get_policy()
        return ok({
            "mode": policy.mode.value,
            "disclosureVersion": policy.disclosure_version,
            "enforceThreshold": s.settings.enforce_threshold.value,
            "heartbeatSeconds": s.settings.heartbeat_seconds,
            "leaseGraceSeconds": int(s.settings.lease_grace.total_seconds()),
            "autoApproveDevices": s.settings.auto_approve_devices,
            "allowBypass": s.settings.allow_anti_cheat_bypass,
            "whitelistMode": s.settings.whitelist.mode,
            "kickOnRevoke": s.settings.whitelist.kick_on_revoke,
            "kickWithoutLease": s.enforcer.enabled,
            "kickGraceSeconds": s.settings.whitelist.kick_grace_seconds,
            "discordRequired": s.settings.discord.required,
            "discordGuildId": s.settings.discord.guild_id,
            "discordRoleIds": s.settings.discord.required_role_ids,
            "discordRecheckMinutes": s.settings.discord.role_recheck_minutes,
            "risk": s.settings.risk,
            "codes": FINDING_CODES,
        })

    # ---- Players ----

    def window_or_default(window: int | None) -> int:
        return s.settings.risk.window_days if window is None else window

    @router.get("/players")
    def list_players(window: int | None = None, limit: int | None = None):
        return ok(dashboard.list_players(window_or_default(window), 200 if limit is None else limit))

    @router.get("/players/{steam_id}")
    def get_player(steam_id: str, window: int | None = None):
        player = dashboard.get_player(steam_id, window_or_default(window))
        return error(404, "Chưa có hồ sơ cho Steam ID này.") if player is None else ok(player)

    @router.post("/players/{steam_id}/ban")
    def ban_player(steam_id: str, body: BanPlayerRequest):
        reason = body.reason.strip() if body.reason and body.reason.strip() else "Admin quyết định"
        ban_id = store.insert_ban(BanSubject.STEAM_ID, steam_id, reason, body.expires_utc)

        scope = (body.scope or "device").lower()
        if scope in ("device", "all"):
            for device in devices_of(steam_id):
                store.insert_ban(BanSubject.DEVICE, device.device_id, reason, body.expires_utc)
                if scope == "all":
                    # Skip components that don't identify a machine (cpuId): banning them hits other players.
                    for kind, value_hash in store.get_device_components(device.device_id):
                        if is_identifying_component(kind):
                            store.insert_ban(BanSubject.COMPONENT, value_hash, reason, body.expires_utc)

        evidence = body.evidence.strip() if body.evidence and body.evidence.strip() else None
        if evidence is not None or body.report_id is not None:
            dashboard.link_evidence(ban_id, body.report_id, evidence or f"báo cáo #{body.report_id}")

        # Dropped with the "banned" code, not "revoked by admin".
        drop_player(ban_id, steam_id, reason, body.expires_utc)
        until = f" — tới {universal(body.expires_utc)}" if body.expires_utc else " — vĩnh viễn"
        dashboard.insert_action("ban", BanSubject.STEAM_ID, steam_id, f"[{scope}] {reason}{until}", body.report_id)
        return ok({"steamId": steam_id, "banId": ban_id, "scope": scope, "banned": True})

    @router.post("/players/{steam_id}/unban")
    def unban_player(steam_id: str, body: NoteRequest | None = None):
        devices = devices_of(steam_id)
        subjects = {steam_id} | {d.device_id for d in devices}
        for device in devices:
            subjects |= {value_hash for _, value_hash in store.get_device_components(device.device_id)}
        removed = sum(1 for ban in store.list_bans() if ban.subject_value in subjects and store.delete_ban(ban.id))
        dashboard.insert_action("unban", BanSubject.STEAM_ID, steam_id, body.note if body else None)
        return ok({"steamId": steam_id, "removed": removed})

    @router.post("/players/{steam_id}/watch")
    def watch_player(steam_id: str, body: WatchRequest):
        """For low-risk cases: not enough to block, but worth keeping an eye on."""
        dashboard.insert_action("watch" if body.watch else "unwatch", BanSubject.STEAM_ID, steam_id, body.note)
        return ok({"steamId": steam_id, "watched": body.watch})

    @router.post("/players/{steam_id}/note")
    def note_player(steam_id: str, body: NoteRequest):
        if not body.note or not body.note.strip():
            return error(400, "Ghi chú rỗng.")
        dashboard.insert_action("note", BanSubject.STEAM_ID, steam_id, body.note.strip())
        return ok({"steamId": steam_id, "saved": True})

    @router.delete("/players/{steam_id}/discord")
    def unlink_discord(steam_id: str):
        """Lets the player link another Discord account (or this Discord account another Steam ID) at their next
        login. A lease they hold ends at its next heartbeat with "discord-not-linked"."""
        link = store.get_discord_link(steam_id)
        if link is None or not store.delete_discord_link(steam_id):
            return error(404, "Steam ID này chưa liên kết Discord.")
        dashboard.insert_action("discord-unlink", BanSubject.STEAM_ID, steam_id,
                                f"{link.discord_name} ({link.discord_id})")
        return ok({"steamId": steam_id, "unlinked": True})

    # ---- Anti-cheat bypass (streamers, staff...) ----

    @router.get("/bypasses")
    def list_bypasses():
        return ok(store.list_bypasses())

    @router.post("/players/{steam_id}/bypass")
    def grant_bypass(steam_id: str, body: BypassRequest):
        if not body.reason or not body.reason.strip():
            return error(400, "Cần lý do miễn trừ (ví dụ: streamer chạy OBS).")
        if body.expires_utc is not None and body.expires_utc <= utc_now():
            return error(400, "Hạn miễn trừ đã qua.")
        bypass = BypassRecord(steam_id, body.reason.strip(), utc_now(), body.expires_utc)
        store.upsert_bypass(bypass)
        until = f" — tới {universal(bypass.expires_utc)}" if bypass.expires_utc else " — tới khi gỡ"
        dashboard.insert_action("bypass", BanSubject.STEAM_ID, steam_id, bypass.reason + until)
        return ok({"steamId": steam_id, "bypass": bypass, "effective": s.settings.allow_anti_cheat_bypass})

    @router.delete("/players/{steam_id}/bypass")
    def remove_bypass(steam_id: str):
        if not store.delete_bypass(steam_id):
            return error(404, "Steam ID này không có miễn trừ.")
        dashboard.insert_action("unbypass", BanSubject.STEAM_ID, steam_id, None)
        return ok({"steamId": steam_id, "removed": True})

    # ---- Scan reports ----

    @router.get("/reports")
    def list_reports(steam_id: str | None = Query(None, alias="steamId"), code: str | None = None,
                     min_rank: int | None = Query(None, alias="minRank"),
                     only_dirty: bool | None = Query(None, alias="onlyDirty"),
                     limit: int | None = None, before: int | None = None):
        return ok(dashboard.list_reports(ReportFilter(
            steam_id, code, min_rank, bool(only_dirty), 100 if limit is None else limit, before)))

    @router.get("/reports/{report_id}")
    def get_report(report_id: int, processes: bool | None = None):
        report = dashboard.get_report(report_id, bool(processes))
        if report is None:
            return error(404, "Không có báo cáo này.")
        # Viewing someone's running software touches their privacy, so it is logged.
        if processes:
            dashboard.insert_action("view-processes", BanSubject.STEAM_ID, report.summary.steam_id,
                                    f"xem danh sách phần mềm trong báo cáo #{report_id}", report_id)
        return ok(report)

    # ---- Sessions ----

    @router.post("/sessions/{session_id}/revoke")
    def revoke_session(session_id: str, body: NoteRequest | None = None):
        session = store.get_session(session_id)
        if session is None:
            return error(404, "Không có phiên này.")
        if session.state != SessionState.ACTIVE:
            return error(400, "Phiên đã kết thúc.")
        reason = body.note.strip() if body and body.note and body.note.strip() else "admin thu hồi"
        sessions.revoke(session, access.lease_revoked(reason))
        dashboard.insert_action("revoke-session", "session", session_id, reason)
        return ok({"sessionId": session_id, "revoked": True})

    # ---- Admin log and maintenance ----

    @router.get("/actions")
    def list_actions(limit: int | None = None):
        return ok(dashboard.list_actions(100 if limit is None else limit))

    @router.post("/maintenance/prune")
    def prune_reports(body: PruneRequest):
        if body.days < 1:
            return error(400, "Số ngày phải từ 1 trở lên.")
        deleted = dashboard.prune_reports(body.days)
        dashboard.insert_action("prune-reports", "maintenance", f"{body.days}d",
                                f"xoá {deleted} báo cáo cũ hơn {body.days} ngày")
        return ok({"deleted": deleted, "days": body.days})

    return router


# ---- Plumbing ----


class BodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Dữ liệu gửi lên quá lớn.")


class BodySizeLimit:
    """Rejects request bodies over max_bytes, declared or streamed, before the app buffers them."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await error(413, "Dữ liệu gửi lên quá lớn.")(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # An HTTPException, so FastAPI's body parsing passes it through as a 413.
                    raise BodyTooLarge()
            return message

        await self.app(scope, limited_receive, send)


def _describe(errors) -> str:
    if not errors:
        return "không rõ lỗi"
    first = errors[0]
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    return f"{where}: {first.get('msg', '')}" if where else first.get("msg", "")


def _warn_if_misconfigured(settings: Settings) -> None:
    if not settings.admin_key or not settings.admin_key.strip():
        log.warning("Chưa đặt IsleWarden:AdminKey — các endpoint /api/admin sẽ bị khoá cho tới khi đặt.")
    if not settings.fingerprint_pepper or not settings.fingerprint_pepper.strip():
        log.warning("Chưa đặt IsleWarden:FingerprintPepper — nên đặt một chuỗi bí mật cố định để ban theo linh "
                    "kiện ổn định.")
    if settings.auto_approve_devices:
        log.info("AutoApproveDevices=true: thiết bị mới được duyệt tự động, trừ máy có cờ rủi ro. Đặt false nếu "
                 "muốn admin duyệt tay mọi máy.")
    if not settings.allow_anti_cheat_bypass:
        log.warning("AllowAntiCheatBypass=false: mọi miễn trừ anti-cheat đang mất tác dụng.")
    log.info("Suất chơi hết hạn sau %gs không có heartbeat.", settings.lease_grace.total_seconds())

    discord = settings.discord
    if discord.required:
        missing = [f"IsleWarden:Discord:{key}" for key, value in (
            ("ClientId", discord.client_id), ("ClientSecret", discord.client_secret),
            ("BotToken", discord.bot_token), ("GuildId", discord.guild_id)) if not value or not value.strip()]
        if missing:
            log.error("Thiếu %s — người chơi sẽ không đăng nhập được.", ", ".join(missing))
        if not discord.required_role_ids:
            log.warning("Discord:RequiredRoleIds trống — mọi thành viên Discord server đều vào chơi được.")
    else:
        log.warning("Discord:Required=false: đăng nhập chỉ bằng Steam, không kiểm tra role Discord. "
                    "Chỉ dùng khi thử nghiệm.")
    if not settings.public_url or not settings.public_url.strip():
        log.warning("Chưa đặt IsleWarden:PublicUrl — địa chỉ quay lại sau khi đăng nhập Steam/Discord sẽ lấy theo "
                    "từng request. Nên đặt khi chạy thật.")

    log.info("Đồng bộ whitelist: mode=%s", settings.whitelist.mode)
    if settings.whitelist.kick_on_revoke:
        if not settings.whitelist.is_rcon:
            log.warning("Whitelist:KickOnRevoke chỉ có tác dụng với Whitelist:Mode=rcon — đang bị bỏ qua.")
        else:
            log.warning("Whitelist:KickOnRevoke=true: dùng RCON kick (0x30) — opcode CHƯA kiểm chứng với server "
                        "thật, xem docs/TEST-WITH-REAL-SERVER.md.")
    whitelist = settings.whitelist
    if whitelist.kick_without_lease:
        if not whitelist.is_rcon or not whitelist.rcon_host or not whitelist.rcon_host.strip():
            log.warning("Whitelist:KickWithoutLease cần Whitelist:Mode=rcon và RconHost — đang bị bỏ qua.")
        else:
            log.warning("Whitelist:KickWithoutLease=true: đọc người chơi online bằng RCON playerlist (0x40) và kick "
                        "(0x30) ai không có suất chơi sau %ss — cả hai opcode CHƯA kiểm chứng với server thật. Nếu "
                        "RCON lỗi thì không ai bị kick.", whitelist.kick_grace_seconds)
            log.warning("Nhân sự vào bằng WhitelistIDs= trong Game.ini mà không mở launcher sẽ bị kick, trừ khi có "
                        "trong Whitelist:ExemptSteamIds (hiện có %d Steam ID).", len(whitelist.exempt_steam_ids))
