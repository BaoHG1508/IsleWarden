"""Fake RCON server for The Isle EVRIMA: exercises the whitelist bridge without a game server.

Listens on TCP, decodes EVRIMA frames and prints them.
  auth    : 0x01 + password + 0x00
  command : 0x02 + opcode + argument + 0x00   (multiple values separated by commas)

Run:
  python tools/mock_rcon.py --port 8888 --password secret

Then point the server at it:
  IsleWarden__Whitelist__Mode=rcon
  IsleWarden__Whitelist__RconHost=127.0.0.1
  IsleWarden__Whitelist__RconPort=8888
  IsleWarden__Whitelist__RconPassword=secret
  IsleWarden__Whitelist__KickOnRevoke=true   (optional: also send kick 0x30 when a lease ends)
"""

import argparse
import socketserver
import sys
from datetime import datetime

# Only the opcodes this project sends are named; anything else prints as hex so nothing is guessed.
OPCODES = {0x10: "announce", 0x30: "kick", 0x82: "addwhitelist", 0x83: "removewhitelist"}


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        log(f"conn {peer}")
        pending = bytearray()
        try:
            while data := self.request.recv(1024):
                for byte in data:
                    if byte != 0x00:
                        pending.append(byte)
                        continue
                    reply, is_command = describe(bytes(pending), self.server.password)
                    pending.clear()
                    if not (is_command and self.server.silent):
                        self.request.sendall(reply.encode("utf-8"))
        except OSError:
            pass  # client hung up mid-command: normal with this protocol
        log(f"close {peer}")


def describe(frame: bytes, expected_password: str | None) -> tuple[str, bool]:
    """Prints the frame; returns the reply and whether it was a command."""
    if not frame:
        log("  empty frame")
        return "Empty", False
    if frame[0] == 0x01:
        password = frame[1:].decode("utf-8", errors="replace")
        ok = expected_password is None or password == expected_password
        log(f'  auth      password="{password}" -> {"ok" if ok else "MISMATCH"}')
        return ("Password Accepted" if ok else "Password Rejected"), False
    if frame[0] == 0x02 and len(frame) >= 2:
        argument = frame[2:].decode("utf-8", errors="replace")
        log(f'  exec 0x{frame[1]:02x} {OPCODES.get(frame[1], "?"):<16} arg="{argument}"')
        return "Ok", True
    log(f"  unknown   bytes={frame.hex().upper()}")
    return "Unknown", False


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake EVRIMA RCON server")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--password", help="verify the password the server sends")
    parser.add_argument("--silent", action="store_true",
                        help="don't answer commands, like a quiet game server (the client waits 3 s, then moves on)")
    args = parser.parse_args()

    # UTF-8 output even when Windows redirects it in a legacy code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    with Server(("0.0.0.0", args.port), Handler) as server:
        server.password = args.password
        server.silent = args.silent
        print(f"mock-rcon listening on 0.0.0.0:{args.port}")
        print("  password check: " + ("on" if args.password else "off (pass --password to verify what the server sends)"))
        if args.silent:
            print("  silent mode: commands will NOT be answered")
        print("  Ctrl+C to stop\n", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
