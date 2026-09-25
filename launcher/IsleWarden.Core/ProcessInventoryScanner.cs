namespace IsleWarden.Core;

/// <param name="Names">null unless the policy enables <c>reportRunningProcesses</c>.</param>
public sealed record ProcessInventoryResult(IReadOnlyList<string>? Names, IReadOnlyList<Finding> Findings);

/// <summary>
/// Inventories running processes: sends their names to the server (if enabled) and flags names
/// containing keywords common in cheat software (aimbot, injector, spoofer...).
/// </summary>
/// <remarks>
/// Two deliberate limits:
/// 1. Only process names are collected, never paths, command lines (which often contain tokens or
///    passwords) or window titles.
/// 2. A keyword match is only a heuristic, so it defaults to Low for admin review rather than an
///    automatic ban: many legitimate programs have "trainer", "unlocker", "inject"... in their names.
/// </remarks>
public sealed class ProcessInventoryScanner
{
    private readonly IProcessSource _processes;

    public ProcessInventoryScanner() : this(new SystemProcessSource())
    {
    }

    public ProcessInventoryScanner(IProcessSource processes) => _processes = processes;

    public ProcessInventoryResult Collect(Policy policy)
    {
        var rule = policy.ProcessInventory;
        if (rule is null || (!rule.ReportRunningProcesses && rule.Keywords.Count == 0))
            return new ProcessInventoryResult(null, []);

        var allow = new HashSet<string>(
            rule.Allow.Select(a => a.Trim()).Where(a => a.Length > 0),
            StringComparer.OrdinalIgnoreCase);

        // Short keywords match too broadly ("esp" matches "respondus"), so they are dropped.
        var keywords = rule.Keywords
            .Where(k => k.Keyword.Trim().Length >= Math.Max(1, rule.MinKeywordLength))
            .Select(k => k with { Keyword = k.Keyword.Trim() })
            .ToList();

        var names = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        var findings = new List<Finding>();
        var flagged = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var process in _processes.GetProcesses())
        {
            var name = process.Name.Trim();
            if (name.Length == 0)
                continue;

            names.Add(name);

            if (allow.Contains(name) || !flagged.Add(name))
                continue; // Allow-listed, or already reported (several processes can share a name).

            var hit = keywords.FirstOrDefault(
                k => name.Contains(k.Keyword, StringComparison.OrdinalIgnoreCase));
            if (hit is not null)
            {
                findings.Add(new Finding(
                    FindingCodes.SuspiciousProcessName,
                    hit.Severity,
                    $"Tên tiến trình khớp từ khoá nghi vấn: {name}",
                    hit.Reason is null ? $"từ khoá “{hit.Keyword}”" : $"từ khoá “{hit.Keyword}”: {hit.Reason}"));
            }
        }

        return new ProcessInventoryResult(
            rule.ReportRunningProcesses ? names.ToList() : null,
            findings);
    }
}
