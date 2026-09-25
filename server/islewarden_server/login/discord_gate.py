"""The Discord gate: a Steam ID may play only while its linked Discord account is in the guild and holds a
required role. Results are cached per player; when Discord can't be reached the last known result is used, so a
Discord outage never locks everyone out (the same principle as an unreachable RCON)."""

import logging
from datetime import timedelta

from .. import access
from ..access import AccessBlock
from ..enums import DiscordRoleState
from ..records import DiscordLinkRecord
from ..settings import Settings
from ..store import Store
from ..timeutil import universal, utc_now
from .discord_api import DiscordApi, DiscordUnavailable

log = logging.getLogger("islewarden.discord_gate")

# A join re-asks Discord unless the last check is younger than this.
JOIN_MAX_AGE = timedelta(minutes=1)


class DiscordGate:
    def __init__(self, settings: Settings, store: Store, api: DiscordApi):
        self._options = settings.discord
        self._store = store
        self._api = api

    @property
    def enabled(self) -> bool:
        return self._options.required

    @property
    def recheck_interval(self) -> timedelta:
        return timedelta(minutes=max(1, self._options.role_recheck_minutes))

    def check(self, steam_id: str, max_age: timedelta) -> tuple[AccessBlock | None, DiscordLinkRecord | None]:
        """The block when the gate fails (None when it passes), and the player's link if there is one."""
        link = self._store.get_discord_link(steam_id)
        if link is None:
            return access.discord_not_linked(), None

        if utc_now() - link.checked_utc < max_age:
            return block_for(link.role_state), link

        try:
            state = self.check_member(link.discord_id)
        except DiscordUnavailable as ex:
            log.warning("Không hỏi được Discord cho Steam %s (%s) — dùng kết quả kiểm tra lúc %s.", steam_id, ex,
                        universal(link.checked_utc))
            return block_for(link.role_state), link

        self._store.update_discord_role_state(steam_id, state, utc_now())
        if state != link.role_state:
            log.info("Discord của Steam %s: %s → %s.", steam_id, link.role_state.value, state.value)
        return block_for(state), link

    def check_member(self, discord_user_id: str) -> DiscordRoleState:
        """Asks Discord now whether the user is in the guild and holds a required role. Raises DiscordUnavailable."""
        member = self._api.get_member(discord_user_id)
        if member is None:
            return DiscordRoleState.NOT_MEMBER
        required = self._options.required_role_ids
        return (DiscordRoleState.OK if not required or any(role in required for role in member.roles)
                else DiscordRoleState.ROLE_MISSING)


def block_for(state: DiscordRoleState) -> AccessBlock | None:
    if state == DiscordRoleState.OK:
        return None
    if state == DiscordRoleState.NOT_MEMBER:
        return access.discord_not_member()
    return access.discord_role_missing()
