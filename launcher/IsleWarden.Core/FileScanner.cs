using System.Diagnostics;

namespace IsleWarden.Core;

/// <summary>
/// Finds files of known cheat tools on disk even when they are not running, catching players who close
/// a tool before opening the launcher.
/// </summary>
/// <remarks>
/// Privacy boundary (intentional; do not loosen): only file names are compared with the policy list.
/// File contents are never read, except that a name-matched file is hashed when its rule lists SHA-256
/// hashes, and names of non-matching files are never recorded or sent. Depth, file count and time are
/// capped, so the scan never crawls a whole drive.
/// </remarks>
public sealed class FileScanner
{
    private readonly FileHashCache _hashes;

    public FileScanner() : this(new FileHashCache())
    {
    }

    public FileScanner(FileHashCache hashes) => _hashes = hashes;

    public IEnumerable<Finding> Scan(Policy policy, ScanContext context)
    {
        var rule = policy.FileScan;
        if (rule is not { Enabled: true } || rule.Files.Count == 0 || rule.Directories.Count == 0)
            yield break;

        var wanted = rule.Files
            .GroupBy(f => f.Name.Trim(), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First(), StringComparer.OrdinalIgnoreCase);

        var budget = new Budget(rule);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var directory in ResolveDirectories(rule.Directories, context))
        {
            if (budget.Exhausted)
                break;

            foreach (var (path, matched) in FindIn(directory, wanted, rule, budget))
            {
                // The same file can be reached through two nested directories; report it once.
                if (seen.Add(path) && Verify(matched, path))
                {
                    yield return new Finding(
                        FindingCodes.BlockedFile,
                        matched.Severity,
                        $"Tìm thấy công cụ gian lận trên máy: {matched.Name}",
                        matched.Reason is null ? path : $"{matched.Reason} — {path}");
                }
            }
        }
    }

    private bool Verify(BlockedFile rule, string path)
    {
        if (rule.Sha256 is not { Length: > 0 })
            return true;

        // Only a file whose name already matched is ever hashed.
        var hash = _hashes.TryGetSha256(path);
        return hash is not null && rule.Sha256.Any(h => h.Equals(hash, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Limits shared by the whole scan: elapsed time and number of files examined.</summary>
    private sealed class Budget(FileScanRule rule)
    {
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private readonly TimeSpan _timeout = TimeSpan.FromSeconds(Math.Max(1, rule.TimeoutSeconds));
        private readonly int _maxFiles = Math.Max(1, rule.MaxFilesExamined);

        public int Examined { get; private set; }

        public bool Exhausted => Examined >= _maxFiles || _clock.Elapsed > _timeout;

        /// <summary>Counts one more file; returns false once the budget is exhausted.</summary>
        public bool Count()
        {
            Examined++;
            return !Exhausted;
        }
    }

    private static List<(string Path, BlockedFile Rule)> FindIn(
        string root, Dictionary<string, BlockedFile> wanted, FileScanRule rule, Budget budget)
    {
        var results = new List<(string, BlockedFile)>();
        var queue = new Queue<(string Dir, int Depth)>();
        queue.Enqueue((root, 0));

        while (queue.Count > 0 && !budget.Exhausted)
        {
            var (dir, depth) = queue.Dequeue();

            string[] files;
            try
            {
                files = Directory.GetFiles(dir);
            }
            catch
            {
                continue; // Access denied, or the directory was just deleted.
            }

            foreach (var file in files)
            {
                // Keep only listed files; every other file is dropped here and never recorded.
                if (wanted.TryGetValue(Path.GetFileName(file), out var matched))
                    results.Add((file, matched));

                if (!budget.Count())
                    return results;
            }

            if (depth >= rule.MaxDepth)
                continue;

            try
            {
                foreach (var sub in Directory.GetDirectories(dir))
                {
                    // Don't follow symlinks/junctions: they can cause loops or lead outside the scanned tree.
                    if ((File.GetAttributes(sub) & FileAttributes.ReparsePoint) == 0)
                        queue.Enqueue((sub, depth + 1));
                }
            }
            catch
            {
                // Subdirectories can't be listed; skip this branch.
            }
        }

        return results;
    }

    /// <summary>Expands folder tokens ({Downloads}, {GameDir}, ...) and environment variables.</summary>
    internal static IEnumerable<string> ResolveDirectories(IEnumerable<string> patterns, ScanContext context)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var pattern in patterns)
        {
            var resolved = ResolveTokens(pattern, context);
            if (resolved is null)
                continue;

            string full;
            try
            {
                full = Path.GetFullPath(Environment.ExpandEnvironmentVariables(resolved));
            }
            catch
            {
                continue;
            }

            if (seen.Add(full) && Directory.Exists(full))
                yield return full;
        }
    }

    private static string? ResolveTokens(string pattern, ScanContext context)
    {
        if (!pattern.Contains('{'))
            return pattern;

        foreach (var (token, value) in WellKnown(context))
        {
            if (!pattern.Contains(token, StringComparison.OrdinalIgnoreCase))
                continue;
            if (string.IsNullOrEmpty(value))
                return null; // This token can't be resolved on this machine.
            pattern = pattern.Replace(token, value, StringComparison.OrdinalIgnoreCase);
        }

        return pattern;
    }

    private static IEnumerable<(string Token, string? Value)> WellKnown(ScanContext context)
    {
        yield return ("{GameDir}", context.GameDirectory);
        yield return ("{Desktop}", Folder(Environment.SpecialFolder.DesktopDirectory));
        yield return ("{Documents}", Folder(Environment.SpecialFolder.MyDocuments));
        yield return ("{ProgramFiles}", Folder(Environment.SpecialFolder.ProgramFiles));
        yield return ("{ProgramFilesX86}", Folder(Environment.SpecialFolder.ProgramFilesX86));
        yield return ("{LocalAppData}", Folder(Environment.SpecialFolder.LocalApplicationData));
        yield return ("{AppData}", Folder(Environment.SpecialFolder.ApplicationData));
        yield return ("{Temp}", Path.GetTempPath());
        // Environment.SpecialFolder has no Downloads entry; build the path from the user profile.
        yield return ("{Downloads}", DownloadsFolder());
    }

    private static string? Folder(Environment.SpecialFolder folder)
    {
        var path = Environment.GetFolderPath(folder);
        return string.IsNullOrEmpty(path) ? null : path;
    }

    private static string? DownloadsFolder()
    {
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return string.IsNullOrEmpty(profile) ? null : Path.Combine(profile, "Downloads");
    }
}
