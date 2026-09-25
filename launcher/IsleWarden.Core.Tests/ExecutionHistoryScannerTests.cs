using Xunit;

namespace IsleWarden.Core.Tests;

public class ExecutionHistoryScannerTests
{
    [Fact]
    public void FindsToolThatAlreadyStopped()
    {
        using var dir = new TempDir();
        dir.WriteBytes("ISLEUNLOCKER.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE", runCount: 7));

        var finding = Assert.Single(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe", "Isle Unlocker")]));
        Assert.Equal(FindingCodes.ExecutedTool, finding.Code);
        Assert.Contains("ISLEUNLOCKER.EXE", finding.Message);
        Assert.Contains("7 lần", finding.Detail);
        Assert.Equal(Severity.Medium, finding.Severity); // ran at some point, not necessarily alongside the game
    }

    [Fact]
    public void IgnoresEverythingNotOnTheList()
    {
        using var dir = new TempDir();
        dir.WriteBytes("WINWORD.EXE-11223344.pf", PrefetchFixture.Scca("WINWORD.EXE"));
        dir.WriteBytes("CHROME.EXE-AABBCCDD.pf", PrefetchFixture.Scca("CHROME.EXE"));
        dir.WriteBytes("ZALO.EXE-99887766.pf", PrefetchFixture.Scca("ZALO.EXE"));

        // No findings, so private execution history is never recorded.
        Assert.Empty(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe")]));
    }

    [Fact]
    public void MatchesRegardlessOfCaseAndExtension()
    {
        using var dir = new TempDir();
        dir.WriteBytes("CHEATENGINE-X86_64.EXE-DEADBEEF.pf", PrefetchFixture.Scca("CHEATENGINE-X86_64.EXE"));

        Assert.Single(Scan(dir, [new ExecutedProgram("cheatengine-x86_64")]));
    }

    [Fact]
    public void IgnoresRunsOlderThanLookbackWindow()
    {
        using var dir = new TempDir();
        var old = DateTimeOffset.UtcNow.AddDays(-30);
        var path = dir.WriteBytes("ISLEUNLOCKER.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE", lastRun: old));
        File.SetLastWriteTimeUtc(path, old.UtcDateTime);

        Assert.Empty(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe")], lookbackDays: 7));
    }

    [Fact]
    public void AllowListSuppressesKnownFalsePositive()
    {
        using var dir = new TempDir();
        dir.WriteBytes("TRAINERROAD.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("TRAINERROAD.EXE"));

        var rule = Rule(dir);
        rule.Keywords.Add(new ProcessNameKeyword("trainer", "Trainer game"));
        rule.Allow.Add("TrainerRoad.exe");

        Assert.Empty(new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }));
    }

    [Fact]
    public void KeywordMatchIsReportedSeparatelyAtItsOwnSeverity()
    {
        using var dir = new TempDir();
        dir.WriteBytes("SOMEINJECTOR.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("SOMEINJECTOR.EXE"));

        var rule = Rule(dir);
        rule.Keywords.Add(new ProcessNameKeyword("injector", "Công cụ tiêm DLL"));

        var finding = Assert.Single(new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }));
        Assert.Equal(FindingCodes.SuspiciousExecutedName, finding.Code);
        Assert.Equal(Severity.Low, finding.Severity); // heuristic; not enough to block automatically
    }

    [Fact]
    public void ShortKeywordIsIgnored()
    {
        using var dir = new TempDir();
        dir.WriteBytes("ESPTOOL.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("ESPTOOL.EXE"));

        var rule = Rule(dir);
        rule.Keywords.Add(new ProcessNameKeyword("esp"));

        Assert.Empty(new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }));
    }

    [Fact]
    public void DisabledRuleReadsNothing()
    {
        using var dir = new TempDir();
        dir.WriteBytes("ISLEUNLOCKER.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE"));

        var rule = Rule(dir) with { Enabled = false };
        rule.Programs.Add(new ExecutedProgram("IsleUnlocker.exe"));

        Assert.Empty(new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }));
    }

    [Fact]
    public void MissingDirectoryIsReportedAtInfoAndKeepsReportClean()
    {
        var rule = new ExecutionHistoryRule
        {
            Enabled = true,
            ReportPrefetchDisabled = false,
            Directory = Path.Combine(Path.GetTempPath(), "iw-khong-ton-tai-" + Guid.NewGuid().ToString("N")),
            Programs = { new ExecutedProgram("IsleUnlocker.exe") }
        };

        var findings = new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }).ToList();
        var finding = Assert.Single(findings);
        Assert.Equal(FindingCodes.ExecutionHistoryUnavailable, finding.Code);
        Assert.Equal(Severity.Info, finding.Severity);
        Assert.True(ScanReport.IsClean(findings)); // unreadable history isn't a violation
    }

    [Fact]
    public void ReportsOneFindingPerProgramEvenWithSeveralPrefetchEntries()
    {
        using var dir = new TempDir();
        // The same tool run from two directories leaves two .pf files with different hashes.
        dir.WriteBytes("ISLEUNLOCKER.EXE-1A2B3C4D.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE"));
        dir.WriteBytes("ISLEUNLOCKER.EXE-99887766.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE"));

        Assert.Single(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe")]));
    }

    [Fact]
    public void IgnoresFilesThatAreNotPrefetchEntries()
    {
        using var dir = new TempDir();
        dir.WriteBytes("IsleUnlocker.exe.pf", PrefetchFixture.Scca("ISLEUNLOCKER.EXE")); // no hash suffix
        Assert.Empty(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe")]));
    }

    [Fact]
    public void FallsBackToFileTimeWhenContentIsUnreadable()
    {
        using var dir = new TempDir();
        dir.Write("ISLEUNLOCKER.EXE-1A2B3C4D.pf", "khong phai dinh dang prefetch");

        // The file name alone is evidence; corrupt content only loses the run count.
        var finding = Assert.Single(Scan(dir, [new ExecutedProgram("IsleUnlocker.exe")]));
        Assert.Contains("lần chạy gần nhất", finding.Detail);
        Assert.DoesNotContain(" lần —", finding.Detail);
    }

    private static List<Finding> Scan(TempDir dir, ExecutedProgram[] programs, int lookbackDays = 7)
    {
        var rule = Rule(dir, lookbackDays);
        rule.Programs.AddRange(programs);
        return new ExecutionHistoryScanner().Scan(new Policy { ExecutionHistory = rule }).ToList();
    }

    /// <summary>ReportPrefetchDisabled is off so results don't depend on the test machine's Prefetch settings.</summary>
    private static ExecutionHistoryRule Rule(TempDir dir, int lookbackDays = 7) => new()
    {
        Enabled = true,
        ReportPrefetchDisabled = false,
        Directory = dir.Path,
        LookbackDays = lookbackDays
    };
}
