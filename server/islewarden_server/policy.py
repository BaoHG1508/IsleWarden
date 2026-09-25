"""Loads the server policy (reloaded whenever the file changes) and per-build baselines."""

import logging
import os
import re
import threading

from pydantic import ValidationError

from .models import Baseline, Policy
from .settings import Settings
from .wire import loads_lenient

log = logging.getLogger("islewarden.policy")

# Only safe build IDs, so the path can't leave the baseline directory.
_BUILD_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def is_valid_build_id(build_id: str) -> bool:
    return bool(_BUILD_ID.match(build_id))


class PolicyProvider:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._policy = Policy()
        self._seen_mtime: int | None = None
        self._reload()

    def get_policy(self) -> Policy:
        self._reload_if_changed()
        with self._lock:
            return self._policy

    def envelope(self) -> dict:
        """What GET /api/policy returns; the launcher and consent.html both read it."""
        return {"policy": self.get_policy().to_json(), "consentUrl": self._settings.consent_url}

    def try_get_baseline(self, build_id: str) -> dict | None:
        """The build's baseline as JSON; None if there is no readable <buildId>.json."""
        if not is_valid_build_id(build_id):
            return None
        path = os.path.join(self._settings.baseline_directory, f"{build_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return Baseline.model_validate(loads_lenient(handle.read())).to_json()
        except (OSError, ValueError, ValidationError):
            log.warning("Không đọc được baseline %s", build_id, exc_info=True)
            return None

    def _reload_if_changed(self) -> None:
        try:
            mtime = os.stat(self._settings.policy_path).st_mtime_ns
        except OSError:
            return  # missing or unreadable: keep the current policy
        if mtime != self._seen_mtime:
            self._reload()

    def _reload(self) -> None:
        path = self._settings.policy_path
        with self._lock:
            try:
                mtime = os.stat(path).st_mtime_ns
            except OSError:
                log.warning("Không tìm thấy policy %s — dùng policy rỗng.", path)
                return
            # Remembered even when the file is broken, so it is retried on the next edit, not on every request.
            self._seen_mtime = mtime
            try:
                with open(path, encoding="utf-8") as handle:
                    self._policy = Policy.model_validate(loads_lenient(handle.read()))
                log.info("Đã nạp policy %s (phiên bản consent %s).", path, self._policy.disclosure_version)
            except (OSError, ValueError, ValidationError) as ex:
                log.error("Lỗi đọc policy %s — giữ bản trước. %s", path, ex)
