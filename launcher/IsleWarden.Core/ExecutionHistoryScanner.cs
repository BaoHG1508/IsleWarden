using System.Diagnostics;
using Microsoft.Win32;

namespace IsleWarden.Core;

/// <summary>
/// Checks the Windows execution history (Prefetch) against the policy's list of cheat tools. This catches
/// tools that were closed before the launcher started, which the process scan cannot see.
/// </summary>
/// <remarks>
/// Privacy boundary (intentional; do not loosen): match by the program name embedded in the <c>.pf</c>
/// file name first, and open only files whose name is on the list. Non-matching programs are dropped on
/// the spot: never opened, recorded or sent. Only runs within the last
/// <see cref="ExecutionHistoryRule.LookbackDays"/> days count.
/// This is the most privacy-sensitive check in Core: enabling it requires updating the disclosure and
/// bumping <c>disclosureVersion</c> so players consent again.
///
/// Only Administrators can read the Prefetch folder. When the launcher runs unelevated, this check only
/// reports <c>execution-history-unavailable</c> at Info and draws no conclusion.
/// </remarks>
public sealed class ExecutionHistoryScanner
{
    private const string PrefetchParametersKey =
        @"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters";

    public IEnumerable<Finding> Scan(Policy policy)
    {
        var rule = policy.ExecutionHistory;
        if (rule is not { Enabled: true } || (rule.Programs.Count == 0 && rule.Keywords.Count == 0))
            return [];

        return OperatingSystem.IsWindows()
            ? ScanWindows(rule)
            : [Unavailable("nhật ký thực thi chỉ có trên Windows")];
    }

    private static List<Finding> ScanWindows(ExecutionHistoryRule rule)
    {
        var findings = new List<Finding>();

        if (rule.ReportPrefetchDisabled && PrefetchEnabled() == false)
        {
            findings.Add(new Finding(FindingCodes.ExecutionHistoryOff, Severity.Info,
                "Nhật ký thực thi của Windows (Prefetch) đang tắt trên máy này.",
                "Có thể do tinh chỉnh hệ thống, cũng có thể là cách xoá dấu vết đã chạy công cụ."));
        }

        var directory = ResolveDirectory(rule);

        string[] files;
        try
        {
            files = Directory.GetFiles(directory, "*.pf");
        }
        catch (UnauthorizedAccessException)
        {
            findings.Add(Unavailable("thư mục Prefetch cần quyền quản trị để đọc"));
            return findings;
        }
        catch (DirectoryNotFoundException)
        {
            findings.Add(Unavailable($"không có thư mục {directory}"));
            return findings;
        }
        catch (IOException ex)
        {
            findings.Add(Unavailable(ex.Message));
            return findings;
        }

        var programs = rule.Programs
            .GroupBy(p => ProcessScanner.NormalizeName(p.Name))
            .ToDictionary(g => g.Key, g => g.First());

        // Short keywords match unrelated names (e.g. "esp" in "respondus"), so they are dropped.
        var keywords = rule.Keywords
            .Where(k => k.Keyword.Trim().Length >= Math.Max(1, rule.MinKeywordLength))
            .Select(k => k with { Keyword = k.Keyword.Trim().ToLowerInvariant() })
            .ToList();

        var allow = new HashSet<string>(
            rule.Allow.Select(ProcessScanner.NormalizeName), StringComparer.OrdinalIgnoreCase);

        var oldest = DateTimeOffset.UtcNow - TimeSpan.FromDays(Math.Max(1, rule.LookbackDays));
        var timeout = TimeSpan.FromSeconds(Math.Max(1, rule.TimeoutSeconds));
        var maxFiles = Math.Max(1, rule.MaxFilesExamined);
        var clock = Stopwatch.StartNew();
        var reported = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var examined = 0;

        foreach (var file in files)
        {
            if (++examined > maxFiles || clock.Elapsed > timeout)
                break;

            var name = ExecutableNameOf(Path.GetFileName(file));
            if (name is null)
                continue;

            var normalized = ProcessScanner.NormalizeName(name);
            if (allow.Contains(normalized) || reported.Contains(normalized))
                continue;

            // Match by name first; a file whose name doesn't match is never opened.
            var match = Match(normalized, programs, keywords);
            if (match is null)
                continue;

            var entry = PrefetchReader.TryRead(file);
            var lastRun = entry?.LastRunUtc ?? LastWrite(file);
            if (lastRun is null || lastRun < oldest)
                continue;

            reported.Add(normalized);
            findings.Add(new Finding(
                match.Value.Code,
                match.Value.Severity,
                $"Đã từng chạy trên máy này: {entry?.ExecutableName ?? name}",
                Describe(lastRun.Value, entry?.RunCount, match.Value.Reason)));
        }

        return findings;
    }

    private static (string Code, Severity Severity, string? Reason)? Match(
        string normalized,
        Dictionary<string, ExecutedProgram> programs,
        List<ProcessNameKeyword> keywords)
    {
        if (programs.TryGetValue(normalized, out var program))
            return (FindingCodes.ExecutedTool, program.Severity, program.Reason);

        var hit = keywords.FirstOrDefault(k => normalized.Contains(k.Keyword, StringComparison.Ordinal));
        if (hit is null)
            return null;

        // A keyword match is only a guess: keep the rule's severity (Low by default) for admin review.
        return (FindingCodes.SuspiciousExecutedName, hit.Severity,
            hit.Reason is null ? $"từ khoá “{hit.Keyword}”" : $"từ khoá “{hit.Keyword}”: {hit.Reason}");
    }

    /// <summary>Gets the program name from a .pf file name of the form <c>NAME.EXE-XXXXXXXX.pf</c>; null otherwise.</summary>
    internal static string? ExecutableNameOf(string prefetchFileName)
    {
        var stem = Path.GetFileNameWithoutExtension(prefetchFileName);
        var dash = stem.LastIndexOf('-');
        if (dash <= 0)
            return null;

        // The suffix is the path hash (8 hex digits); anything else is not a Prefetch entry.
        var suffix = stem[(dash + 1)..];
        return suffix.Length is >= 8 and <= 16 && suffix.All(Uri.IsHexDigit) ? stem[..dash] : null;
    }

    private static string Describe(DateTimeOffset lastRun, int? runCount, string? reason)
    {
        var parts = new List<string> { $"lần chạy gần nhất {lastRun.UtcDateTime:yyyy-MM-dd HH:mm} UTC" };
        if (runCount is > 0)
            parts.Add($"{runCount} lần");
        if (!string.IsNullOrWhiteSpace(reason))
            parts.Add(reason);

        return string.Join(" — ", parts);
    }

    private static string ResolveDirectory(ExecutionHistoryRule rule) =>
        string.IsNullOrWhiteSpace(rule.Directory)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Prefetch")
            : Environment.ExpandEnvironmentVariables(rule.Directory);

    private static DateTimeOffset? LastWrite(string file)
    {
        try
        {
            return new DateTimeOffset(File.GetLastWriteTimeUtc(file), TimeSpan.Zero);
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    /// <summary>Null if the registry value can't be read (Windows enables Prefetch by default).</summary>
    private static bool? PrefetchEnabled()
    {
        if (!OperatingSystem.IsWindows())
            return null;

        try
        {
            // 0 = disabled; 1 = app launch, 2 = boot, 3 = both.
            return Registry.GetValue(PrefetchParametersKey, "EnablePrefetcher", null) is int flag ? flag != 0 : null;
        }
        catch
        {
            return null;
        }
    }

    private static Finding Unavailable(string reason) =>
        new(FindingCodes.ExecutionHistoryUnavailable, Severity.Info,
            "Không đọc được nhật ký thực thi của Windows.", reason);
}
