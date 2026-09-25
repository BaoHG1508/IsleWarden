"""RCON client for The Isle EVRIMA's binary protocol.

auth = 0x01 + password + 0x00; command = 0x02 + opcode + argument + 0x00. Multi-value arguments are
comma-separated. One connection per command keeps it simple and robust.
"""

import socket
import unicodedata

OP_AUTH = 0x01
OP_EXEC = 0x02
OP_ANNOUNCE = 0x10
OP_KICK = 0x30
OP_ADD_WHITELIST = 0x82
OP_REMOVE_WHITELIST = 0x83

CONNECT_TIMEOUT_SECONDS = 8.0
REPLY_TIMEOUT_SECONDS = 3.0


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

    def _send(self, opcode: int, argument: str) -> str:
        """Raises OSError when the game server can't be reached; callers log it and carry on."""
        with socket.create_connection((self._host, self._port), timeout=CONNECT_TIMEOUT_SECONDS) as sock:
            sock.sendall(bytes([OP_AUTH]) + self._password.encode("utf-8") + b"\x00")
            _drain(sock)  # consume the auth reply (if any) so it is not mistaken for the command's
            sock.sendall(bytes([OP_EXEC, opcode]) + argument.encode("utf-8") + b"\x00")
            return _drain(sock)


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
