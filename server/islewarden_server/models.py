"""Request bodies and the policy/baseline files, as pydantic models mirroring the C# records in IsleWarden.Core.

The launcher (still C#) sends and expects exactly these shapes, so a field renamed here must be renamed in
launcher/IsleWarden.Core too.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, model_validator
from pydantic.alias_generators import to_camel

from .enums import EnforcementMode, Severity
from .timeutil import MIN_UTC, iso, parse_iso


def _parse_time(value: Any) -> Any:
    return parse_iso(value) if isinstance(value, str) else value


# System.Text.Json accepts 7 fraction digits and trimmed zeros; parse_iso handles both.
UtcDateTime = Annotated[datetime, BeforeValidator(_parse_time), PlainSerializer(iso, return_type=str)]
SeverityField = Annotated[Severity, BeforeValidator(Severity.parse), PlainSerializer(lambda s: s.wire, return_type=str)]
ModeField = Annotated[
    EnforcementMode, BeforeValidator(EnforcementMode.parse), PlainSerializer(lambda m: m.wire, return_type=str)
]


class WireModel(BaseModel):
    """camelCase JSON whose property names match case-insensitively, like the C# server's JSON settings."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _match_names_ignoring_case(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        known = {(field.alias or name).lower(): field.alias or name for name, field in cls.model_fields.items()}
        return {known.get(key.lower(), key) if isinstance(key, str) else key: value for key, value in data.items()}

    def to_json(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)


# ---- Scan reports (sent by the launcher) ----

# Stable finding codes from launcher/IsleWarden.Core/FindingCodes.cs, offered as filters in the dashboard.
# Released codes are never renamed; add new ones in both places.
FINDING_CODES = [
    "blocked-process", "suspicious-process-name", "blocked-module", "suspicious-module", "module-scan-unavailable",
    "game-started-before-launcher", "blocked-file",
    "executed-tool", "suspicious-executed-name", "execution-history-unavailable", "execution-history-off",
    "file-missing", "file-unreadable", "file-tampered", "unexpected-file", "unsigned-file", "invalid-signature",
    "wrong-signer", "signature-check-failed", "game-not-found", "baseline-unavailable", "baseline-outdated",
    "baseline-pending",
]


class Finding(WireModel):
    code: str
    severity: SeverityField
    message: str
    detail: str | None = None


class ScanReport(WireModel):
    timestamp_utc: UtcDateTime | None = None
    machine: str = ""
    clean: bool = False
    findings: list[Finding] = Field(default_factory=list)
    # Names only, and only when the policy enables processInventory.reportRunningProcesses.
    processes: list[str] | None = None


# ---- Launcher requests ----


class DeviceFingerprint(WireModel):
    device_id: str | None = None
    components: dict[str, str] = Field(default_factory=dict)


class LoginCompleteRequest(WireModel):
    """Redeems a finished browser login for a device key."""

    # One-time code the server sent to the launcher's loopback listener.
    code: str
    # PKCE verifier: proves this launcher is the one that started the login.
    code_verifier: str
    machine_name: str
    consent_version: str
    fingerprint: DeviceFingerprint | None = None


class SessionStartRequest(WireModel):
    device_id: str
    device_key: str
    consent_version: str
    agent_version: str | None = None
    game_build_id: str | None = None
    report: ScanReport


class HeartbeatRequest(WireModel):
    session_id: str
    token: str
    report: ScanReport
    # The launcher restarted and is resuming the lease it held before.
    resumed: bool = False


class SessionEndRequest(WireModel):
    session_id: str
    token: str
    reason: str | None = None


# ---- Admin requests ----


class CreateBanRequest(WireModel):
    subject_type: str | None = None
    subject_value: str | None = None
    reason: str | None = None
    expires_utc: UtcDateTime | None = None


class BanBySteamRequest(WireModel):
    steam_id: str | None = None
    reason: str | None = None
    expires_utc: UtcDateTime | None = None


class BanPlayerRequest(WireModel):
    reason: str | None = None
    expires_utc: UtcDateTime | None = None
    scope: str | None = "device"
    report_id: int | None = None
    evidence: str | None = None


class NoteRequest(WireModel):
    note: str | None = None


class WatchRequest(WireModel):
    watch: bool = False
    note: str | None = None


class PruneRequest(WireModel):
    days: int = 0


class BypassRequest(WireModel):
    reason: str | None = None
    expires_utc: UtcDateTime | None = None


# ---- Policy (server-policy.json, served to launchers) ----
# Validated here so a typo in the file is rejected on the server (keeping the last good policy) instead of
# being passed on to every launcher, which would then fail to parse it.


class BlockedProcess(WireModel):
    name: str
    reason: str | None = None
    severity: SeverityField = Severity.HIGH
    sha256: list[str] | None = None


class ProtectedFile(WireModel):
    path: str
    sha256: list[str] | None = None
    require_signature: bool = False
    expected_signer: str | None = None


class BlockedModule(WireModel):
    name: str
    reason: str | None = None
    severity: SeverityField = Severity.HIGH
    sha256: list[str] | None = None


class StartupOrderRule(WireModel):
    enabled: bool = True
    severity: SeverityField = Severity.MEDIUM
    tolerance_seconds: int = 5


class ModuleScanRule(WireModel):
    enabled: bool = False
    blocked_modules: list[BlockedModule] = Field(default_factory=list)
    suspicious_paths: list[str] = Field(default_factory=list)
    suspicious_severity: SeverityField = Severity.MEDIUM


class BaselineRule(WireModel):
    path: str | None = None
    severity: SeverityField = Severity.HIGH
    report_unexpected_files: bool = True
    max_hash_megabytes_per_scan: int = 512


class BlockedFile(WireModel):
    name: str
    reason: str | None = None
    severity: SeverityField = Severity.MEDIUM
    sha256: list[str] | None = None


class FileScanRule(WireModel):
    enabled: bool = False
    directories: list[str] = Field(default_factory=list)
    files: list[BlockedFile] = Field(default_factory=list)
    max_depth: int = 2
    max_files_examined: int = 20000
    timeout_seconds: int = 5


class ProcessNameKeyword(WireModel):
    keyword: str
    reason: str | None = None
    severity: SeverityField = Severity.LOW


class ProcessInventoryRule(WireModel):
    report_running_processes: bool = False
    keywords: list[ProcessNameKeyword] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    min_keyword_length: int = 4


class ExecutedProgram(WireModel):
    name: str
    reason: str | None = None
    severity: SeverityField = Severity.MEDIUM


class ExecutionHistoryRule(WireModel):
    enabled: bool = False
    programs: list[ExecutedProgram] = Field(default_factory=list)
    keywords: list[ProcessNameKeyword] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    min_keyword_length: int = 4
    lookback_days: int = 7
    max_files_examined: int = 4096
    timeout_seconds: int = 5
    directory: str | None = None
    report_prefetch_disabled: bool = True


class Policy(WireModel):
    mode: ModeField = EnforcementMode.OBSERVE
    interval_seconds: int = 30
    disclosure_version: str = "iw-v1"
    disclosure: str = ""
    game_process_name: str | None = None
    steam_app_id: str | None = None
    game_directory: str | None = None
    launch_uri: str | None = None
    blocked_processes: list[BlockedProcess] = Field(default_factory=list)
    protected_files: list[ProtectedFile] = Field(default_factory=list)
    startup_order: StartupOrderRule | None = None
    module_scan: ModuleScanRule | None = None
    baseline: BaselineRule | None = None
    file_scan: FileScanRule | None = None
    process_inventory: ProcessInventoryRule | None = None
    execution_history: ExecutionHistoryRule | None = None


# ---- Baseline (per game build, uploaded by an admin, downloaded by launchers) ----


class BaselineFile(WireModel):
    path: str
    size: int
    sha256: str


class Baseline(WireModel):
    version: int = 1
    app_id: str | None = None
    build_id: str | None = None
    created_utc: UtcDateTime = MIN_UTC
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    files: list[BaselineFile] = Field(default_factory=list)
