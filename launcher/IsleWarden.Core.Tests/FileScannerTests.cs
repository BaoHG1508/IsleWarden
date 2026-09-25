using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class FileScannerTests
{
    [Fact]
    public void FindsKnownToolOnDisk()
    {
        using var dir = new TempDir();
        dir.Write("IsleUnlocker.exe", "tool");
        var findings = Scan(dir, [new BlockedFile("IsleUnlocker.exe", "Isle Unlocker")]);

        var finding = Assert.Single(findings);
        Assert.Equal(FindingCodes.BlockedFile, finding.Code);
        Assert.Contains("IsleUnlocker.exe", finding.Message);
        Assert.Equal(Severity.Medium, finding.Severity); // Medium by default: having the file doesn't mean it was used
    }

    [Fact]
    public void MatchesRegardlessOfCase()
    {
        using var dir = new TempDir();
        dir.Write("isleunlocker.EXE", "tool");
        Assert.Single(Scan(dir, [new BlockedFile("IsleUnlocker.exe")]));
    }

    [Fact]
    public void IgnoresEverythingNotOnTheList()
    {
        using var dir = new TempDir();
        dir.Write("bao-cao-thue.pdf", "rieng tu");
        dir.Write("anh-gia-dinh.jpg", "rieng tu");
        dir.Write("notepad.exe", "vo hai");

        // No findings, so the names of private files are never recorded.
        Assert.Empty(Scan(dir, [new BlockedFile("IsleUnlocker.exe")]));
    }

    [Fact]
    public void FindsToolInSubdirectoryWithinDepth()
    {
        using var dir = new TempDir();
        dir.Write(Path.Combine("tools", "cheat", "IsleUnlocker.exe"), "tool");
        Assert.Single(Scan(dir, [new BlockedFile("IsleUnlocker.exe")], depth: 2));
    }

    [Fact]
    public void DoesNotDescendBeyondMaxDepth()
    {
        using var dir = new TempDir();
        dir.Write(Path.Combine("a", "b", "c", "IsleUnlocker.exe"), "tool");
        Assert.Empty(Scan(dir, [new BlockedFile("IsleUnlocker.exe")], depth: 1));
    }

    [Fact]
    public void HashGatedRuleIgnoresUnrelatedFileWithSameName()
    {
        using var dir = new TempDir();
        dir.Write("IsleUnlocker.exe", "thuc ra la file vo hai trung ten");
        var rule = new BlockedFile("IsleUnlocker.exe", Sha256: ["DEADBEEF"]);
        Assert.Empty(Scan(dir, [rule]));
    }

    [Fact]
    public void HashGatedRuleFlagsWhenHashMatches()
    {
        using var dir = new TempDir();
        var path = dir.Write("IsleUnlocker.exe", "dung la tool");
        var hash = FileHashCache.ComputeSha256(path)!;
        Assert.Single(Scan(dir, [new BlockedFile("IsleUnlocker.exe", Sha256: [hash])]));
    }

    [Fact]
    public void DisabledRuleScansNothing()
    {
        using var dir = new TempDir();
        dir.Write("IsleUnlocker.exe", "tool");
        var policy = new Policy
        {
            FileScan = new FileScanRule
            {
                Enabled = false,
                Directories = { dir.Path },
                Files = { new BlockedFile("IsleUnlocker.exe") }
            }
        };
        Assert.Empty(new FileScanner().Scan(policy, new ScanContext()));
    }

    [Fact]
    public void ReportsEachFileOnceEvenWhenDirectoriesOverlap()
    {
        using var dir = new TempDir();
        dir.Write(Path.Combine("sub", "IsleUnlocker.exe"), "tool");
        var policy = new Policy
        {
            FileScan = new FileScanRule
            {
                Enabled = true,
                MaxDepth = 2,
                Directories = { dir.Path, Path.Combine(dir.Path, "sub") },
                Files = { new BlockedFile("IsleUnlocker.exe") }
            }
        };

        Assert.Single(new FileScanner().Scan(policy, new ScanContext()));
    }

    [Fact]
    public void ResolvesGameDirToken()
    {
        using var dir = new TempDir();
        var context = new ScanContext { GameDirectory = dir.Path };
        var resolved = FileScanner.ResolveDirectories(["{GameDir}"], context).ToList();
        Assert.Equal(Path.GetFullPath(dir.Path), Assert.Single(resolved));
    }

    [Fact]
    public void SkipsTokenThatCannotBeResolved()
    {
        // No game directory, so {GameDir} is skipped instead of throwing.
        var resolved = FileScanner.ResolveDirectories(["{GameDir}"], new ScanContext()).ToList();
        Assert.Empty(resolved);
    }

    private static List<Finding> Scan(TempDir dir, BlockedFile[] files, int depth = 2)
    {
        var policy = new Policy
        {
            FileScan = new FileScanRule { Enabled = true, MaxDepth = depth, Directories = { dir.Path } }
        };
        policy.FileScan!.Files.AddRange(files);
        return new FileScanner().Scan(policy, new ScanContext()).ToList();
    }
}
