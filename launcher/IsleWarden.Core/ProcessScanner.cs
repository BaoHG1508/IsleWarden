namespace IsleWarden.Core;

/// <summary>
/// Checks running processes against the policy's blocklist, matching names case-insensitively.
/// If a rule lists SHA-256 hashes, only a matching executable is reported, so unrelated software
/// with the same name is not flagged.
/// </summary>
public sealed class ProcessScanner
{
    private readonly IProcessSource _processes;
    private readonly FileHashCache _hashes;

    public ProcessScanner() : this(new SystemProcessSource(), new FileHashCache())
    {
    }

    public ProcessScanner(IProcessSource processes, FileHashCache hashes)
    {
        _processes = processes;
        _hashes = hashes;
    }

    public IEnumerable<Finding> Scan(Policy policy)
    {
        if (policy.BlockedProcesses.Count == 0)
            yield break;

        var rules = policy.BlockedProcesses
            .GroupBy(b => NormalizeName(b.Name))
            .ToDictionary(g => g.Key, g => g.First());

        foreach (var p in _processes.GetProcesses())
        {
            if (!rules.TryGetValue(NormalizeName(p.Name), out var rule))
                continue;

            var path = _processes.TryGetExecutablePath(p.Id);

            // When the rule lists hashes, only a match counts; an unreadable file proves nothing, so it is skipped.
            if (rule.Sha256 is { Length: > 0 })
            {
                if (path is null)
                    continue;

                var hash = _hashes.TryGetSha256(path);
                if (hash is null ||
                    !rule.Sha256.Any(h => h.Equals(hash, StringComparison.OrdinalIgnoreCase)))
                {
                    continue;
                }
            }

            var detail = rule.Reason is null
                ? path
                : path is null ? rule.Reason : $"{rule.Reason} — {path}";

            yield return new Finding(
                FindingCodes.BlockedProcess,
                rule.Severity,
                $"Phát hiện tiến trình bị cấm: {p.Name} (PID {p.Id})",
                detail);
        }
    }

    internal static string NormalizeName(string name)
    {
        var normalized = name.Trim().ToLowerInvariant();
        return normalized.EndsWith(".exe", StringComparison.Ordinal) ? normalized[..^4] : normalized;
    }
}
