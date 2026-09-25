"""Logins in progress, kept in memory for LIFETIME. A server restart only means an unfinished login has to be
started again."""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote

from .. import crypto
from ..timeutil import utc_now

LIFETIME = timedelta(minutes=10)
# Caps memory if someone floods /login/start.
MAX_PENDING = 2000


@dataclass(eq=False)
class PendingLogin:
    """One browser login in progress."""

    # Carried through Steam (in the return URL) and Discord (as state); not a secret.
    id: str
    # The launcher's loopback listener the browser is sent back to.
    launcher_port: int
    # Echoed back so the launcher can match the redirect to its own login.
    launcher_state: str
    # PKCE challenge; only the launcher that started the login knows the verifier.
    code_challenge: str
    created_utc: datetime = field(default_factory=utc_now)
    steam_id: str | None = None
    discord_id: str | None = None
    discord_name: str | None = None
    # (code, message) when the login failed; the launcher learns the reason when it redeems the code.
    failure: tuple[str, str] | None = None

    def loopback_url(self, code: str) -> str:
        return (f"http://127.0.0.1:{self.launcher_port}/callback?code={quote(code, safe='')}"
                f"&state={quote(self.launcher_state, safe='')}")

    @property
    def expired(self) -> bool:
        return utc_now() - self.created_utc > LIFETIME


class PendingLogins:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_id: dict[str, PendingLogin] = {}
        self._by_code: dict[str, PendingLogin] = {}

    def start(self, launcher_port: int, launcher_state: str, code_challenge: str) -> PendingLogin | None:
        """None when too many logins are already in progress."""
        with self._lock:
            self._sweep()
            if len(self._by_id) + len(self._by_code) >= MAX_PENDING:
                return None
            login = PendingLogin(crypto.new_id(), launcher_port, launcher_state, code_challenge)
            self._by_id[login.id] = login
            return login

    def get(self, login_id: str) -> PendingLogin | None:
        with self._lock:
            login = self._by_id.get(login_id)
        return login if login is not None and not login.expired else None

    def finish(self, login: PendingLogin) -> str:
        """Ends the browser part and issues the one-time code the launcher redeems."""
        code = crypto.new_secret()
        with self._lock:
            self._by_id.pop(login.id, None)
            self._by_code[code] = login
        return code

    def redeem(self, code: str, code_verifier: str) -> PendingLogin | None:
        """Hands the login to the launcher that proves it started it. The code is consumed only on a matching
        verifier, so a wrong guess can't burn the real launcher's code."""
        with self._lock:
            login = self._by_code.get(code)
            if login is None or login.expired or not crypto.pkce_verify(code_verifier, login.code_challenge):
                return None
            del self._by_code[code]
            return login

    def _sweep(self) -> None:
        for table in (self._by_id, self._by_code):
            for key in [key for key, login in table.items() if login.expired]:
                del table[key]
