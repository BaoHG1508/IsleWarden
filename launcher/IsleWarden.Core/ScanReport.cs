namespace IsleWarden.Core;

/// <param name="Clean">true when no finding is Low or higher; Info findings are informational only.</param>
public sealed record ScanReport(
    DateTimeOffset TimestampUtc,
    string Machine,
    bool Clean,
    IReadOnlyList<Finding> Findings)
{
    /// <summary>
    /// Running process names, present only when the policy enables <c>processInventory.reportRunningProcesses</c>.
    /// Names only: never paths, command lines or window titles.
    /// </summary>
    public IReadOnlyList<string>? Processes { get; init; }

    public static bool IsClean(IEnumerable<Finding> findings) =>
        !findings.Any(f => f.Severity >= Severity.Low);
}
