"""Background thread that expires leases whose heartbeats stopped for longer than the grace period and drops
them from the whitelist: the "launcher went silent, so leave the server" mechanism."""

import logging
import threading

from .sessions import SessionManager
from .settings import Settings
from .store import Store
from .timeutil import utc_now

log = logging.getLogger("islewarden.sweeper")


class SessionSweeper:
    def __init__(self, settings: Settings, store: Store, sessions: SessionManager):
        self._settings = settings
        self._store = store
        self._sessions = sessions
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="session-sweeper", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def sweep(self) -> None:
        cutoff = utc_now() - self._settings.lease_grace
        for session in self._store.list_active_sessions():
            if session.last_heartbeat_utc < cutoff:
                self._sessions.expire(session, cutoff)

    def _run(self) -> None:
        # More often than the heartbeat period, so expiry lands close to the deadline.
        interval = max(5.0, self._settings.heartbeat_seconds / 2)
        log.info("SessionSweeper chạy mỗi %gs.", interval)
        while not self._stop.wait(interval):
            try:
                self.sweep()
            except Exception:
                log.exception("Lỗi khi quét phiên hết hạn.")
