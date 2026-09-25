using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class BaselineTests
{
    [Fact]
    public void BuilderCapturesMatchingFilesAndExcludes()
    {
        using var dir = new TempDir();
        dir.Write("TheIsle.exe", "exe-data");
        dir.Write("Engine/lib.dll", "dll-data");
        dir.Write("readme.txt", "bo qua"); // matches no pattern
        dir.Write("EasyAntiCheat/eac.dll", "eac"); // excluded directory

        var baseline = BaselineBuilder.Create(dir.Path, ["*.exe", "*.dll"], ["EasyAntiCheat"], buildId: "b1");

        Assert.Equal(2, baseline.Files.Count);
        Assert.Contains(baseline.Files, f => f.Path.EndsWith("TheIsle.exe"));
        Assert.Contains(baseline.Files, f => f.Path.EndsWith("lib.dll"));
        Assert.DoesNotContain(baseline.Files, f => f.Path.Contains("EasyAntiCheat"));
        Assert.DoesNotContain(baseline.Files, f => f.Path.EndsWith("readme.txt"));
    }

    [Fact]
    public void CheckerCleanWhenFilesUnchanged()
    {
        using var dir = new TempDir();
        dir.Write("TheIsle.exe", "exe-data");
        var baseline = BaselineBuilder.Create(dir.Path, ["*.exe"], [], buildId: "b1");
        var context = Context(dir.Path, "b1", baseline);

        Assert.Empty(new BaselineChecker().Scan(PolicyWithBaseline(), context));
    }

    [Fact]
    public void CheckerReportsTamperedAndMissingAndUnexpected()
    {
        using var dir = new TempDir();
        dir.Write("TheIsle.exe", "exe-goc");
        dir.Write("keep.dll", "dll-goc");
        var baseline = BaselineBuilder.Create(dir.Path, ["*.exe", "*.dll"], [], buildId: "b1");

        // After the baseline: tamper with the exe, delete the dll, add an unexpected file.
        dir.Write("TheIsle.exe", "exe-da-sua");
        File.Delete(Path.Combine(dir.Path, "keep.dll"));
        dir.Write("injected.dll", "la");

        var findings = new BaselineChecker().Scan(PolicyWithBaseline(), Context(dir.Path, "b1", baseline)).ToList();

        Assert.Contains(findings, f => f.Code == FindingCodes.FileTampered && f.Message.Contains("TheIsle.exe"));
        Assert.Contains(findings, f => f.Code == FindingCodes.FileMissing && f.Message.Contains("keep.dll"));
        Assert.Contains(findings, f => f.Code == FindingCodes.UnexpectedFile && f.Message.Contains("injected.dll"));
    }

    [Fact]
    public void CheckerSkipsWhenBuildIdMismatch()
    {
        using var dir = new TempDir();
        dir.Write("TheIsle.exe", "exe");
        var baseline = BaselineBuilder.Create(dir.Path, ["*.exe"], [], buildId: "OLD");
        var context = Context(dir.Path, "NEW", baseline);

        var finding = Assert.Single(new BaselineChecker().Scan(PolicyWithBaseline(), context));
        Assert.Equal(FindingCodes.BaselineOutdated, finding.Code);
        Assert.Equal(Severity.Info, finding.Severity); // informational; the report stays clean
    }

    [Fact]
    public void JsonRoundTrips()
    {
        using var dir = new TempDir();
        dir.Write("TheIsle.exe", "exe");
        var baseline = BaselineBuilder.Create(dir.Path, ["*.exe"], [], buildId: "b1");
        var file = Path.Combine(dir.Path, "baseline.json");

        IsleWardenJson.SaveBaseline(baseline, file);
        var loaded = IsleWardenJson.LoadBaseline(file);

        Assert.Equal(baseline.BuildId, loaded.BuildId);
        Assert.Equal(baseline.Files.Count, loaded.Files.Count);
        Assert.Equal(baseline.Files[0].Sha256, loaded.Files[0].Sha256);
    }

    private static Policy PolicyWithBaseline() => new() { Baseline = new BaselineRule() };

    private static ScanContext Context(string gameDir, string buildId, Baseline baseline) =>
        new() { GameDirectory = gameDir, GameBuildId = buildId, Baseline = baseline };
}
