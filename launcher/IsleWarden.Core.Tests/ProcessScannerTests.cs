using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class ProcessScannerTests
{
    [Fact]
    public void FlagsBlockedProcessByName()
    {
        var policy = new Policy { BlockedProcesses = { new BlockedProcess("cheatengine-x86_64", "Cheat Engine") } };
        var source = new FakeProcessSource().Add(100, "cheatengine-x86_64").Add(200, "notepad");

        var findings = new ProcessScanner(source, new FileHashCache()).Scan(policy).ToList();

        var finding = Assert.Single(findings);
        Assert.Equal(FindingCodes.BlockedProcess, finding.Code);
        Assert.Contains("100", finding.Message);
    }

    [Theory]
    [InlineData("CheatEngine-x86_64")] // different case
    [InlineData("cheatengine-x86_64.exe")] // .exe suffix
    public void MatchesRegardlessOfCaseAndExeSuffix(string runningName)
    {
        var policy = new Policy { BlockedProcesses = { new BlockedProcess("cheatengine-x86_64") } };
        var source = new FakeProcessSource().Add(1, runningName);

        Assert.Single(new ProcessScanner(source, new FileHashCache()).Scan(policy));
    }

    [Fact]
    public void HashGatedRuleIgnoresProcessWhenHashDiffers()
    {
        var file = TempFile.Create("noi dung khong khop");
        var policy = new Policy { BlockedProcesses = { new BlockedProcess("tool", Sha256: ["DEADBEEF"]) } };
        var source = new FakeProcessSource().Add(1, "tool", file.Path);

        Assert.Empty(new ProcessScanner(source, new FileHashCache()).Scan(policy));
    }

    [Fact]
    public void HashGatedRuleFlagsProcessWhenHashMatches()
    {
        var file = TempFile.Create("noi dung cheat");
        var hash = FileHashCache.ComputeSha256(file.Path)!;
        var policy = new Policy { BlockedProcesses = { new BlockedProcess("tool", Sha256: [hash]) } };
        var source = new FakeProcessSource().Add(1, "tool", file.Path);

        Assert.Single(new ProcessScanner(source, new FileHashCache()).Scan(policy));
    }

    [Fact]
    public void NoBlockedProcessesYieldsNothing()
    {
        var source = new FakeProcessSource().Add(1, "cheatengine-x86_64");
        Assert.Empty(new ProcessScanner(source, new FileHashCache()).Scan(new Policy()));
    }
}
