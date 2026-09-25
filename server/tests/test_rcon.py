"""The exact frames on the wire. This is the part most likely to break silently: the game server doesn't report
a malformed frame, it just quietly doesn't add anyone to the whitelist."""

import pytest
from fake_rcon import DEFAULT_COMMAND_REPLY, FakeEvrimaRconServer

from islewarden_server import rcon
from islewarden_server.rcon import EvrimaRconClient

PASSWORD = "mat-khau-rcon"
STEAM_ID = "76561198000000001"


def test_add_whitelist_authenticates_then_sends_opcode_82():
    with FakeEvrimaRconServer() as fake:
        response = EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).add_whitelist(STEAM_ID)

        assert response == DEFAULT_COMMAND_REPLY  # the command's reply, not the auth reply
        auth, command = fake.frames
        assert auth.is_auth and auth.payload == PASSWORD
        assert command.is_command and command.opcode == rcon.OP_ADD_WHITELIST and command.payload == STEAM_ID


def test_remove_whitelist_sends_opcode_83():
    with FakeEvrimaRconServer() as fake:
        EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).remove_whitelist(STEAM_ID)

        [command] = fake.commands
        assert (command.opcode, command.payload) == (rcon.OP_REMOVE_WHITELIST, STEAM_ID)


def test_announce_sends_opcode_10():
    with FakeEvrimaRconServer() as fake:
        EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).announce("Server se khoi dong lai sau 5 phut")

        [command] = fake.commands
        assert (command.opcode, command.payload) == (rcon.OP_ANNOUNCE, "Server se khoi dong lai sau 5 phut")


def test_kick_sends_opcode_30_with_a_reason_that_cannot_split_the_arguments():
    with FakeEvrimaRconServer() as fake:
        EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).kick(STEAM_ID, "Mất tín hiệu, launcher\nđã tắt")

        [command] = fake.commands
        assert command.opcode == rcon.OP_KICK
        # Commas separate EVRIMA arguments and control characters could end the frame: both become spaces.
        assert command.payload == f"{STEAM_ID},Mất tín hiệu  launcher đã tắt"


def test_player_list_sends_opcode_40_and_reads_a_reply_split_over_packets():
    # A full server's list is a few KB: more than one recv, so the client must keep reading until it goes quiet.
    steam_ids = [f"765611980000{n:05d}" for n in range(100)]
    reply = "PlayerList\n" + ",".join(f"Dino {n}" for n in range(100)) + ",\n" + ",".join(steam_ids) + ",\n"
    with FakeEvrimaRconServer(replies={rcon.OP_PLAYER_LIST: reply}, chunk_size=700) as fake:
        response = EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).player_list()

        [command] = fake.commands
        assert (command.opcode, command.payload) == (rcon.OP_PLAYER_LIST, "")
        assert rcon.parse_steam_ids(response) == steam_ids


def test_parse_steam_ids_keeps_order_and_skips_repeats_and_other_numbers():
    reply = ("[2026.09.26-12.00.00] PlayerList\nRex,Spino 76561198000000009x,\n"
             "76561198000000001,76561198000000002,76561198000000001,\n"
             "12345678901234567,765611980000000011,EOS:0002a5c3d1e04f")

    assert rcon.parse_steam_ids(reply) == ["76561198000000009", "76561198000000001", "76561198000000002"]
    assert rcon.parse_steam_ids("") == []


def test_multi_value_arguments_keep_their_commas():
    with FakeEvrimaRconServer() as fake:
        EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).announce("mot,hai,ba")

        assert fake.commands[0].payload == "mot,hai,ba"


def test_no_reply_counts_as_sent():
    # The game server may not answer a whitelist opcode at all. Raising would block clean players too.
    # Takes about 3 s: it waits out the reply timeout.
    with FakeEvrimaRconServer(silent_to_commands=True) as fake:
        response = EvrimaRconClient("127.0.0.1", fake.port, PASSWORD).add_whitelist(STEAM_ID)

        assert response == ""
        assert [c.opcode for c in fake.commands] == [rcon.OP_ADD_WHITELIST]  # it still reached the server


def test_unreachable_server_raises_so_the_bridge_can_log_it():
    client = EvrimaRconClient("127.0.0.1", FakeEvrimaRconServer.find_unused_port(), PASSWORD)

    with pytest.raises(OSError):
        client.add_whitelist(STEAM_ID)
