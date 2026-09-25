""""Sign in through Steam" (OpenID 2.0). Proves which SteamID64 the player owns; needs no API key."""

import re
from urllib.parse import quote

from .http import Http, HttpUnavailable

ENDPOINT = "https://steamcommunity.com/openid/login"

_IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
# Fields the assertion must sign; anything unsigned could have been altered on the way back.
_MUST_BE_SIGNED = ("op_endpoint", "claimed_id", "identity", "return_to", "response_nonce")
_CLAIMED_ID = re.compile(r"https?://steamcommunity\.com/openid/id/(7656119\d{10})")


def login_url(return_to: str, realm: str) -> str:
    params = [("openid.ns", "http://specs.openid.net/auth/2.0"), ("openid.mode", "checkid_setup"),
              ("openid.return_to", return_to), ("openid.realm", realm), ("openid.identity", _IDENTIFIER_SELECT),
              ("openid.claimed_id", _IDENTIFIER_SELECT)]
    return ENDPOINT + "?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in params)


class SteamOpenId:
    def __init__(self, http: Http):
        self._http = http

    def verify(self, query: dict[str, str], expected_return_to: str) -> str | None:
        """The SteamID64 of a valid assertion, or None. It must be for our own return URL (one made for another
        site or another login can't be replayed), sign every field we rely on, and Steam itself must confirm the
        signature (check_authentication). Raises HttpUnavailable when Steam can't be reached."""
        if (query.get("openid.mode") != "id_res" or query.get("openid.op_endpoint") != ENDPOINT
                or query.get("openid.return_to") != expected_return_to):
            return None

        claimed_id = query.get("openid.claimed_id") or ""
        match = _CLAIMED_ID.fullmatch(claimed_id)
        if match is None or query.get("openid.identity") != claimed_id:
            return None

        signed = (query.get("openid.signed") or "").split(",")
        if any(field not in signed for field in _MUST_BE_SIGNED):
            return None

        form = {key: value for key, value in query.items() if key.startswith("openid.")}
        form["openid.mode"] = "check_authentication"
        response = self._http.send("POST", ENDPOINT, form=form)
        if not response.ok:
            raise HttpUnavailable(f"Steam OpenID answered HTTP {response.status}.")
        confirmed = any(line.strip() == "is_valid:true" for line in response.body.split("\n"))
        return match.group(1) if confirmed else None
