using System.IO.Enumeration;

namespace IsleWarden.Core;

/// <summary>Reference hashes of the game files for one specific game build.</summary>
public sealed record Baseline
{
    public int Version { get; init; } = 1;
    public string? AppId { get; init; }
    public string? BuildId { get; init; }
    public DateTimeOffset CreatedUtc { get; init; }

    /// <summary>File name patterns to include, e.g. <c>*.exe</c>.</summary>
    public List<string> Include { get; init; } = new();

    /// <summary>Subdirectories to exclude, relative to the game directory, e.g. <c>EasyAntiCheat</c>.</summary>
    public List<string> Exclude { get; init; } = new();

    public List<BaselineFile> Files { get; init; } = new();
}

/// <param name="Path">Path relative to the game directory.</param>
public sealed record BaselineFile(string Path, long Size, string Sha256);

/// <summary>Builds a baseline from a clean game install; the admin must rebuild it after every game update.</summary>
public static class BaselineBuilder
{
    public static IReadOnlyList<string> DefaultInclude { get; } = ["*.exe", "*.dll", "*.pak", "*.utoc", "*.ucas", "*.sig"];

    /// <summary>EasyAntiCheat manages and updates its own folder, so it is left out of the baseline.</summary>
    public static IReadOnlyList<string> DefaultExclude { get; } = ["EasyAntiCheat"];

    public static Baseline Create(
        string gameDirectory,
        IReadOnlyList<string>? include = null,
        IReadOnlyList<string>? exclude = null,
        string? appId = null,
        string? buildId = null,
        Action<string>? progress = null)
    {
        include ??= DefaultInclude;
        exclude ??= DefaultExclude;

        var files = new List<BaselineFile>();
        var matches = EnumerateMatching(gameDirectory, include, exclude)
            .OrderBy(m => m.Relative, StringComparer.OrdinalIgnoreCase);

        foreach (var (full, relative) in matches)
        {
            progress?.Invoke(relative);
            var hash = FileHashCache.ComputeSha256(full)
                       ?? throw new IOException($"Không đọc được file: {full}");
            files.Add(new BaselineFile(relative, new FileInfo(full).Length, hash));
        }

        return new Baseline
        {
            AppId = appId,
            BuildId = buildId,
            CreatedUtc = DateTimeOffset.UtcNow,
            Include = include.ToList(),
            Exclude = exclude.ToList(),
            Files = files
        };
    }

    public static IEnumerable<(string Full, string Relative)> EnumerateMatching(
        string root, IReadOnlyList<string> include, IReadOnlyList<string> exclude)
    {
        var options = new EnumerationOptions
        {
            RecurseSubdirectories = true,
            IgnoreInaccessible = true,
            // Unlike the default, include hidden/system files; skip only reparse points to avoid cycles.
            AttributesToSkip = FileAttributes.ReparsePoint
        };
        var excluded = exclude.Select(NormalizeRelative).Where(e => e.Length > 0).ToList();

        foreach (var full in Directory.EnumerateFiles(root, "*", options))
        {
            var relative = NormalizeRelative(Path.GetRelativePath(root, full));
            if (excluded.Any(e => relative.Equals(e, StringComparison.OrdinalIgnoreCase) ||
                                  relative.StartsWith(e + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            var name = Path.GetFileName(full);
            if (include.Any(pattern => FileSystemName.MatchesSimpleExpression(pattern, name, ignoreCase: true)))
                yield return (full, relative);
        }
    }

    public static string NormalizeRelative(string path) =>
        path.Replace('/', Path.DirectorySeparatorChar)
            .Replace('\\', Path.DirectorySeparatorChar)
            .Trim(Path.DirectorySeparatorChar);
}
