using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class ScannerAndModelTests
{
    [Theory]
    [InlineData(Severity.Info, true)]
    [InlineData(Severity.Low, false)]
    [InlineData(Severity.High, false)]
    public void IsCleanTreatsInfoAsClean(Severity severity, bool expectedClean)
    {
        var findings = new[] { new Finding("x", severity, "msg") };
        Assert.Equal(expectedClean, ScanReport.IsClean(findings));
    }

    [Fact]
    public void EmptyFindingsIsClean() => Assert.True(ScanReport.IsClean([]));

    [Fact]
    public void StartupOrderFlagsGameStartedBeforeLauncher()
    {
        var agentStart = DateTimeOffset.UtcNow;
        var policy = new Policy { GameProcessName = "TheIsleClient-Win64-Shipping", StartupOrder = new StartupOrderRule() };
        var source = new FakeProcessSource().Add(1, "TheIsleClient-Win64-Shipping", started: agentStart.AddMinutes(-1));
        var context = new ScanContext { AgentStartedUtc = agentStart };

        var finding = Assert.Single(new StartupOrderChecker(source).Scan(policy, context));
        Assert.Equal(FindingCodes.GameStartedBeforeLauncher, finding.Code);
    }

    [Fact]
    public void StartupOrderAllowsGameStartedAfterLauncher()
    {
        var agentStart = DateTimeOffset.UtcNow;
        var policy = new Policy { GameProcessName = "TheIsle", StartupOrder = new StartupOrderRule() };
        var source = new FakeProcessSource().Add(1, "TheIsle", started: agentStart.AddSeconds(10));
        var context = new ScanContext { AgentStartedUtc = agentStart };

        Assert.Empty(new StartupOrderChecker(source).Scan(policy, context));
    }

    [Fact]
    public void ModuleScannerFlagsBlockedDll()
    {
        var policy = new Policy
        {
            GameProcessName = "TheIsle",
            ModuleScan = new ModuleScanRule { Enabled = true, BlockedModules = { new BlockedModule("hack.dll", "Cheat DLL") } }
        };
        var processes = new FakeProcessSource().Add(1, "TheIsle");
        var modules = new FakeModuleSource().AddModule(1, "hack.dll", @"C:\temp\hack.dll").AddModule(1, "ok.dll", @"C:\game\ok.dll");

        var finding = Assert.Single(new ModuleScanner(processes, modules, new FileHashCache()).Scan(policy));
        Assert.Equal(FindingCodes.BlockedModule, finding.Code);
    }

    [Fact]
    public void ModuleScannerFlagsSuspiciousPathAndReportsUnavailableAsInfo()
    {
        var policy = new Policy
        {
            GameProcessName = "TheIsle",
            ModuleScan = new ModuleScanRule { Enabled = true, SuspiciousPaths = { @"\Downloads\" } }
        };
        var processes = new FakeProcessSource().Add(1, "TheIsle").Add(2, "TheIsle");
        var modules = new FakeModuleSource()
            .AddModule(1, "x.dll", @"C:\Users\a\Downloads\x.dll")
            .Deny(2); // module access denied for process 2

        var findings = new ModuleScanner(processes, modules, new FileHashCache()).Scan(policy).ToList();

        Assert.Contains(findings, f => f.Code == FindingCodes.SuspiciousModule);
        var unavailable = Assert.Single(findings, f => f.Code == FindingCodes.ModuleScanUnavailable);
        Assert.Equal(Severity.Info, unavailable.Severity);
    }

    [Fact]
    public void ScannerCombinesModulesAndComputesClean()
    {
        var policy = new Policy { BlockedProcesses = { new BlockedProcess("cheatengine-x86_64") } };
        var processes = new FakeProcessSource().Add(1, "notepad");
        var report = new Scanner(processes, new FakeModuleSource(), new FileHashCache()).Run(policy, new ScanContext());

        Assert.True(report.Clean);
        Assert.Empty(report.Findings);
        Assert.Equal(Environment.MachineName, report.Machine);
    }
}
