"""JSON helpers: camelCase output like the C# server's, and the lenient JSON its config files allow."""

import json
from dataclasses import fields, is_dataclass
from datetime import date, datetime

from .enums import DotnetEnum
from .timeutil import iso


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def to_wire(value):
    """Converts records to JSON-ready values: camelCase keys, camelCase enums, "O"-format times.

    Dictionary keys are left alone, as System.Text.Json does (e.g. findingsLast24h: {"high": 3}).
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {camel(f.name): to_wire(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, DotnetEnum):
        return value.wire
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_wire(item) for item in value]
    return value


def dumps(value) -> str:
    """Compact JSON with Vietnamese left unescaped, as stored in the reports table."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_lenient(text: str):
    """Parses JSON that may contain // and /* */ comments and trailing commas (policy and baseline files)."""
    return json.loads(_strip_trailing_commas(_strip_comments(text.lstrip("﻿"))))


def _strip_comments(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("Unterminated /* comment")
            out.append(" ")
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j >= n or text[j] not in "}]":
                out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)
