using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class ProcessInventoryTests
{
    [Fact]
    public void DoesNothingWhenRuleAbsent()
    {
        var source = new FakeProcessSource().Add(1, "notepad");
        var result = new ProcessInventoryScanner(source).Collect(new Policy());

        Assert.Null(result.Names);
        Assert.Empty(result.Findings);
    }

    [Fact]
    public void ReportsProcessNamesWhenEnabled()
    {
        var source = new FakeProcessSource().Add(1, "notepad").Add(2, "TheIsle").Add(3, "chrome");
        var result = new ProcessInventoryScanner(source).Collect(
            Policy(new ProcessInventoryRule { ReportRunningProcesses = true }));

        Assert.NotNull(result.Names);
        Assert.Equal(["chrome", "notepad", "TheIsle"], result.Names!); // sorted case-insensitively
    }

    [Fact]
    public void DoesNotReportNamesWhenOnlyKeywordsEnabled()
    {
        var source = new FakeProcessSource().Add(1, "aimbot-pro");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            ReportRunningProcesses = false,
            Keywords = { new ProcessNameKeyword("aimbot") }
        }));

        Assert.Null(result.Names); // still flags without sending the list
        Assert.Single(result.Findings);
    }

    [Fact]
    public void FlagsNameContainingKeyword()
    {
        var source = new FakeProcessSource().Add(1, "SuperAimbotV2").Add(2, "notepad");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            Keywords = { new ProcessNameKeyword("aimbot", "Aimbot") }
        }));

        var finding = Assert.Single(result.Findings);
        Assert.Equal(FindingCodes.SuspiciousProcessName, finding.Code);
        Assert.Contains("SuperAimbotV2", finding.Message);
        Assert.Equal(Severity.Low, finding.Severity); // heuristic; not enough for an automatic ban
    }

    [Fact]
    public void KeywordMatchIsCaseInsensitive()
    {
        var source = new FakeProcessSource().Add(1, "ISLEUNLOCKER");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            Keywords = { new ProcessNameKeyword("unlocker") }
        }));

        Assert.Single(result.Findings);
    }

    [Fact]
    public void AllowListSuppressesKnownFalsePositive()
    {
        var source = new FakeProcessSource().Add(1, "esptool").Add(2, "cheatengine-x86_64");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            Keywords = { new ProcessNameKeyword("esptool"), new ProcessNameKeyword("cheat") },
            Allow = { "esptool" }
        }));

        var finding = Assert.Single(result.Findings);
        Assert.Contains("cheatengine", finding.Message);
    }

    [Fact]
    public void IgnoresKeywordShorterThanMinimum()
    {
        // "esp" would falsely match "respondus", so MinKeywordLength filters it out.
        var source = new FakeProcessSource().Add(1, "respondus");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            Keywords = { new ProcessNameKeyword("esp") },
            MinKeywordLength = 4
        }));

        Assert.Empty(result.Findings);
    }

    [Fact]
    public void ReportsDuplicateProcessNameOnlyOnce()
    {
        var source = new FakeProcessSource().Add(1, "injector").Add(2, "injector").Add(3, "injector");
        var result = new ProcessInventoryScanner(source).Collect(Policy(new ProcessInventoryRule
        {
            ReportRunningProcesses = true,
            Keywords = { new ProcessNameKeyword("inject") }
        }));

        Assert.Single(result.Findings);
        Assert.Single(result.Names!);
    }

    [Fact]
    public void ScannerAttachesProcessListToReport()
    {
        var policy = Policy(new ProcessInventoryRule { ReportRunningProcesses = true });
        var source = new FakeProcessSource().Add(1, "notepad");
        var report = new Scanner(source, new FakeModuleSource(), new FileHashCache()).Run(policy, new ScanContext());

        Assert.Equal(["notepad"], report.Processes!);
        Assert.True(report.Clean);
    }

    [Fact]
    public void KeywordFindingAtLowSeverityDoesNotBreakCleanAtHighThreshold()
    {
        // The report is no longer clean (it has a Low finding), but Low is below the default
        // block threshold (High), so the server won't reject it automatically.
        var source = new FakeProcessSource().Add(1, "GameTrainer");
        var policy = Policy(new ProcessInventoryRule { Keywords = { new ProcessNameKeyword("trainer") } });
        var report = new Scanner(source, new FakeModuleSource(), new FileHashCache()).Run(policy, new ScanContext());

        var finding = Assert.Single(report.Findings);
        Assert.Equal(Severity.Low, finding.Severity);
        Assert.DoesNotContain(report.Findings, f => f.Severity >= Severity.High);
    }

    private static Policy Policy(ProcessInventoryRule rule) => new() { ProcessInventory = rule };
}
