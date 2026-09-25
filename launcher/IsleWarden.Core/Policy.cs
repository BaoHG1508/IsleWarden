namespace IsleWarden.Core;

/// <summary>Observe only logs findings; Enforce actually blocks the player (no session token is issued).</summary>
public enum EnforcementMode
{
    Observe,
    Enforce
}

/// <summary>A process that must not run while the player is on the server.</summary>
/// <param name="Name">Process name, with or without ".exe"; matched case-insensitively.</param>
/// <param name="Sha256">If set, report only when the executable's hash matches one of these values.</param>
public sealed record BlockedProcess(
    string Name,
    string? Reason = null,
    Severity Severity = Severity.High,
    string[]? Sha256 = null);

/// <summary>A file whose integrity is verified.</summary>
/// <param name="Path">Supports <c>{GameDir}</c> and environment variables such as <c>%ProgramFiles%</c>.</param>
/// <param name="Sha256">Accepted hashes; list several to allow multiple versions.</param>
/// <param name="RequireSignature">Require a valid Authenticode signature.</param>
/// <param name="ExpectedSigner">Text that must appear in the signer's subject, e.g. "EasyAntiCheat Oy".</param>
public sealed record ProtectedFile(
    string Path,
    string[]? Sha256 = null,
    bool RequireSignature = false,
    string? ExpectedSigner = null);

/// <summary>A module (DLL) that must not be loaded into the game process.</summary>
public sealed record BlockedModule(
    string Name,
    string? Reason = null,
    Severity Severity = Severity.High,
    string[]? Sha256 = null);

/// <summary>Startup order check: the game must be started after the launcher.</summary>
public sealed record StartupOrderRule
{
    public bool Enabled { get; init; } = true;
    public Severity Severity { get; init; } = Severity.Medium;

    /// <summary>Allowed slack in seconds: a game started up to this long before the launcher is not flagged.</summary>
    public int ToleranceSeconds { get; init; } = 5;
}

/// <summary>Inspects the modules (DLLs) loaded in the game process.</summary>
/// <remarks>
/// The game runs under EasyAntiCheat, so reading its module list may be denied; that is only
/// recorded as Info. Try it on a test machine before enabling it for players.
/// </remarks>
public sealed record ModuleScanRule
{
    public bool Enabled { get; init; }
    public List<BlockedModule> BlockedModules { get; init; } = new();

    /// <summary>
    /// A module whose path contains one of these (case-insensitive) is suspicious, e.g. <c>%TEMP%</c>,
    /// <c>\Downloads\</c>. Environment variables are expanded.
    /// </summary>
    public List<string> SuspiciousPaths { get; init; } = new();

    public Severity SuspiciousSeverity { get; init; } = Severity.Medium;
}

/// <summary>Compares game files with the hash baseline for the exact installed game build.</summary>
public sealed record BaselineRule
{
    /// <summary>
    /// Baseline file for local runs, relative to the policy's directory.
    /// When connected to a server, the baseline is downloaded from it by the game's build ID.
    /// </summary>
    public string? Path { get; init; }

    public Severity Severity { get; init; } = Severity.High;

    /// <summary>Report files in the game directory that are not in the baseline, e.g. added .pak/.dll files.</summary>
    public bool ReportUnexpectedFiles { get; init; } = true;

    /// <summary>Hashing budget per scan; large files that don't fit are checked in later scans.</summary>
    public int MaxHashMegabytesPerScan { get; init; } = 512;
}

/// <summary>A known cheat-tool file, matched by name in the configured directories.</summary>
/// <param name="Name">File name with extension, e.g. <c>IsleUnlocker.exe</c>; matched case-insensitively.</param>
/// <param name="Severity">
/// Defaults to Medium: a file on disk only proves the player has the tool, not that they used it
/// (it may have been downloaded and left there). Set High to block outright.
/// </param>
/// <param name="Sha256">If set, report only on a hash match, so harmless files with the same name are not flagged.</param>
public sealed record BlockedFile(
    string Name,
    string? Reason = null,
    Severity Severity = Severity.Medium,
    string[]? Sha256 = null);

/// <summary>Searches selected directories for known cheat-tool files, even if they are not running.</summary>
/// <remarks>
/// Deliberately limited for privacy: it only compares file names with the policy list, never reads file
/// contents (except hashing a name-matched file whose rule lists SHA-256 values), and never records or
/// sends the names of other files. Depth, file-count and time limits keep it from crawling the whole drive.
/// Enabling it requires updating the player disclosure to match.
/// </remarks>
public sealed record FileScanRule
{
    public bool Enabled { get; init; }

    /// <summary>
    /// Directories to search. Supports environment variables (<c>%TEMP%</c>) and the tokens
    /// <c>{Desktop}</c>, <c>{Downloads}</c>, <c>{Documents}</c>, <c>{ProgramFiles}</c>,
    /// <c>{ProgramFilesX86}</c>, <c>{LocalAppData}</c>, <c>{AppData}</c>, <c>{Temp}</c>, <c>{GameDir}</c>.
    /// </summary>
    public List<string> Directories { get; init; } = new();

    /// <summary>Files to look for; if empty, nothing is scanned.</summary>
    public List<BlockedFile> Files { get; init; } = new();

    /// <summary>Maximum subdirectory depth; 0 searches only the directory itself.</summary>
    public int MaxDepth { get; init; } = 2;

    /// <summary>Cap on files examined per scan, as a guard against huge directories.</summary>
    public int MaxFilesExamined { get; init; } = 20000;

    public int TimeoutSeconds { get; init; } = 5;
}

/// <summary>A keyword that suggests cheat software, matched case-insensitively within a process or program name.</summary>
/// <param name="Severity">
/// Defaults to Low: a keyword match is a heuristic, not evidence, and many legitimate programs contain
/// these words. Leave it for admin review; don't set it high enough to trigger an automatic ban.
/// </param>
public sealed record ProcessNameKeyword(
    string Keyword,
    string? Reason = null,
    Severity Severity = Severity.Low);

/// <summary>Collects the names of running processes and flags names that contain keywords.</summary>
/// <remarks>
/// The most privacy-sensitive feature: the list of running software shows what the player uses on
/// their machine. So only process names are sent, never paths, command lines (which may contain
/// tokens or passwords) or window titles. Enabling it requires saying so in the player disclosure.
/// </remarks>
public sealed record ProcessInventoryRule
{
    /// <summary>Include the names of running processes in the scan report.</summary>
    public bool ReportRunningProcesses { get; init; }

    public List<ProcessNameKeyword> Keywords { get; init; } = new();

    /// <summary>Process names that are always ignored, to suppress known false positives (whole name, case-insensitive).</summary>
    public List<string> Allow { get; init; } = new();

    /// <summary>Shorter keywords are ignored because they match too broadly.</summary>
    public int MinKeywordLength { get; init; } = 4;
}

/// <summary>A known program, looked up by name in the Windows execution history (Prefetch).</summary>
/// <param name="Name">Executable name, e.g. <c>IsleUnlocker.exe</c>; ".exe" is optional.</param>
/// <param name="Severity">
/// Defaults to Medium: the history proves the tool ran on the machine, but not that it ran at the
/// same time as the game. Set High to block outright.
/// </param>
public sealed record ExecutedProgram(
    string Name,
    string? Reason = null,
    Severity Severity = Severity.Medium);

/// <summary>
/// Checks the Windows execution history (the Prefetch folder) against known tools, to catch tools
/// that were closed before the launcher started.
/// </summary>
/// <remarks>
/// Prefetch records every program run on the machine, so this is deliberately narrow: it only looks up
/// listed names, only considers the last <see cref="LookbackDays"/> days, and never records programs that
/// don't match. Enabling it requires updating the disclosure and bumping disclosureVersion.
/// Reading the Prefetch folder requires administrator rights.
/// </remarks>
public sealed record ExecutionHistoryRule
{
    public bool Enabled { get; init; }

    /// <summary>Programs to look up. If both Programs and Keywords are empty, nothing is scanned.</summary>
    public List<ExecutedProgram> Programs { get; init; } = new();

    /// <summary>Keywords in program names; only a heuristic, so keep their severity low.</summary>
    public List<ProcessNameKeyword> Keywords { get; init; } = new();

    /// <summary>Names that are always ignored, to suppress known false positives.</summary>
    public List<string> Allow { get; init; } = new();

    public int MinKeywordLength { get; init; } = 4;

    public int LookbackDays { get; init; } = 7;

    public int MaxFilesExamined { get; init; } = 4096;
    public int TimeoutSeconds { get; init; } = 5;

    /// <summary>Overrides the Prefetch directory, mainly for tests; empty means <c>%SystemRoot%\Prefetch</c>.</summary>
    public string? Directory { get; init; }

    /// <summary>Record an Info finding when Prefetch is disabled, which can be a way to hide traces.</summary>
    public bool ReportPrefetchDisabled { get; init; } = true;
}

/// <summary>Anti-cheat policy, loaded from policy.json or downloaded from the server.</summary>
public sealed record Policy
{
    public EnforcementMode Mode { get; init; } = EnforcementMode.Observe;
    public int IntervalSeconds { get; init; } = 30;
    public string DisclosureVersion { get; init; } = "iw-v1";
    public string Disclosure { get; init; } = "";

    /// <summary>Game process name, ".exe" optional, e.g. <c>TheIsleClient-Win64-Shipping</c>.</summary>
    public string? GameProcessName { get; init; }

    /// <summary>Steam App ID used to find the game's install directory and build ID (The Isle: 376210).</summary>
    public string? SteamAppId { get; init; }

    /// <summary>Overrides the game directory, e.g. when the game is not installed through Steam.</summary>
    public string? GameDirectory { get; init; }

    /// <summary>URI or path the launcher uses to start the game, e.g. <c>steam://rungameid/376210</c>.</summary>
    public string? LaunchUri { get; init; }

    public List<BlockedProcess> BlockedProcesses { get; init; } = new();
    public List<ProtectedFile> ProtectedFiles { get; init; } = new();
    public StartupOrderRule? StartupOrder { get; init; }
    public ModuleScanRule? ModuleScan { get; init; }
    public BaselineRule? Baseline { get; init; }
    public FileScanRule? FileScan { get; init; }
    public ProcessInventoryRule? ProcessInventory { get; init; }
    public ExecutionHistoryRule? ExecutionHistory { get; init; }
}
