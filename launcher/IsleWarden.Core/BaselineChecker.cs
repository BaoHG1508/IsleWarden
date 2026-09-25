namespace IsleWarden.Core;

/// <summary>
/// Compares the game files with the baseline for the installed build: missing, modified and unexpected
/// files (e.g. an extra .pak or .dll). Large files are hashed across several scans and cached, so later
/// scans cost almost nothing.
/// </summary>
public sealed class BaselineChecker
{
    private readonly FileHashCache _hashes;

    public BaselineChecker() : this(new FileHashCache())
    {
    }

    public BaselineChecker(FileHashCache hashes) => _hashes = hashes;

    public IEnumerable<Finding> Scan(Policy policy, ScanContext context)
    {
        var rule = policy.Baseline;
        if (rule is null || context.GameDirectory is null)
            yield break; // No game directory: Scanner already reports game-not-found.

        var baseline = context.Baseline;
        if (baseline is null)
        {
            yield return new Finding(FindingCodes.BaselineUnavailable, Severity.Info,
                "Chưa có baseline cho bản game này — bỏ qua so sánh file game.",
                context.GameBuildId is null ? null : $"build={context.GameBuildId}");
            yield break;
        }

        if (baseline.BuildId is not null && context.GameBuildId is not null &&
            !baseline.BuildId.Equals(context.GameBuildId, StringComparison.OrdinalIgnoreCase))
        {
            yield return new Finding(FindingCodes.BaselineOutdated, Severity.Info,
                "Baseline không khớp bản game đang cài — bỏ qua so sánh file game.",
                $"baseline={baseline.BuildId}; game={context.GameBuildId}");
            yield break;
        }

        var budget = Math.Max(1, rule.MaxHashMegabytesPerScan) * 1024L * 1024L;
        var hashedAny = false;
        var pending = 0;
        var expected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Small files (exe, dll) first, so the important ones are always checked on the first scan.
        foreach (var file in baseline.Files.OrderBy(f => f.Size))
        {
            var relative = BaselineBuilder.NormalizeRelative(file.Path);
            expected.Add(relative);
            var full = Path.Combine(context.GameDirectory, relative);

            var info = new FileInfo(full);
            if (!info.Exists)
            {
                yield return new Finding(FindingCodes.FileMissing, Severity.Medium, $"Thiếu file game: {relative}");
                continue;
            }

            if (info.Length != file.Size)
            {
                yield return Tampered(rule, relative, $"size={info.Length}; expected={file.Size}");
                continue;
            }

            if (!_hashes.TryGetCached(full, out var hash))
            {
                // Always hash at least one file per scan, so files larger than the budget still get checked.
                if (hashedAny && budget < file.Size)
                {
                    pending++;
                    continue;
                }

                hash = _hashes.TryGetSha256(full);
                budget -= file.Size;
                hashedAny = true;
            }

            if (hash is null)
            {
                yield return new Finding(FindingCodes.FileUnreadable, Severity.Low, $"Không đọc được file game: {relative}");
            }
            else if (!hash.Equals(file.Sha256, StringComparison.OrdinalIgnoreCase))
            {
                yield return Tampered(rule, relative, $"sha256={hash}");
            }
        }

        if (pending > 0)
        {
            yield return new Finding(FindingCodes.BaselinePending, Severity.Info,
                $"Còn {pending} file game lớn sẽ được kiểm tra ở các lần quét sau.");
        }

        if (!rule.ReportUnexpectedFiles)
            yield break;

        foreach (var (_, relative) in BaselineBuilder.EnumerateMatching(context.GameDirectory, baseline.Include, baseline.Exclude))
        {
            if (!expected.Contains(relative))
            {
                yield return new Finding(FindingCodes.UnexpectedFile, Severity.Medium,
                    $"File lạ trong thư mục game: {relative}");
            }
        }
    }

    private static Finding Tampered(BaselineRule rule, string relative, string detail) =>
        new(FindingCodes.FileTampered, rule.Severity, $"File game bị thay đổi: {relative}", detail);
}
