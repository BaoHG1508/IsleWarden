"""The Discord calls the login needs. The player's OAuth2 token (scope "identify" only) is used once to learn who
they are and is never stored; roles are read with the application's bot, so they can be re-checked later."""

from dataclasses import dataclass, field
from urllib.parse import quote

from ..settings import Settings
from .http import Http, HttpResponse, HttpUnavailable

API_BASE = "https://discord.com/api/v10/"
# Discord rejects bot calls without a User-Agent of this form.
USER_AGENT = "DiscordBot (IsleWarden.Server, 0.5.0)"

_AUTHORIZE_ENDPOINT = "https://discord.com/oauth2/authorize"
_UNKNOWN_MEMBER = 10007


class DiscordUnavailable(Exception):
    """Discord couldn't give an answer (network, outage, rate limit, bad configuration): not a "no"."""


@dataclass(frozen=True)
class DiscordUser:
    id: str
    name: str


@dataclass(frozen=True)
class DiscordMember:
    roles: list[str] = field(default_factory=list)


class DiscordApi:
    def __init__(self, settings: Settings, http: Http):
        self._options = settings.discord
        self._http = http

    def authorize_url(self, redirect_uri: str, state: str) -> str:
        params = [("response_type", "code"), ("client_id", self._options.client_id or ""), ("scope", "identify"),
                  ("redirect_uri", redirect_uri), ("state", state), ("prompt", "none")]
        return _AUTHORIZE_ENDPOINT + "?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in params)

    def get_user_from_code(self, code: str, redirect_uri: str) -> DiscordUser | None:
        """Trades the OAuth2 code for the user who signed in; None when Discord rejects the code.
        Raises DiscordUnavailable."""
        token = self._send("POST", "oauth2/token", form={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": self._options.client_id or "", "client_secret": self._options.client_secret or ""})
        if token.status in (400, 401):
            return None
        access_token = _read(token).get("access_token")
        if not isinstance(access_token, str):
            raise DiscordUnavailable("Discord API returned no access_token.")

        user = _read(self._send("GET", "users/@me", headers={"Authorization": f"Bearer {access_token}"}))
        global_name = user.get("global_name")
        name = global_name if isinstance(global_name, str) and global_name.strip() else user.get("username")
        return DiscordUser(str(user.get("id")), str(name))

    def get_member(self, user_id: str) -> DiscordMember | None:
        """The member's roles in the configured guild; None when the user isn't in it. Raises DiscordUnavailable."""
        guild = quote(self._options.guild_id or "", safe="")
        response = self._send("GET", f"guilds/{guild}/members/{quote(user_id, safe='')}",
                              headers={"Authorization": f"Bot {self._options.bot_token}"})
        # A 404 also comes back for an unknown guild; only "Unknown Member" means "not in the guild".
        if response.status == 404 and _error_code(response) == _UNKNOWN_MEMBER:
            return None
        roles = _read(response).get("roles") or []
        return DiscordMember([str(role) for role in roles])

    def _send(self, method: str, path: str, *, headers: dict[str, str] | None = None,
              form: dict[str, str] | None = None) -> HttpResponse:
        try:
            return self._http.send(method, API_BASE + path, headers=headers, form=form)
        except HttpUnavailable as ex:
            raise DiscordUnavailable(f"Discord API: {ex}") from ex


def _read(response: HttpResponse) -> dict:
    if not response.ok:
        message = None
        try:
            message = response.json().get("message")
        except (ValueError, AttributeError):
            pass
        raise DiscordUnavailable(f"Discord API {response.status}: {message or ''}".rstrip(": "))
    try:
        body = response.json()
    except ValueError as ex:
        raise DiscordUnavailable(f"Discord API: {ex}") from ex
    if not isinstance(body, dict):
        raise DiscordUnavailable("Discord API returned an empty body.")
    return body


def _error_code(response: HttpResponse) -> int | None:
    try:
        code = response.json().get("code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, int) else None
