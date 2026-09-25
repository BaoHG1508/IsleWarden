"""Background thread that kicks players who are in the game without an active lease.

The whitelist keeps players without a lease from joining; this catches whoever is online anyway: a player whose
lease ended while in the game (whitelist removal may not drop them), or anyone at all when the game server runs
with bServerWhitelist=false. It reads the player list over RCON, so it only runs in rcon mode, and it fails open:
when the list can't be read nobody is kicked, so admins are alerted on Discord.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from . import access
from .discord import DiscordNotifier
from .rcon import EvrimaRconClient, parse_steam_ids
from .records import BanSubject
from .settings import Settings
from .store import Store
from .timeutil import utc_now

log = logging.getLogger("islewarden.enforcer")

# What the kicked player reads; free of commas, which would split the RCON argument.
NO_LEASE_REASON = "Không có suất chơi: mở launcher IsleWarden và đăng nhập Steam + Discord rồi vào lại."
# A player kicked this recently who comes back without a lease gets no second grace period.
REJOIN_WINDOW = timedelta(minutes=10)
# Consecutive failed reads of the player list before admins are told that kicking has stopped.
FAILURES_BEFORE_ALERT = 3
EMPTY_REPLIES_BEFORE_WARNING = 3


class LeaseEnforcer:
    def __init__(self, settings: Settings, store: Store, discord: DiscordNotifier,
                 rcon: EvrimaRconClient | None = None, clock: Callable[[], datetime] = utc_now):
        """rcon / clock replace the real client and clock in tests."""
        self._settings = settings
        self._store = store
        self._discord = discord
        options = settings.whitelist
        if rcon is None and options.is_rcon and options.rcon_host and options.rcon_host.strip():
            rcon = EvrimaRconClient(options.rcon_host, options.rcon_port, options.rcon_password or "")
        self._rcon = rcon
        self._clock = clock
        self._first_seen: dict[str, datetime] = {}
        self._kicked: dict[str, datetime] = {}
        self._failures = 0
        self._empty_replies = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        options = self._settings.whitelist
        return options.kick_without_lease and options.is_rcon and self._rcon is not None

    def start(self) -> None:
        if not self.enabled:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="lease-enforcer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def poll(self) -> list[str]:
        """One pass over the players online; returns the Steam IDs it kicked."""
        try:
            reply = self._rcon.player_list()
        except Exception as ex:
            self._failures += 1
            if self._failures in (1, FAILURES_BEFORE_ALERT):
                log.warning("Không đọc được playerlist qua RCON (%d lần liên tiếp): %s", self._failures, ex)
            if self._failures == FAILURES_BEFORE_ALERT:
                self._discord.notify_event("⚠️ Không đọc được danh sách người chơi qua RCON — đang KHÔNG kick được "
                                           "ai vào game mà không có suất chơi.")
            return []
        if self._failures >= FAILURES_BEFORE_ALERT:
            self._discord.notify_event("✅ Đã đọc lại được danh sách người chơi qua RCON.")
        self._failures = 0

        now = self._clock()
        online = parse_steam_ids(reply)
        active = {session.steam_id for session in self._store.list_active_sessions()}
        self._note_lists_without_ids(reply, online, active)
        # Someone who left and comes back later starts a new grace period.
        self._first_seen = {steam_id: at for steam_id, at in self._first_seen.items() if steam_id in online}
        self._kicked = {steam_id: at for steam_id, at in self._kicked.items() if now - at <= REJOIN_WINDOW}

        options = self._settings.whitelist
        exempt = set(options.exempt_steam_ids)
        grace = timedelta(seconds=max(0, options.kick_grace_seconds))
        kicked = []
        for steam_id in online:
            if steam_id in active:
                self._first_seen.pop(steam_id, None)
                continue
            ban = self._store.find_active_ban([(BanSubject.STEAM_ID, steam_id)])
            if ban is not None:
                reason = access.banned(ban).label
            elif steam_id in exempt:
                continue
            elif steam_id not in self._kicked and now - self._first_seen.setdefault(steam_id, now) < grace:
                continue
            else:
                reason = NO_LEASE_REASON
            if self._kick(steam_id, reason, now):
                kicked.append(steam_id)
        log.debug("playerlist: %d online, %d có suất chơi, kick %d.", len(online), len(active & set(online)),
                  len(kicked))
        return kicked

    def _kick(self, steam_id: str, reason: str, now: datetime) -> bool:
        try:
            response = self._rcon.kick(steam_id, reason)
        except Exception:
            log.exception("RCON kick thất bại (%s).", steam_id)
            return False
        log.info("Kick %s vì không có suất chơi: %s → %s", steam_id, reason, response)
        if steam_id not in self._kicked:  # one alert per player per rejoin window, not one per kick
            self._discord.notify_event(f"🦶 Kick Steam `{steam_id}` khỏi game — {reason}")
        self._first_seen.pop(steam_id, None)
        self._kicked[steam_id] = now
        return True

    def _note_lists_without_ids(self, reply: str, online: list[str], active: set[str]) -> None:
        """A game server that doesn't answer playerlist, or answers in a layout without SteamID64s, looks like an
        empty server: nobody gets kicked, which is safe but silent, so say so in the log."""
        self._empty_replies = self._empty_replies + 1 if not online and active else 0
        if self._empty_replies == EMPTY_REPLIES_BEFORE_WARNING:
            log.warning("playerlist không có Steam ID nào %d lần liền trong khi có %d suất chơi đang mở — nếu có "
                        "người đang ở trong game thì server game không trả lời playerlist hoặc trả về dạng khác, và "
                        "không ai bị kick. Trả lời nhận được: %r", self._empty_replies, len(active), reply[:300])

    def _run(self) -> None:
        options = self._settings.whitelist
        interval = max(5.0, float(options.kick_poll_seconds))
        log.info("LeaseEnforcer: kiểm tra người chơi online mỗi %gs, ân hạn %ss.", interval, options.kick_grace_seconds)
        while not self._stop.wait(interval):
            try:
                self.poll()
            except Exception:
                log.exception("Lỗi khi kiểm tra người chơi online.")
