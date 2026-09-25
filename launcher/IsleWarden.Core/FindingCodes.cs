namespace IsleWarden.Core;

/// <summary>
/// Stable finding codes. The server and admin tools act on these values automatically,
/// so never change a released code; only add new ones.
/// </summary>
public static class FindingCodes
{
    public const string BlockedProcess = "blocked-process";
    public const string SuspiciousProcessName = "suspicious-process-name";
    public const string BlockedModule = "blocked-module";
    public const string SuspiciousModule = "suspicious-module";
    public const string ModuleScanUnavailable = "module-scan-unavailable";
    public const string GameStartedBeforeLauncher = "game-started-before-launcher";

    // A known cheat tool found on disk, even if it is not running.
    public const string BlockedFile = "blocked-file";

    // Windows execution history (Prefetch): tools that ran and have since exited.
    public const string ExecutedTool = "executed-tool";
    public const string SuspiciousExecutedName = "suspicious-executed-name";
    public const string ExecutionHistoryUnavailable = "execution-history-unavailable";
    public const string ExecutionHistoryOff = "execution-history-off";

    public const string FileMissing = "file-missing";
    public const string FileUnreadable = "file-unreadable";
    public const string FileTampered = "file-tampered";
    public const string UnexpectedFile = "unexpected-file";
    public const string UnsignedFile = "unsigned-file";
    public const string InvalidSignature = "invalid-signature";
    public const string WrongSigner = "wrong-signer";
    public const string SignatureCheckFailed = "signature-check-failed";

    public const string GameNotFound = "game-not-found";
    public const string BaselineUnavailable = "baseline-unavailable";
    public const string BaselineOutdated = "baseline-outdated";
    public const string BaselinePending = "baseline-pending";

    public static IReadOnlyList<string> All { get; } =
    [
        BlockedProcess, SuspiciousProcessName, BlockedModule, SuspiciousModule, ModuleScanUnavailable,
        GameStartedBeforeLauncher, BlockedFile,
        ExecutedTool, SuspiciousExecutedName, ExecutionHistoryUnavailable, ExecutionHistoryOff,
        FileMissing, FileUnreadable, FileTampered, UnexpectedFile, UnsignedFile, InvalidSignature, WrongSigner,
        SignatureCheckFailed, GameNotFound, BaselineUnavailable, BaselineOutdated, BaselinePending
    ];
}
