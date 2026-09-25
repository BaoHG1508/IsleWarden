namespace IsleWarden.Core;

/// <summary>
/// Inspects the modules (DLLs) loaded in the game process for signs of injection: blocked DLLs,
/// or DLLs loaded from suspicious folders (Temp, Downloads, ...).
/// </summary>
public sealed class ModuleScanner
{
    private readonly IProcessSource _processes;
    private readonly IModuleSource _modules;
    private readonly FileHashCache _hashes;

    public ModuleScanner() : this(new SystemProcessSource(), new SystemModuleSource(), new FileHashCache())
    {
    }

    public ModuleScanner(IProcessSource processes, IModuleSource modules, FileHashCache hashes)
    {
        _processes = processes;
        _modules = modules;
        _hashes = hashes;
    }

    public IEnumerable<Finding> Scan(Policy policy)
    {
        var rule = policy.ModuleScan;
        if (rule is not { Enabled: true } || string.IsNullOrWhiteSpace(policy.GameProcessName))
            yield break;

        var gameName = ProcessScanner.NormalizeName(policy.GameProcessName);
        var blocked = rule.BlockedModules
            .GroupBy(m => m.Name.Trim().ToLowerInvariant())
            .ToDictionary(g => g.Key, g => g.First());
        var suspicious = rule.SuspiciousPaths
            .Select(Environment.ExpandEnvironmentVariables)
            .Where(s => !string.IsNullOrWhiteSpace(s))
            .ToList();

        foreach (var p in _processes.GetProcesses())
        {
            if (ProcessScanner.NormalizeName(p.Name) != gameName)
                continue;

            var modules = _modules.TryGetModules(p.Id, out var error);
            if (modules is null)
            {
                yield return new Finding(FindingCodes.ModuleScanUnavailable, Severity.Info,
                    $"Không đọc được danh sách module của game (PID {p.Id}).", error);
                continue;
            }

            foreach (var module in modules)
            {
                if (Check(module, blocked, suspicious, rule.SuspiciousSeverity) is { } finding)
                    yield return finding;
            }
        }
    }

    private Finding? Check(
        ModuleInfo module,
        Dictionary<string, BlockedModule> blocked,
        List<string> suspicious,
        Severity suspiciousSeverity)
    {
        if (blocked.TryGetValue(module.Name.Trim().ToLowerInvariant(), out var rule))
        {
            // If the rule lists hashes, only a matching hash counts, as in the process scan.
            var matches = rule.Sha256 is not { Length: > 0 } ||
                          (_hashes.TryGetSha256(module.Path) is { } hash &&
                           rule.Sha256.Any(h => h.Equals(hash, StringComparison.OrdinalIgnoreCase)));
            if (matches)
            {
                return new Finding(FindingCodes.BlockedModule, rule.Severity,
                    $"Game đang nạp DLL bị cấm: {module.Name}",
                    rule.Reason is null ? module.Path : $"{rule.Reason} — {module.Path}");
            }
        }

        var hit = suspicious.FirstOrDefault(s => module.Path.Contains(s, StringComparison.OrdinalIgnoreCase));
        return hit is null
            ? null
            : new Finding(FindingCodes.SuspiciousModule, suspiciousSeverity,
                $"Game đang nạp DLL từ thư mục đáng ngờ: {module.Name}", module.Path);
    }
}
