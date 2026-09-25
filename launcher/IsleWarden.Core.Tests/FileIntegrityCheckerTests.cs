using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class FileIntegrityCheckerTests
{
    [Fact]
    public void ReportsMissingFile()
    {
        var policy = new Policy { ProtectedFiles = { new ProtectedFile(@"Z:\khong-ton-tai\game.exe") } };
        var finding = Assert.Single(new FileIntegrityChecker().Scan(policy));
        Assert.Equal(FindingCodes.FileMissing, finding.Code);
    }

    [Fact]
    public void CleanWhenHashMatches()
    {
        using var file = TempFile.Create("noi dung game hop le");
        var hash = FileHashCache.ComputeSha256(file.Path)!;
        var policy = new Policy { ProtectedFiles = { new ProtectedFile(file.Path, Sha256: [hash]) } };

        Assert.Empty(new FileIntegrityChecker().Scan(policy));
    }

    [Fact]
    public void ReportsTamperedWhenHashDiffers()
    {
        using var file = TempFile.Create("da bi sua");
        var policy = new Policy { ProtectedFiles = { new ProtectedFile(file.Path, Sha256: ["0000"]) } };

        var finding = Assert.Single(new FileIntegrityChecker().Scan(policy));
        Assert.Equal(FindingCodes.FileTampered, finding.Code);
        Assert.Equal(Severity.High, finding.Severity);
    }

    [Fact]
    public void AcceptsAnyOfMultipleAllowedHashes()
    {
        using var file = TempFile.Create("phien ban 2");
        var hash = FileHashCache.ComputeSha256(file.Path)!;
        var policy = new Policy { ProtectedFiles = { new ProtectedFile(file.Path, Sha256: ["1111", hash, "2222"]) } };

        Assert.Empty(new FileIntegrityChecker().Scan(policy));
    }

    [Fact]
    public void ResolvesGameDirToken()
    {
        using var dir = new TempDir();
        var full = dir.Write("TheIsle.exe", "exe");
        var hash = FileHashCache.ComputeSha256(full)!;
        var policy = new Policy { ProtectedFiles = { new ProtectedFile(@"{GameDir}\TheIsle.exe", Sha256: [hash]) } };
        var context = new ScanContext { GameDirectory = dir.Path };

        Assert.Empty(new FileIntegrityChecker().Scan(policy, context));
    }
}
