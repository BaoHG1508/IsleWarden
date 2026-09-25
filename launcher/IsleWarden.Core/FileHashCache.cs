using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace IsleWarden.Core;

/// <summary>
/// SHA-256 cache keyed by file size and last write time. Unchanged files are not re-hashed, so periodic
/// scans of large game files stay cheap.
/// </summary>
public sealed class FileHashCache
{
    private sealed record Entry(long Length, DateTime LastWriteUtc, string Sha256);

    private readonly ConcurrentDictionary<string, Entry> _entries = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>Returns the hash, from the cache if the file is unchanged; null if the file can't be read.</summary>
    public string? TryGetSha256(string path)
    {
        var info = TryGetInfo(path);
        if (info is null)
            return null;

        if (_entries.TryGetValue(info.FullName, out var entry) && Matches(entry, info))
            return entry.Sha256;

        var hash = ComputeSha256(info.FullName);
        if (hash is not null)
            _entries[info.FullName] = new Entry(info.Length, info.LastWriteTimeUtc, hash);
        return hash;
    }

    /// <summary>Reads the cache only; never hashes the file.</summary>
    public bool TryGetCached(string path, out string? hash)
    {
        hash = null;
        var info = TryGetInfo(path);
        if (info is null || !_entries.TryGetValue(info.FullName, out var entry) || !Matches(entry, info))
            return false;

        hash = entry.Sha256;
        return true;
    }

    /// <summary>Computes the SHA-256 as uppercase hex; null if the file can't be read.</summary>
    public static string? ComputeSha256(string path)
    {
        try
        {
            // Share read/write/delete so files the game currently has open can still be read.
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete, 1 << 20, FileOptions.SequentialScan);
            return Convert.ToHexString(SHA256.HashData(stream));
        }
        catch
        {
            return null;
        }
    }

    private static FileInfo? TryGetInfo(string path)
    {
        try
        {
            var info = new FileInfo(path);
            return info.Exists ? info : null;
        }
        catch
        {
            return null;
        }
    }

    private static bool Matches(Entry entry, FileInfo info) =>
        entry.Length == info.Length && entry.LastWriteUtc == info.LastWriteTimeUtc;
}
