using Xunit;

namespace IsleWarden.Core.Tests;

public class PrefetchReaderTests
{
    private static readonly DateTimeOffset FileTime = new(2026, 9, 20, 8, 30, 0, TimeSpan.Zero);

    [Theory]
    [InlineData(17u)]
    [InlineData(23u)]
    [InlineData(26u)]
    [InlineData(30u)]
    public void ReadsNameRunCountAndLastRunForKnownVersions(uint version)
    {
        var lastRun = new DateTimeOffset(2026, 9, 25, 14, 5, 0, TimeSpan.Zero);
        var entry = PrefetchReader.Parse(
            PrefetchFixture.Scca("ISLEUNLOCKER.EXE", version, lastRun, runCount: 12), FileTime);

        Assert.NotNull(entry);
        Assert.Equal("ISLEUNLOCKER.EXE", entry.ExecutableName);
        Assert.Equal(12, entry.RunCount);
        Assert.Equal(lastRun, entry.LastRunUtc);
        Assert.Equal(version, entry.FormatVersion);
    }

    [Fact]
    public void ReadsCompressedPrefetchAsWindowsWritesIt()
    {
        if (!OperatingSystem.IsWindows())
            return; // MAM (de)compression is only available through ntdll.

        var raw = PrefetchFixture.Scca("CHEATENGINE-X86_64.EXE", runCount: 4);
        var entry = PrefetchReader.Parse(PrefetchFixture.Mam(raw), FileTime);

        Assert.NotNull(entry);
        Assert.Equal("CHEATENGINE-X86_64.EXE", entry.ExecutableName);
        Assert.Equal(4, entry.RunCount);
    }

    [Fact]
    public void UnknownVersionStillGivesNameButNoGuessedNumbers()
    {
        // Unknown version: no guessed offsets; last run falls back to the file time, run count is omitted.
        var entry = PrefetchReader.Parse(PrefetchFixture.Scca("ISLEUNLOCKER.EXE", version: 99), FileTime);

        Assert.NotNull(entry);
        Assert.Equal("ISLEUNLOCKER.EXE", entry.ExecutableName);
        Assert.Null(entry.RunCount);
        Assert.Equal(FileTime, entry.LastRunUtc);
    }

    [Fact]
    public void ImplausibleTimestampFallsBackToFileTime()
    {
        var entry = PrefetchReader.Parse(
            PrefetchFixture.Scca("ISLEUNLOCKER.EXE", lastRun: new DateTimeOffset(1999, 1, 1, 0, 0, 0, TimeSpan.Zero)),
            FileTime);

        Assert.NotNull(entry);
        Assert.Equal(FileTime, entry.LastRunUtc);
    }

    [Theory]
    [InlineData("khong phai prefetch")]
    [InlineData("MAM\u0004 rac sau vo MAM")]
    public void RejectsContentThatIsNotPrefetch(string content)
    {
        Assert.Null(PrefetchReader.Parse(System.Text.Encoding.UTF8.GetBytes(content), FileTime));
    }

    [Fact]
    public void RejectsEmptyContent()
    {
        Assert.Null(PrefetchReader.Parse([], FileTime));
    }

    [Theory]
    [InlineData("ISLEUNLOCKER.EXE-1A2B3C4D.pf", "ISLEUNLOCKER.EXE")]
    [InlineData("CHEATENGINE-X86_64.EXE-DEADBEEF.pf", "CHEATENGINE-X86_64.EXE")]
    [InlineData("NTOSBOOT-B00DFAAD.pf", "NTOSBOOT")]
    [InlineData("khong-co-hash.pf", null)]
    [InlineData("khongcodauganh.pf", null)]
    public void ParsesExecutableNameFromPrefetchFileName(string fileName, string? expected)
    {
        Assert.Equal(expected, ExecutionHistoryScanner.ExecutableNameOf(fileName));
    }
}
