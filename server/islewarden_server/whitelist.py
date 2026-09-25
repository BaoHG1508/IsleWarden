"""Syncs the desired whitelist (the whitelist table) to The Isle game server.

Modes: none (log only, the safe default), rcon (push over RCON), file (write a whitelist file). A failure
talking to the game server is logged and never breaks granting or revoking a lease.
"""

import logging
import os
import threading

from .rcon import EvrimaRconClient
from .settings import Settings
from .store import Store

log = logging.getLogger("islewarden.whitelist")


class WhitelistBridge:
    def __init__(self, settings: Settings, store: Store):
        self._settings = settings
        self._store = store
        self._file_lock = threading.Lock()
        options = settings.whitelist
        self._rcon = (EvrimaRconClient(options.rcon_host, options.rcon_port, options.rcon_password or "")
                      if options.is_rcon and options.rcon_host and options.rcon_host.strip() else None)

    def grant(self, steam_id: str) -> None:
        self._store.add_to_whitelist(steam_id)
        log.info("Whitelist +%s", steam_id)
        self._apply(steam_id, add=True)

    def revoke(self, steam_id: str) -> None:
        """Unconditional: callers decide whether another active lease should keep the player in."""
        self._store.remove_from_whitelist(steam_id)
        log.info("Whitelist -%s", steam_id)
        self._apply(steam_id, add=False)

    def kick(self, steam_id: str, reason: str) -> None:
        """Kicks the player when their last lease ends, only with kick_on_revoke in rcon mode. reason is what
        the player reads, so it must name what dropped them (lost signal is not anti-cheat is not a ban)."""
        options = self._settings.whitelist
        if not options.kick_on_revoke or not options.is_rcon:
            return
        if self._rcon is None:
            log.warning("KickOnRevoke bật nhưng thiếu cấu hình RconHost — không kick được %s.", steam_id)
            return
        try:
            response = self._rcon.kick(steam_id, reason)
            log.info("RCON kick %s (%s) → %s", steam_id, reason, response)
        except Exception:
            log.exception("RCON kick thất bại (%s).", steam_id)

    def _apply(self, steam_id: str, add: bool) -> None:
        operation = "add" if add else "remove"
        mode = (self._settings.whitelist.mode or "").lower()
        try:
            if mode == "rcon":
                self._apply_rcon(steam_id, add)
            elif mode == "file":
                self._write_file()
            else:
                log.debug("Whitelist mode=none: chỉ ghi log (%s %s).", operation, steam_id)
        except Exception:
            log.exception("Đồng bộ whitelist thất bại (%s %s).", operation, steam_id)

    def _apply_rcon(self, steam_id: str, add: bool) -> None:
        if self._rcon is None:
            log.warning("Whitelist mode=rcon nhưng thiếu cấu hình RconHost.")
            return
        response = self._rcon.add_whitelist(steam_id) if add else self._rcon.remove_whitelist(steam_id)
        log.info("RCON %s %s → %s", "addwhitelist" if add else "removewhitelist", steam_id, response)

    def _write_file(self) -> None:
        path = self._settings.whitelist.file_path
        if not path or not path.strip():
            log.warning("Whitelist mode=file nhưng thiếu cấu hình FilePath.")
            return
        with self._file_lock:
            full_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            # Write a temp file, then replace, so the game server never reads a half-written file.
            temp = full_path + ".tmp"
            with open(temp, "w", encoding="utf-8", newline="\n") as handle:
                handle.writelines(steam_id + "\n" for steam_id in self._store.list_whitelist())
            os.replace(temp, full_path)
