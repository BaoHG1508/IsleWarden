import re
from datetime import datetime, timezone

MIN_UTC = datetime(1, 1, 1, tzinfo=timezone.utc)

_FRACTION = re.compile(r"\.(\d+)")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    """Formats a time like .NET's "O" specifier in UTC, e.g. 2026-09-25T10:11:12.1234560+00:00.

    The database compares timestamp columns as strings, and databases created by the earlier C# server
    already hold this exact form, so every timestamp must be written the same way for ordering and range
    filters to stay correct.
    """
    text = value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    return text + "0+00:00"


def parse_iso(text: str) -> datetime:
    """Parses ISO 8601 from .NET (7 fraction digits, trimmed zeros) or JavaScript ("Z"). No offset means UTC."""
    text = text.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    # Python 3.10 only accepts exactly 3 or 6 fraction digits.
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_iso_or_none(text: str | None) -> datetime | None:
    return None if text is None else parse_iso(text)


def universal(value: datetime) -> str:
    """.NET's "u" format, used in admin log notes: 2026-10-01 23:59:59Z."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
