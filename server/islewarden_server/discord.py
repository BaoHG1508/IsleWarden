"""Admin alerts over a Discord webhook; does nothing when no webhook is configured."""

import json
import logging
import urllib.error
import urllib.request

from . import __version__
from .enums import Severity
from .models import ScanReport
from .settings import Settings

log = logging.getLogger("islewarden.discord")

TIMEOUT_SECONDS = 10


class DiscordNotifier:
    def __init__(self, settings: Settings):
        self._settings = settings

    @property
    def enabled(self) -> bool:
        url = self._settings.discord.webhook_url
        return bool(url and url.strip())

    def notify_findings(self, steam_id: str, report: ScanReport, bypassed: bool) -> None:
        """Reports findings that reach the configured severity. A bypassed player is still reported, but
        labelled so admins don't panic."""
        if not self.enabled:
            return
        minimum = self._settings.discord.min_severity
        worst = max((f.severity for f in report.findings), key=lambda s: s.rank, default=Severity.INFO)
        if worst.rank < minimum.rank:
            return

        lines = [f"• [{f.severity.value}] {f.code}: {f.message}"
                 for f in report.findings if f.severity.rank >= minimum.rank][:10]
        note = " · _đang được miễn trừ anti-cheat, không bị chặn_" if bypassed else ""
        self._send(f"⚠️ **Phát hiện gian lận** — Steam `{steam_id}` (máy `{report.machine}`){note}\n"
                   + "\n".join(lines))

    def notify_event(self, message: str) -> None:
        """Lease revoked, heartbeats lost, ban, new device to review..."""
        if self.enabled:
            self._send(message)

    def _send(self, content: str) -> None:
        request = urllib.request.Request(
            self._settings.discord.webhook_url.strip(),
            data=json.dumps({"content": content}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": f"IsleWarden.Server/{__version__}"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
                pass
        except urllib.error.HTTPError as ex:
            log.warning("Discord webhook trả %s", ex.code)
        except Exception:
            log.warning("Không gửi được cảnh báo Discord.", exc_info=True)
