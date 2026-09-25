namespace IsleWarden.Core;

/// <summary>
/// Checks that the game was started after the launcher, so a player cannot start the game
/// unprotected and then open the launcher just for show.
/// </summary>
public sealed class StartupOrderChecker
{
    private readonly IProcessSource _processes;

    public StartupOrderChecker() : this(new SystemProcessSource())
    {
    }

    public StartupOrderChecker(IProcessSource processes) => _processes = processes;

    public IEnumerable<Finding> Scan(Policy policy, ScanContext context)
    {
        var rule = policy.StartupOrder;
        if (rule is not { Enabled: true } || string.IsNullOrWhiteSpace(policy.GameProcessName))
            yield break;

        var gameName = ProcessScanner.NormalizeName(policy.GameProcessName);
        var limit = context.AgentStartedUtc - TimeSpan.FromSeconds(Math.Max(0, rule.ToleranceSeconds));

        foreach (var p in _processes.GetProcesses())
        {
            if (ProcessScanner.NormalizeName(p.Name) != gameName)
                continue;

            // An unreadable start time proves nothing; skip it to avoid false positives.
            var started = _processes.TryGetStartTimeUtc(p.Id);
            if (started is null || started >= limit)
                continue;

            yield return new Finding(
                FindingCodes.GameStartedBeforeLauncher,
                rule.Severity,
                $"Game đã chạy trước khi mở launcher: {p.Name} (PID {p.Id})",
                $"game={started:O}; launcher={context.AgentStartedUtc:O}");
        }
    }
}
