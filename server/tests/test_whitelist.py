"""The whitelist bridge in all three modes. The invariant that matters most: a failure syncing to the game
server must not break granting or revoking leases; the whitelist table must still be right."""

import os

from fake_rcon import FakeEvrimaRconServer

from islewarden_server import rcon
from islewarden_server.db import Database
from islewarden_server.settings import Settings
from islewarden_server.store import Store
from islewarden_server.whitelist import WhitelistBridge

PLAYER_A = "76561198000000001"
PLAYER_B = "76561198000000002"


def build(tmp_path, **whitelist):
    database = Database(str(tmp_path / "islewarden-test.db"))
    database.initialize()
    settings = Settings()
    for key, value in whitelist.items():
        setattr(settings.whitelist, key, value)
    store = Store(database)
    return WhitelistBridge(settings, store), store


def test_rcon_mode_sends_the_add_then_remove_opcodes(tmp_path):
    with FakeEvrimaRconServer() as fake:
        bridge, store = build(tmp_path, mode="rcon", rcon_host="127.0.0.1", rcon_port=fake.port,
                              rcon_password="mat-khau-rcon")

        bridge.grant(PLAYER_A)
        bridge.revoke(PLAYER_A)

        commands = fake.commands
        assert [(c.opcode, c.payload) for c in commands] == [(rcon.OP_ADD_WHITELIST, PLAYER_A),
                                                             (rcon.OP_REMOVE_WHITELIST, PLAYER_A)]
        assert store.list_whitelist() == []


def test_rcon_mode_without_a_host_does_not_raise(tmp_path):
    bridge, store = build(tmp_path, mode="rcon")

    bridge.grant(PLAYER_A)

    assert store.list_whitelist() == [PLAYER_A]


def test_unreachable_rcon_still_keeps_the_whitelist_table_right(tmp_path):
    # Game server down or on the wrong port: a clean player must still get a lease, and the table must stay
    # right so a later sync can catch up.
    bridge, store = build(tmp_path, mode="rcon", rcon_host="127.0.0.1",
                          rcon_port=FakeEvrimaRconServer.find_unused_port(), rcon_password="mat-khau-rcon")

    bridge.grant(PLAYER_A)

    assert store.list_whitelist() == [PLAYER_A]


def test_kick_on_revoke_sends_the_kick_opcode(tmp_path):
    with FakeEvrimaRconServer() as fake:
        bridge, _ = build(tmp_path, mode="rcon", rcon_host="127.0.0.1", rcon_port=fake.port,
                          rcon_password="mat-khau-rcon", kick_on_revoke=True)

        bridge.kick(PLAYER_A, "Mất tín hiệu launcher")

        [command] = fake.commands
        assert command.opcode == rcon.OP_KICK
        assert command.payload == f"{PLAYER_A},Mất tín hiệu launcher"


def test_kick_is_off_unless_explicitly_enabled(tmp_path):
    # The kick opcode is unverified against a real server, so nothing is sent unless an admin opts in.
    with FakeEvrimaRconServer() as fake:
        bridge, _ = build(tmp_path, mode="rcon", rcon_host="127.0.0.1", rcon_port=fake.port,
                          rcon_password="mat-khau-rcon")

        bridge.kick(PLAYER_A, "Mất tín hiệu launcher")

        assert fake.commands == []


def test_kick_that_cannot_connect_does_not_raise(tmp_path):
    bridge, _ = build(tmp_path, mode="rcon", rcon_host="127.0.0.1",
                      rcon_port=FakeEvrimaRconServer.find_unused_port(), rcon_password="mat-khau-rcon",
                      kick_on_revoke=True)

    bridge.kick(PLAYER_A, "Admin đã thu hồi suất chơi.")


def test_file_mode_writes_one_steam_id_per_line_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "whitelist.txt"
    bridge, _ = build(tmp_path, mode="file", file_path=str(path))

    bridge.grant(PLAYER_A)
    bridge.grant(PLAYER_B)
    assert sorted(line for line in path.read_text(encoding="utf-8").splitlines() if line) == [PLAYER_A, PLAYER_B]

    bridge.revoke(PLAYER_A)
    assert [line for line in path.read_text(encoding="utf-8").splitlines() if line] == [PLAYER_B]
    assert not os.path.exists(str(path) + ".tmp"), "the temp file must be swapped in, not left behind"


def test_file_mode_without_a_path_does_not_raise(tmp_path):
    bridge, store = build(tmp_path, mode="file")

    bridge.grant(PLAYER_A)

    assert store.list_whitelist() == [PLAYER_A]


def test_none_mode_only_changes_the_database(tmp_path):
    path = tmp_path / "must-not-be-created.txt"
    bridge, store = build(tmp_path, mode="none", file_path=str(path))  # configured, but none must not use it

    bridge.grant(PLAYER_A)

    assert store.list_whitelist() == [PLAYER_A]
    assert not path.exists()
