"""Server settings, read the way the C# server read them so existing deployments and docs carry over:
the "IsleWarden" section of appsettings.json, overridden by IsleWarden__<Key> environment variables
(nested keys joined by "__"). Keys match case-insensitively.
"""

import os
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import timedelta
from pathlib import Path
from types import UnionType
from typing import Any, Mapping

from .enums import Severity
from .wire import loads_lenient

SECTION = "IsleWarden"


class SettingsError(Exception):
    pass


@dataclass
class WhitelistSettings:
    # none = log only (safe default) · rcon = push over RCON · file = write a whitelist file
    mode: str = "none"
    rcon_host: str | None = None
    rcon_port: int = 8888
    rcon_password: str | None = None
    # One Steam ID per line, for mode = file.
    file_path: str | None = None
    # Also send RCON kick (0x30) when a player's last lease ends. The opcode is unverified against a real
    # server, and whether whitelist removal alone drops a player already in the game is unknown.
    kick_on_revoke: bool = False

    @property
    def is_rcon(self) -> bool:
        return (self.mode or "").lower() == "rcon"


@dataclass
class DiscordSettings:
    """Admin alerts through a webhook, and the sign-in and role check every player must pass."""

    webhook_url: str | None = None
    min_severity: Severity = Severity.MEDIUM
    # Players must sign in with a Discord account that is in guild_id and holds one of required_role_ids.
    # False = Steam-only login with no role check; for local testing only.
    required: bool = True
    # OAuth2 client of the Discord application players sign in with.
    client_id: str | None = None
    client_secret: str | None = None
    # The same application's bot, used to read members' roles. It must be in the guild; it needs no permissions.
    bot_token: str | None = None
    guild_id: str | None = None
    # Holding any one of these roles allows playing. Empty = guild membership alone is enough.
    required_role_ids: list[str] = field(default_factory=list)
    # How often a player's role is re-checked while they hold a lease; losing the role ends the lease.
    role_recheck_minutes: int = 10


@dataclass
class RiskSettings:
    """Risk scoring for the dashboard review queue. The score never blocks anyone."""

    window_days: int = 14
    # Days after which a finding counts for half its points.
    half_life_days: float = 7
    low_weight: float = 1
    medium_weight: float = 5
    high_weight: float = 20
    critical_weight: float = 40
    # Below this is Low; below medium_ceiling is Medium; anything higher is High.
    low_ceiling: int = 10
    medium_ceiling: int = 35


@dataclass
class Settings:
    database_path: str = "islewarden.db"
    policy_path: str = "server-policy.json"
    baseline_directory: str = "baselines"
    consent_url: str | None = None
    # Base URL players' browsers reach this server at, e.g. https://ac.example.com. Steam and Discord send the
    # browser back here, so it must match the redirect URL registered in the Discord application. None = taken
    # from each request, which is fine locally but unreliable behind a reverse proxy.
    public_url: str | None = None
    admin_key: str | None = None
    # Keep fixed: changing it breaks every existing hardware ban and match.
    fingerprint_pepper: str | None = None
    heartbeat_seconds: int = 30
    # Heartbeat periods a lease survives without a heartbeat: 30 × 2.5 = 75 s rides out a network blip or a
    # launcher restart.
    missed_heartbeat_grace: float = 2.5
    # Even when true, a device with a risk flag waits for an admin.
    auto_approve_devices: bool = True
    # Master switch: false suspends every anti-cheat bypass (e.g. during a tournament) without deleting them.
    allow_anti_cheat_bypass: bool = True
    enforce_threshold: Severity = Severity.HIGH
    whitelist: WhitelistSettings = field(default_factory=WhitelistSettings)
    discord: DiscordSettings = field(default_factory=DiscordSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)

    @property
    def lease_grace(self) -> timedelta:
        """How long a lease stays valid after its last heartbeat; used for both the expiry and the sweeper."""
        return timedelta(seconds=self.heartbeat_seconds * max(1.0, self.missed_heartbeat_grace))


def load_settings(config_path: str | os.PathLike | None = "appsettings.json", *, dev: bool = False,
                  environ: Mapping[str, str] | None = None) -> Settings:
    """Missing files are skipped; the defaults above apply. dev also layers appsettings.Development.json."""
    settings = Settings()
    if config_path is not None:
        path = Path(config_path)
        files = [path]
        if dev:
            files.append(path.with_name(f"{path.stem}.Development{path.suffix}"))
        for file in files:
            if file.is_file():
                _apply(settings, _read_section(file), str(file))
    _apply_environment(settings, os.environ if environ is None else environ)
    return settings


def _read_section(path: Path) -> dict:
    try:
        document = loads_lenient(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise SettingsError(f"Không đọc được {path}: {ex}") from ex
    if not isinstance(document, dict):
        return {}
    for key, value in document.items():
        if key.lower() == SECTION.lower():
            return value if isinstance(value, dict) else {}
    return {}


def _apply_environment(settings: Settings, environ: Mapping[str, str]) -> None:
    prefix = SECTION.lower() + "__"
    for name, value in environ.items():
        if not name.lower().startswith(prefix):
            continue
        tree: dict = {}
        node = tree
        parts = name[len(prefix):].split("__")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        _apply(settings, tree, f"biến môi trường {name}")


def _apply(target: Any, values: dict, source: str) -> None:
    hints = typing.get_type_hints(type(target))
    by_key = {f.name.replace("_", ""): f for f in fields(target)}
    for key, value in values.items():
        f = by_key.get(str(key).replace("_", "").lower())
        if f is None:
            continue  # unknown keys are ignored, as the .NET binder does
        current = getattr(target, f.name)
        if is_dataclass(current):
            if isinstance(value, dict):
                _apply(current, value, source)
            continue
        try:
            converted = _convert(value, hints[f.name], current)
        except (TypeError, ValueError) as ex:
            raise SettingsError(f"{source}: giá trị không hợp lệ cho {key}: {value!r} ({ex})") from ex
        if converted is not _KEEP:
            setattr(target, f.name, converted)


_KEEP = object()


def _convert(value: Any, hint: Any, current: Any = None) -> Any:
    if typing.get_origin(hint) is list:
        return _convert_list(value, typing.get_args(hint)[0], current or [])

    optional = False
    if isinstance(hint, UnionType) or typing.get_origin(hint) is typing.Union:
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        optional = len(args) < len(typing.get_args(hint))
        hint = args[0]

    if value is None:
        return None if optional else _KEEP
    if hint is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError("cần true hoặc false")
    if hint is int:
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise ValueError("cần số nguyên")
        return int(value)
    if hint is float:
        if isinstance(value, bool):
            raise ValueError("cần số")
        return float(value)
    if hint is Severity:
        return Severity.parse(value)
    if hint is str:
        if isinstance(value, (dict, list)):
            raise ValueError("cần chuỗi")
        return value if isinstance(value, str) else str(value)
    raise TypeError(f"unsupported setting type {hint}")


def _convert_list(value: Any, item_hint: Any, current: list) -> list:
    """A JSON array, or indexed keys as .NET binds them (IsleWarden__Discord__RequiredRoleIds__0=...), which
    replace items by position and keep the rest."""
    if isinstance(value, list):
        return [_convert(item, item_hint) for item in value]
    if isinstance(value, dict):
        items = list(current)
        for index, item in sorted(((int(k), v) for k, v in value.items()), key=lambda pair: pair[0]):
            if index < 0 or index > len(items):
                raise ValueError(f"chỉ số {index} không liên tục")
            converted = _convert(item, item_hint)
            if index == len(items):
                items.append(converted)
            else:
                items[index] = converted
        return items
    if value is None:
        return []
    raise ValueError("cần danh sách (mảng JSON hoặc các khoá __0, __1...)")
