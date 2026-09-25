from datetime import datetime, timezone

import pytest

from islewarden_server.timeutil import iso, parse_iso
from islewarden_server.wire import camel, loads_lenient


def test_lenient_json_drops_comments_and_trailing_commas_but_not_string_content():
    text = """
    {
      // line comment
      "url": "http://example.com/a//b", /* block
      comment */ "quote": "say \\"hi\\" // not a comment",
      "list": [1, 2, 3,],
    }
    """
    assert loads_lenient(text) == {"url": "http://example.com/a//b", "quote": 'say "hi" // not a comment',
                                   "list": [1, 2, 3]}


def test_lenient_json_accepts_a_byte_order_mark():
    assert loads_lenient('﻿{"a": 1}') == {"a": 1}


def test_lenient_json_still_rejects_broken_json():
    with pytest.raises(ValueError):
        loads_lenient('{"a": }')


def test_iso_matches_dotnet_round_trip_format():
    when = datetime(2026, 9, 25, 10, 11, 12, 123456, tzinfo=timezone.utc)
    assert iso(when) == "2026-09-25T10:11:12.1234560+00:00"
    assert iso(datetime(1, 1, 1, tzinfo=timezone.utc)) == "0001-01-01T00:00:00.0000000+00:00"


@pytest.mark.parametrize("text", ["2026-09-25T10:11:12.1234567+00:00", "2026-09-25T10:11:12.123456Z",
                                  "2026-09-25T17:11:12.123456+07:00", "2026-09-25T10:11:12.123456"])
def test_parse_iso_accepts_dotnet_javascript_and_offsets(text):
    assert parse_iso(text) == datetime(2026, 9, 25, 10, 11, 12, 123456, tzinfo=timezone.utc)


def test_parse_iso_accepts_trimmed_fractions():
    assert parse_iso("2026-09-25T10:11:12.5+00:00").microsecond == 500000
    assert parse_iso("2026-09-25T10:11:12+00:00").microsecond == 0


def test_camel():
    assert camel("anti_cheat_bypassed") == "antiCheatBypassed"
    assert camel("players_last24h") == "playersLast24h"
    assert camel("id") == "id"
