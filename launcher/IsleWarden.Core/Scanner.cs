namespace IsleWarden.Core;

/// <summary>Runs all detectors as a single scan and returns the report.</summary>
public sealed class Scanner
{
    private readonly ProcessScanner _processScanner;
    private readonly FileIntegrityChecker _fileChecker;
    private readonly StartupOrderChecker _startupOrder;
    private readonly ModuleScanner _moduleScanner;
    private readonly BaselineChecker _baselineChecker;
    private readonly FileScanner _fileScanner;
    private readonly ProcessInventoryScanner _inventory;
    private readonly ExecutionHistoryScanner _executionHistory;

    public Scanner() : this(new SystemProcessSource(), new SystemModuleSource(), new FileHashCache())
    {
    }

    public Scanner(IProcessSource processes, IModuleSource modules, FileHashCache hashes)
    {
        _processScanner = new ProcessScanner(processes, hashes);
        _fileChecker = new FileIntegrityChecker(hashes);
        _startupOrder = new StartupOrderChecker(processes);
        _moduleScanner = new ModuleScanner(processes, modules, hashes);
        _baselineChecker = new BaselineChecker(hashes);
        _fileScanner = new FileScanner(hashes);
        _inventory = new ProcessInventoryScanner(processes);
        _executionHistory = new ExecutionHistoryScanner();
    }

    public ScanReport Run(Policy policy) => Run(policy, ScanContext.Resolve(policy, DateTimeOffset.UtcNow));

    public ScanReport Run(Policy policy, ScanContext context)
    {
        var findings = new List<Finding>();

        if (context.GameDirectory is null && NeedsGameDirectory(policy))
        {
            findings.Add(new Finding(FindingCodes.GameNotFound, Severity.Medium,
                "Không xác định được thư mục cài game.",
                policy.SteamAppId is null ? null : $"steamAppId={policy.SteamAppId}"));
        }

        findings.AddRange(_processScanner.Scan(policy));
        findings.AddRange(_fileChecker.Scan(policy, context));
        findings.AddRange(_startupOrder.Scan(policy, context));
        findings.AddRange(_moduleScanner.Scan(policy));
        findings.AddRange(_baselineChecker.Scan(policy, context));
        findings.AddRange(_fileScanner.Scan(policy, context));
        findings.AddRange(_executionHistory.Scan(policy));

        var inventory = _inventory.Collect(policy);
        findings.AddRange(inventory.Findings);

        return new ScanReport(
            DateTimeOffset.UtcNow,
            Environment.MachineName,
            ScanReport.IsClean(findings),
            findings)
        {
            Processes = inventory.Names
        };
    }

    private static bool NeedsGameDirectory(Policy policy) =>
        policy.Baseline is not null ||
        policy.ProtectedFiles.Any(f => PathTemplate.UsesGameDirectory(f.Path));
}
