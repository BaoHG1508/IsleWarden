import json
from datetime import timedelta

import pytest

from islewarden_server.enums import Severity
from islewarden_server.settings import SettingsError, load_settings


def write(path, section: dict) -> None:
    path.write_text(json.dumps({"Logging": {}, "IsleWarden": section}), encoding="utf-8")


def test_reads_the_isle_warden_section_like_the_csharp_server(tmp_path):
    config = tmp_path / "appsettings.json"
    write(config, {"DatabasePath": "data/x.db", "EnforceThreshold": "critical", "AllowAntiCheatBypass": False,
                   "Whitelist": {"Mode": "rcon", "RconPort": 9999}, "Risk": {"HalfLifeDays": 3.5}})

    settings = load_settings(config, environ={})

    assert settings.database_path == "data/x.db"
    assert settings.enforce_threshold == Severity.CRITICAL
    assert settings.allow_anti_cheat_bypass is False
    assert (settings.whitelist.mode, settings.whitelist.rcon_port) == ("rcon", 9999)
    assert settings.risk.half_life_days == 3.5
    assert settings.heartbeat_seconds == 30  # untouched default


def test_dev_overlay_and_environment_variables_win(tmp_path):
    config = tmp_path / "appsettings.json"
    write(config, {"AdminKey": "from-file", "HeartbeatSeconds": 20})
    write(tmp_path / "appsettings.Development.json", {"AdminKey": "from-dev"})

    settings = load_settings(config, dev=True, environ={
        "ISLEWARDEN__HEARTBEATSECONDS": "40",  # Windows upper-cases environment variable names
        "IsleWarden__Whitelist__KickOnRevoke": "true",
        "OTHER__AdminKey": "ignored",
    })

    assert settings.admin_key == "from-dev"
    assert settings.heartbeat_seconds == 40
    assert settings.whitelist.kick_on_revoke is True
    assert settings.lease_grace == timedelta(seconds=100)


def test_role_lists_come_from_a_json_array_or_indexed_variables(tmp_path):
    config = tmp_path / "appsettings.json"
    write(config, {"Discord": {"Required": False, "RequiredRoleIds": ["111", 222, "333"], "GuildId": 42}})

    from_file = load_settings(config, environ={})
    overridden = load_settings(config, environ={"IsleWarden__Discord__RequiredRoleIds__1": "999",
                                                "IsleWarden__Discord__RequiredRoleIds__3": "444"})

    assert from_file.discord.required is False
    assert from_file.discord.guild_id == "42"
    assert from_file.discord.required_role_ids == ["111", "222", "333"]
    assert overridden.discord.required_role_ids == ["111", "999", "333", "444"]  # by position, like .NET


def test_kick_without_lease_is_off_by_default_and_reads_its_exempt_list(tmp_path):
    config = tmp_path / "appsettings.json"
    write(config, {"Whitelist": {"KickWithoutLease": True, "KickGraceSeconds": 90,
                                 "ExemptSteamIds": ["76561198000000001"]}})

    defaults = load_settings(None, environ={})
    configured = load_settings(config, environ={"IsleWarden__Whitelist__ExemptSteamIds__1": "76561198000000002"})

    assert (defaults.whitelist.kick_without_lease, defaults.whitelist.kick_poll_seconds,
            defaults.whitelist.kick_grace_seconds, defaults.whitelist.exempt_steam_ids) == (False, 20, 60, [])
    assert configured.whitelist.kick_without_lease is True
    assert configured.whitelist.kick_grace_seconds == 90
    assert configured.whitelist.exempt_steam_ids == ["76561198000000001", "76561198000000002"]


def test_discord_is_required_by_default():
    settings = load_settings(None, environ={})

    assert settings.discord.required is True
    assert settings.discord.required_role_ids == []
    assert settings.public_url is None


def test_missing_file_means_defaults(tmp_path):
    settings = load_settings(tmp_path / "nope.json", environ={})

    assert settings.admin_key is None
    assert settings.lease_grace == timedelta(seconds=75)


def test_grace_never_drops_below_one_heartbeat(tmp_path):
    settings = load_settings(None, environ={"IsleWarden__MissedHeartbeatGrace": "0.2"})

    assert settings.lease_grace == timedelta(seconds=30)


@pytest.mark.parametrize("name,value", [("IsleWarden__HeartbeatSeconds", "abc"),
                                        ("IsleWarden__AutoApproveDevices", "yes please"),
                                        ("IsleWarden__EnforceThreshold", "extreme")])
def test_invalid_values_stop_startup_with_a_clear_message(name, value):
    with pytest.raises(SettingsError, match=name):
        load_settings(None, environ={name: value})
