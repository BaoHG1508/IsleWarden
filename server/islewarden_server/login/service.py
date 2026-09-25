"""Player login, replacing admin-issued invite codes: Steam proves the Steam ID, Discord proves guild membership
and a required role, then the launcher gets a device key."""

import logging
import sqlite3
from dataclasses import dataclass

from ..access import LoginCodes
from ..enums import DeviceStatus, DiscordRoleState
from ..models import LoginCompleteRequest
from ..records import DiscordLinkRecord
from ..sessions import SessionManager
from ..store import Store
from ..timeutil import utc_now
from . import steam
from .discord_api import DiscordApi, DiscordUnavailable
from .discord_gate import DiscordGate, block_for
from .http import HttpUnavailable
from .pending import PendingLogin, PendingLogins
from .steam import SteamOpenId

log = logging.getLogger("islewarden.login")

_EXPIRED = "Phiên đăng nhập đã hết hạn hoặc không hợp lệ. Hãy chạy lại lệnh login trong launcher."


@dataclass(frozen=True)
class LoginStep:
    """What a browser step answers with: a redirect to the next step, or a page explaining the problem."""

    redirect_url: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class LoginResponse:
    device_id: str
    # Returned exactly once; the server stores only its hash.
    device_key: str
    steam_id: str
    status: DeviceStatus
    # The linked Discord account; None when the server doesn't require Discord.
    discord_name: str | None


@dataclass(frozen=True)
class LoginResult:
    response: LoginResponse | None = None
    error: str | None = None
    code: str | None = None


class LoginService:
    def __init__(self, pending: PendingLogins, steam_openid: SteamOpenId, discord: DiscordApi,
                 discord_gate: DiscordGate, sessions: SessionManager, store: Store):
        self._pending = pending
        self._steam = steam_openid
        self._discord = discord
        self._gate = discord_gate
        self._sessions = sessions
        self._store = store

    def start(self, launcher_port: int, launcher_state: str, code_challenge: str, base_url: str) -> LoginStep:
        if (not 1024 <= launcher_port <= 65535 or not _is_token(launcher_state, 16, 128)
                or not _is_token(code_challenge, 43, 43)):
            return LoginStep(error_message="Liên kết đăng nhập không hợp lệ. Hãy chạy lại lệnh login trong launcher.")

        login = self._pending.start(launcher_port, launcher_state, code_challenge)
        if login is None:
            return LoginStep(error_message="Server đang có quá nhiều lượt đăng nhập. Thử lại sau ít phút.")
        return LoginStep(steam.login_url(_steam_return_to(base_url, login.id), base_url))

    def steam_callback(self, login_id: str | None, query: dict[str, str], base_url: str) -> LoginStep:
        login = None if login_id is None else self._pending.get(login_id)
        if login is None or login.steam_id is not None:
            return LoginStep(error_message=_EXPIRED)

        try:
            steam_id = self._steam.verify(query, _steam_return_to(base_url, login.id))
        except HttpUnavailable as ex:
            log.warning("Không xác minh được với Steam: %s", ex)
            return self._finish(login, (LoginCodes.STEAM_FAILED, "Không kết nối được Steam để xác minh. Thử lại sau."))

        if steam_id is None:
            return self._finish(login, (LoginCodes.STEAM_FAILED, "Đăng nhập Steam không hợp lệ. Hãy thử lại."))

        login.steam_id = steam_id
        if self._gate.enabled:
            return LoginStep(self._discord.authorize_url(_discord_redirect_uri(base_url), login.id))
        return self._finish(login)

    def discord_callback(self, state: str | None, code: str | None, base_url: str) -> LoginStep:
        login = None if state is None else self._pending.get(state)
        if login is None or login.steam_id is None or login.discord_id is not None:
            return LoginStep(error_message=_EXPIRED)

        if not code:
            return self._finish(login, (LoginCodes.DISCORD_FAILED, "Bạn đã huỷ đăng nhập Discord."))

        try:
            user = self._discord.get_user_from_code(code, _discord_redirect_uri(base_url))
            if user is None:
                return self._finish(login, (LoginCodes.DISCORD_FAILED,
                                            "Discord không chấp nhận lượt đăng nhập này. Hãy thử lại."))

            block = block_for(self._gate.check_member(user.id))
            if block is not None:
                message = block.label if block.detail is None else f"{block.label} {block.detail}"
                return self._finish(login, (block.code, message))

            login.discord_id = user.id
            login.discord_name = user.name
            return self._finish(login)
        except DiscordUnavailable as ex:
            log.warning("Đăng nhập Discord lỗi: %s", ex)
            return self._finish(login, (LoginCodes.DISCORD_FAILED, "Không kết nối được Discord. Thử lại sau."))

    def complete(self, request: LoginCompleteRequest) -> LoginResult:
        """The launcher redeems the finished login: links Steam and Discord, then issues the device key."""
        login = self._pending.redeem(request.code, request.code_verifier)
        if login is None:
            return LoginResult(error="Mã đăng nhập không hợp lệ hoặc đã hết hạn. Hãy chạy lại lệnh login.",
                               code=LoginCodes.EXPIRED)
        if login.failure is not None:
            code, message = login.failure
            return LoginResult(error=message, code=code)

        steam_id = login.steam_id
        if self._gate.enabled:
            failure = self._link(steam_id, login)
            if failure is not None:
                return failure

        device = self._sessions.register_device(steam_id, request.machine_name, request.consent_version,
                                                request.fingerprint)
        log.info("Đăng nhập: Steam %s%s → thiết bị %s (%s).", steam_id,
                 "" if login.discord_name is None else f" / Discord {login.discord_name}", device.device_id,
                 device.status.value)
        return LoginResult(LoginResponse(device.device_id, device.device_key, steam_id, device.status,
                                         login.discord_name))

    def _link(self, steam_id: str, login: PendingLogin) -> LoginResult | None:
        """One Discord account per Steam ID and vice versa: otherwise a single role holder could let any number of
        Steam accounts in. Changing either side is an admin decision (unlink on the dashboard)."""
        discord_id = login.discord_id

        by_discord = self._store.get_discord_link_by_discord_id(discord_id)
        if by_discord is not None and by_discord.steam_id != steam_id:
            return _linked_elsewhere(LoginCodes.DISCORD_LINKED_ELSEWHERE,
                                     "Tài khoản Discord này đã liên kết với một Steam ID khác.")

        by_steam = self._store.get_discord_link(steam_id)
        if by_steam is not None and by_steam.discord_id != discord_id:
            return _linked_elsewhere(LoginCodes.STEAM_LINKED_ELSEWHERE,
                                     "Steam ID này đã liên kết với một tài khoản Discord khác.")

        now = utc_now()
        try:
            self._store.upsert_discord_link(DiscordLinkRecord(
                steam_id, discord_id, login.discord_name, by_steam.linked_utc if by_steam else now,
                DiscordRoleState.OK, now))
        except sqlite3.IntegrityError:  # linked concurrently
            return _linked_elsewhere(LoginCodes.DISCORD_LINKED_ELSEWHERE,
                                     "Tài khoản Discord này đã liên kết với một Steam ID khác.")
        return None

    def _finish(self, login: PendingLogin, failure: tuple[str, str] | None = None) -> LoginStep:
        login.failure = failure
        return LoginStep(login.loopback_url(self._pending.finish(login)))


def _linked_elsewhere(code: str, message: str) -> LoginResult:
    return LoginResult(error=f"{message} Nhờ admin gỡ liên kết cũ nếu muốn đổi.", code=code)


def _steam_return_to(base_url: str, login_id: str) -> str:
    return f"{base_url}/login/steam/callback?login={login_id}"


def _discord_redirect_uri(base_url: str) -> str:
    return f"{base_url}/login/discord/callback"


def _is_token(value: str, min_length: int, max_length: int) -> bool:
    return min_length <= len(value) <= max_length and all(
        c.isascii() and (c.isalnum() or c in "-_") for c in value)
