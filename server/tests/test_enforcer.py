"""The kick-without-lease safety net: who is kicked and when, and that a game-server problem never kicks anyone."""

from datetime import timedelta

from fake_rcon import FakeEvrimaRconServer

from islewarden_server import rcon
from islewarden_server.db import Database
from islewarden_server.discord import DiscordNotifier
from islewarden_server.enforcer import FAILURES_BEFORE_ALERT, NO_LEASE_REASON, REJOIN_WINDOW, LeaseEnforcer
from islewarden_server.enums import DeviceStatus, SessionState
from islewarden_server.records import BanSubject, DeviceRecord, SessionRecord
from islewarden_server.settings import Settings
from islewarden_server.store import Store
from islewarden_server.timeutil import utc_now

PLAYING = "76561198000000001"  # holds a lease
STRANGER = "76561198000000002"  # never opened the launcher
STAFF = "76561198000000003"  # in ExemptSteamIds
GRACE = 60


class Clock:
    def __init__(self):
        self.now = utc_now()

    def __call__(self):
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Alerts(DiscordNotifier):
    """Keeps the Discord alerts instead of sending them."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.messages: list[str] = []

    def notify_event(self, message: str) -> None:
        self.messages.append(message)


class StubRcon:
    """Answers playerlist with whoever is `online`, or raises while `down`; remembers the kicks."""

    def __init__(self):
        self.online: list[str] = []
        self.reply: str | None = None  # overrides the generated player list
        self.down = False
        self.kicks: list[tuple[str, str]] = []

    def player_list(self) -> str:
        if self.down:
            raise OSError("connection refused (test)")
        return self.reply if self.reply is not None else player_list(*self.online)

    def kick(self, steam_id: str, reason: str) -> str:
        self.kicks.append((steam_id, reason))
        return "Kicked"


def player_list(*steam_ids: str) -> str:
    """The layout public RCON libraries describe: names, then IDs. Only the IDs matter to the parser."""
    names = ",".join(f"Dino {n}" for n in range(len(steam_ids)))
    return f"PlayerList\n{names},\n{','.join(steam_ids)},\n"


def settings_for(tmp_path, **whitelist) -> Settings:
    settings = Settings(database_path=str(tmp_path / "enforcer.db"))
    options = settings.whitelist
    options.mode, options.rcon_host, options.rcon_password = "rcon", "127.0.0.1", "mat-khau-rcon"
    options.kick_without_lease, options.kick_grace_seconds, options.exempt_steam_ids = True, GRACE, [STAFF]
    for key, value in whitelist.items():
        setattr(options, key, value)
    return settings


def build(tmp_path, **whitelist):
    settings = settings_for(tmp_path, **whitelist)
    database = Database(settings.database_path)
    database.initialize()
    store = Store(database)
    stub, clock, alerts = StubRcon(), Clock(), Alerts(settings)
    return LeaseEnforcer(settings, store, alerts, rcon=stub, clock=clock), store, stub, clock, alerts


def open_lease(store: Store, steam_id: str) -> None:
    now = utc_now()
    device_id = "device-" + steam_id
    store.insert_device(DeviceRecord(device_id, steam_id, "key-hash", "TEST-PC", None, DeviceStatus.APPROVED,
                                     "test-v1", now), None)
    store.insert_session(SessionRecord("lease-" + steam_id, device_id, steam_id, "token-hash", SessionState.ACTIVE,
                                       now, now + timedelta(seconds=75), now, None))


def test_a_player_without_a_lease_is_kicked_once_the_grace_period_is_over(tmp_path):
    enforcer, _, stub, clock, alerts = build(tmp_path)
    stub.online = [STRANGER]

    assert enforcer.poll() == []  # first seen: the grace period starts
    clock.advance(GRACE - 1)
    assert enforcer.poll() == []
    clock.advance(2)
    assert enforcer.poll() == [STRANGER]

    assert stub.kicks == [(STRANGER, NO_LEASE_REASON)]
    assert len(alerts.messages) == 1 and STRANGER in alerts.messages[0]


def test_lease_holders_and_exempt_staff_are_never_kicked(tmp_path):
    enforcer, store, stub, clock, _ = build(tmp_path)
    open_lease(store, PLAYING)
    stub.online = [PLAYING, STAFF]

    enforcer.poll()
    clock.advance(GRACE * 10)

    assert enforcer.poll() == []
    assert stub.kicks == []


def test_a_banned_player_is_kicked_at_once_with_the_ban_wording(tmp_path):
    enforcer, store, stub, _, _ = build(tmp_path)
    store.insert_ban(BanSubject.STEAM_ID, STRANGER, "Cheat Engine", None)
    stub.online = [STRANGER]

    assert enforcer.poll() == [STRANGER]
    assert stub.kicks == [(STRANGER, "Bạn đang bị cấm vĩnh viễn.")]


def test_a_kicked_player_who_comes_back_gets_no_second_grace_period(tmp_path):
    enforcer, _, stub, clock, alerts = build(tmp_path)
    stub.online = [STRANGER]
    enforcer.poll()
    clock.advance(GRACE + 1)
    enforcer.poll()  # kicked

    stub.online = []
    clock.advance(20)
    enforcer.poll()
    stub.online = [STRANGER]  # rejoined without the launcher
    clock.advance(20)

    assert enforcer.poll() == [STRANGER]
    assert len(stub.kicks) == 2
    assert len(alerts.messages) == 1, "one alert per player per rejoin window, not one per kick"

    stub.online = []
    clock.advance(REJOIN_WINDOW.total_seconds() + 1)
    enforcer.poll()
    stub.online = [STRANGER]
    assert enforcer.poll() == [], "after the window, a new visit gets the grace period again"


def test_leaving_before_the_grace_period_ends_starts_it_over(tmp_path):
    enforcer, _, stub, clock, _ = build(tmp_path)
    stub.online = [STRANGER]
    enforcer.poll()
    clock.advance(GRACE - 10)
    stub.online = []
    enforcer.poll()

    stub.online = [STRANGER]
    clock.advance(20)

    assert enforcer.poll() == []


def test_an_unreachable_game_server_kicks_nobody_and_alerts_once(tmp_path):
    enforcer, _, stub, clock, alerts = build(tmp_path)
    stub.online = [STRANGER]
    enforcer.poll()
    clock.advance(GRACE + 1)
    stub.down = True

    for _ in range(FAILURES_BEFORE_ALERT + 2):
        assert enforcer.poll() == []
    assert stub.kicks == []
    assert len(alerts.messages) == 1 and "KHÔNG kick" in alerts.messages[0]

    stub.down = False
    enforcer.poll()
    assert "đọc lại được" in alerts.messages[1]


def test_a_reply_without_steam_ids_kicks_nobody(tmp_path):
    # A layout the parser doesn't know, or an error message, reads as an empty server: safe, never a lockout.
    enforcer, store, stub, clock, _ = build(tmp_path)
    open_lease(store, PLAYING)
    stub.reply = "Unknown command"

    for _ in range(4):
        assert enforcer.poll() == []
        clock.advance(GRACE)
    assert stub.kicks == []


def test_it_only_runs_in_rcon_mode_with_the_setting_on(tmp_path):
    assert LeaseEnforcer(settings_for(tmp_path), None, None).enabled
    assert not LeaseEnforcer(settings_for(tmp_path, kick_without_lease=False), None, None).enabled
    assert not LeaseEnforcer(settings_for(tmp_path, mode="none"), None, None).enabled
    assert not LeaseEnforcer(settings_for(tmp_path, rcon_host=None), None, None).enabled


def test_the_frames_on_the_wire(tmp_path):
    with FakeEvrimaRconServer(replies={rcon.OP_PLAYER_LIST: player_list(STRANGER)}) as fake:
        settings = settings_for(tmp_path, rcon_port=fake.port, kick_grace_seconds=0)
        database = Database(settings.database_path)
        database.initialize()
        enforcer = LeaseEnforcer(settings, Store(database), Alerts(settings))

        assert enforcer.poll() == [STRANGER]

        assert [(c.opcode, c.payload) for c in fake.commands] == [(rcon.OP_PLAYER_LIST, ""),
                                                                  (rcon.OP_KICK, f"{STRANGER},{NO_LEASE_REASON}")]
