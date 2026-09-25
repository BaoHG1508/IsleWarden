"""RCON client for The Isle EVRIMA's binary protocol.

auth = 0x01 + password + 0x00; command = 0x02 + opcode + argument + 0x00. Multi-value arguments are
comma-separated. One connection per command keeps it simple and robust.
"""

import re
import socket
import unicodedata

OP_AUTH = 0x01
OP_EXEC = 0x02
OP_ANNOUNCE = 0x10
OP_KICK = 0x30
OP_PLAYER_LIST = 0x40
OP_ADD_WHITELIST = 0x82
OP_REMOVE_WHITELIST = 0x83

CONNECT_TIMEOUT_SECONDS = 8.0
REPLY_TIMEOUT_SECONDS = 3.0
# A long reply (the player list) arrives in several packets; this much silence after the first one ends it.
REPLY_IDLE_SECONDS = 0.5
MAX_REPLY_BYTES = 512 * 1024

_STEAM_ID = re.compile(r"(?<!\d)7656119\d{10}(?!\d)")


class EvrimaRconClient:
    def __init__(self, host: str, port: int, password: str):
        self._host = host
        self._port = port
        self._password = password

    def add_whitelist(self, steam_id: str) -> str:
        return self._send(OP_ADD_WHITELIST, steam_id)

    def remove_whitelist(self, steam_id: str) -> str:
        return self._send(OP_REMOVE_WHITELIST, steam_id)

    def announce(self, message: str) -> str:
        return self._send(OP_ANNOUNCE, message)

    def kick(self, steam_id: str, reason: str) -> str:
        """Opcode 0x30 and the "steamId,reason" layout come from public RCON libraries, NOT verified against a
        real server."""
        return self._send(OP_KICK, f"{steam_id},{free_text(reason)}")

    def player_list(self) -> str:
        """The raw reply of playerlist (0x40). The opcode comes from public RCON libraries and the reply layout
        isn't documented, NOT verified against a real server: read Steam IDs out of it with parse_steam_ids."""
        return self._send(OP_PLAYER_LIST, "", whole_reply=True)

    def _send(self, opcode: int, argument: str, whole_reply: bool = False) -> str:
        """Raises OSError when the game server can't be reached; callers log it and carry on."""
        with socket.create_connection((self._host, self._port), timeout=CONNECT_TIMEOUT_SECONDS) as sock:
            sock.sendall(bytes([OP_AUTH]) + self._password.encode("utf-8") + b"\x00")
            _drain(sock)  # consume the auth reply (if any) so it is not mistaken for the command's
            sock.sendall(bytes([OP_EXEC, opcode]) + argument.encode("utf-8") + b"\x00")
            return _drain_all(sock) if whole_reply else _drain(sock)


def parse_steam_ids(reply: str) -> list[str]:
    """Every SteamID64 in a reply, in order and without repeats. Matching the ID itself rather than a layout
    keeps working whatever separators or header the game server uses."""
    return list(dict.fromkeys(_STEAM_ID.findall(reply)))


def free_text(text: str) -> str:
    """Free text inside an argument: a comma is Evrima's argument separator and 0x00 ends the frame, so both
    (and any other control character) become spaces."""
    clean = "".join(" " if c == "," or unicodedata.category(c) == "Cc" else c for c in text).strip()
    return clean[:120]


def _drain(sock: socket.socket) -> str:
    """Reads a short reply; the game server may not answer at all, which counts as sent."""
    sock.settimeout(REPLY_TIMEOUT_SECONDS)
    try:
        data = sock.recv(1024)
    except TimeoutError:
        return ""
    return data.decode("utf-8", errors="replace").strip("\x00\r\n ")


def _drain_all(sock: socket.socket) -> str:
    """Reads a reply that may span several packets, until the server goes quiet or hangs up."""
    sock.settimeout(REPLY_TIMEOUT_SECONDS)
    chunks: list[bytes] = []
    received = 0
    try:
        while received < MAX_REPLY_BYTES:
            data = sock.recv(8192)
            if not data:
                break
            chunks.append(data)
            received += len(data)
            sock.settimeout(REPLY_IDLE_SECONDS)
    except TimeoutError:
        pass
    return b"".join(chunks).decode("utf-8", errors="replace").strip("\x00\r\n ")
