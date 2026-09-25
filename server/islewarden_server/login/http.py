"""The small HTTP client the login needs (Steam and Discord), behind an interface tests can replace."""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class HttpUnavailable(Exception):
    """The remote service couldn't be reached (network, DNS, timeout)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self):
        return json.loads(self.body)


class Http(Protocol):
    def send(self, method: str, url: str, *, headers: dict[str, str] | None = None,
             form: dict[str, str] | None = None) -> HttpResponse:
        """Any HTTP status is a response; only an unreachable service raises HttpUnavailable."""


class UrllibHttp:
    def __init__(self, timeout_seconds: float = 10, user_agent: str | None = None):
        self._timeout = timeout_seconds
        self._user_agent = user_agent

    def send(self, method: str, url: str, *, headers: dict[str, str] | None = None,
             form: dict[str, str] | None = None) -> HttpResponse:
        all_headers = dict(headers or {})
        if self._user_agent:
            all_headers.setdefault("User-Agent", self._user_agent)
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode("ascii")
            all_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return HttpResponse(response.status, response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as ex:
            return HttpResponse(ex.code, ex.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as ex:
            raise HttpUnavailable(str(ex)) from ex
