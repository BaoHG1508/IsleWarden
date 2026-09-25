"""A fake RCON server speaking EVRIMA's binary protocol, so the whitelist bridge is testable without a game server.

Listens on 127.0.0.1 on an OS-assigned port. Each frame is recorded before the reply is sent, so once a client
call returns, its frame is already in `frames`.
"""

import socket
import threading
from typing import NamedTuple

AUTH_REPLY = "Password Accepted"
DEFAULT_COMMAND_REPLY = "Whitelist updated"


class RconFrame(NamedTuple):
    leading: int
    opcode: int  # 0 for non-command frames
    payload: str

    @property
    def is_auth(self) -> bool:
        return self.leading == 0x01

    @property
    def is_command(self) -> bool:
        return self.leading == 0x02


class FakeEvrimaRconServer:
    def __init__(self, silent_to_commands: bool = False, command_reply: str = DEFAULT_COMMAND_REPLY):
        self._silent = silent_to_commands
        self._command_reply = command_reply
        self._frames: list[RconFrame] = []
        self._lock = threading.Lock()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self._listener.close()

    @property
    def frames(self) -> list[RconFrame]:
        with self._lock:
            return list(self._frames)

    @property
    def commands(self) -> list[RconFrame]:
        return [f for f in self.frames if f.is_command]

    @staticmethod
    def find_unused_port() -> int:
        with socket.create_server(("127.0.0.1", 0)) as probe:
            return probe.getsockname()[1]

    def _accept_loop(self) -> None:
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return  # listener closed
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection: socket.socket) -> None:
        with connection:
            pending = bytearray()
            while True:
                try:
                    data = connection.recv(512)
                except OSError:
                    return
                if not data:
                    return
                for byte in data:
                    if byte != 0x00:
                        pending.append(byte)
                        continue
                    frame = _decode(bytes(pending))  # 0x00 ends a frame
                    pending.clear()
                    with self._lock:
                        self._frames.append(frame)
                    reply = None if frame.is_command and self._silent else (
                        self._command_reply if frame.is_command else AUTH_REPLY)
                    if reply is not None:
                        connection.sendall(reply.encode("utf-8"))


def _decode(frame: bytes) -> RconFrame:
    if not frame:
        return RconFrame(0, 0, "")
    if frame[0] == 0x02 and len(frame) >= 2:
        return RconFrame(frame[0], frame[1], frame[2:].decode("utf-8"))
    return RconFrame(frame[0], 0, frame[1:].decode("utf-8"))
