using System.Runtime.InteropServices;
using System.Text;

namespace IsleWarden.Core;

/// <summary>One entry of the Windows execution history (a <c>.pf</c> file in the Prefetch folder).</summary>
/// <param name="ExecutableName">Executable name as Windows records it, e.g. <c>ISLEUNLOCKER.EXE</c>.</param>
/// <param name="LastRunUtc">Last run time; falls back to the .pf file's last write time when the embedded timestamp can't be read.</param>
/// <param name="RunCount">Run count; null for an unknown format version or an implausible value.</param>
/// <param name="FormatVersion">SCCA format version (30/31 = Windows 10/11).</param>
public sealed record PrefetchEntry(
    string ExecutableName,
    DateTimeOffset LastRunUtc,
    int? RunCount,
    uint FormatVersion);

/// <summary>
/// Parses Windows Prefetch (<c>.pf</c>) files: unwraps the MAM compression, then reads the program name,
/// last run time and run count.
/// </summary>
/// <remarks>
/// Since Windows 10, .pf files are XPRESS Huffman-compressed inside a "MAM" header; they are decompressed
/// with ntdll's <c>RtlDecompressBufferEx</c> (a public API). Older, uncompressed files are read as is.
///
/// The "File Information" block layout differs between format versions, so every value read by offset
/// (timestamp, run count) must pass a plausibility check and is null otherwise. Never guess: a wrong
/// number here could get a player punished unfairly.
/// </remarks>
public static class PrefetchReader
{
    private const int HeaderSize = 0x54;      // version + "SCCA" + program name + hash
    private const int NameOffset = 0x10;
    private const int NameMaxBytes = 60;      // 29 UTF-16 chars + terminator
    private const int InfoOffset = 0x54;      // File Information block follows the header
    private const ushort XpressHuff = 4;      // COMPRESSION_FORMAT_XPRESS_HUFF

    private const int MaxFileBytes = 4 * 1024 * 1024;
    private const int MaxDecompressedBytes = 32 * 1024 * 1024;

    /// <summary>Earliest plausible timestamp; anything older means the value was read from the wrong offset.</summary>
    private static readonly DateTimeOffset EarliestPlausibleRun = new(2010, 1, 1, 0, 0, 0, TimeSpan.Zero);

    /// <summary>Reads a .pf file; null if it is not a valid Prefetch file or can't be read.</summary>
    public static PrefetchEntry? TryRead(string path)
    {
        try
        {
            var info = new FileInfo(path);
            if (!info.Exists || info.Length is 0 or > MaxFileBytes)
                return null;

            return Parse(File.ReadAllBytes(path), new DateTimeOffset(info.LastWriteTimeUtc, TimeSpan.Zero));
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

    /// <param name="fileLastWriteUtc">Last write time of the .pf file, which Windows updates on every run; used when the embedded timestamp can't be read.</param>
    internal static PrefetchEntry? Parse(byte[] raw, DateTimeOffset fileLastWriteUtc)
    {
        var content = IsCompressed(raw) ? Decompress(raw) : raw;
        if (content is null || content.Length < HeaderSize)
            return null;

        if (Encoding.ASCII.GetString(content, 4, 4) != "SCCA")
            return null;

        var name = ReadName(content);
        if (name is null)
            return null;

        var version = BitConverter.ToUInt32(content, 0);
        var layout = Layout(version);

        return new PrefetchEntry(
            name,
            ReadLastRun(content, layout?.LastRun) ?? fileLastWriteUtc,
            ReadRunCount(content, layout?.RunCount),
            version);
    }

    /// <summary>
    /// Offsets of the last run time and run count in the File Information block, by format version.
    /// Version 31 (Windows 11) shares the start of version 30's layout, but its run count offset is
    /// unconfirmed, so it is null instead of a guess.
    /// </summary>
    private static (int LastRun, int? RunCount)? Layout(uint version) => version switch
    {
        17 => (InfoOffset + 0x24, InfoOffset + 0x3C),
        23 => (InfoOffset + 0x2C, InfoOffset + 0x44),
        26 => (InfoOffset + 0x2C, InfoOffset + 0x7C),
        30 => (InfoOffset + 0x2C, InfoOffset + 0x74),
        31 => (InfoOffset + 0x2C, null),
        _ => null
    };

    private static string? ReadName(byte[] content)
    {
        var end = NameOffset;
        var limit = NameOffset + NameMaxBytes;
        while (end + 1 < limit && (content[end] != 0 || content[end + 1] != 0))
            end += 2;

        var name = Encoding.Unicode.GetString(content, NameOffset, end - NameOffset).Trim();

        // A misaligned read yields garbage; a real program name never contains control characters or path separators.
        return name.Length == 0 || name.Any(c => char.IsControl(c) || c is '\\' or '/')
            ? null
            : name;
    }

    private static DateTimeOffset? ReadLastRun(byte[] content, int? offset)
    {
        if (offset is not { } at || at + 8 > content.Length)
            return null;

        try
        {
            var time = new DateTimeOffset(DateTime.FromFileTimeUtc(BitConverter.ToInt64(content, at)), TimeSpan.Zero);
            return time >= EarliestPlausibleRun && time <= DateTimeOffset.UtcNow.AddDays(1) ? time : null;
        }
        catch (ArgumentOutOfRangeException)
        {
            return null; // Not a valid FILETIME.
        }
    }

    private static int? ReadRunCount(byte[] content, int? offset)
    {
        if (offset is not { } at || at + 4 > content.Length)
            return null;

        var count = BitConverter.ToUInt32(content, at);
        return count is > 0 and <= 1_000_000 ? (int)count : null;
    }

    private static bool IsCompressed(byte[] raw) =>
        raw.Length >= 8 && raw[0] == (byte)'M' && raw[1] == (byte)'A' && raw[2] == (byte)'M';

    /// <summary>Unwraps a MAM file; null if it is not XPRESS Huffman or ntdll rejects it.</summary>
    private static byte[]? Decompress(byte[] raw)
    {
        if (!OperatingSystem.IsWindows())
            return null;

        if ((ushort)(raw[3] & 0x0F) != XpressHuff)
            return null;

        var headerSize = (raw[3] & 0x80) != 0 ? 12 : 8; // flag 0x80: header has an extra 4-byte checksum
        if (raw.Length <= headerSize)
            return null;

        var size = BitConverter.ToUInt32(raw, 4);
        if (size is 0 or > MaxDecompressedBytes)
            return null;

        try
        {
            if (RtlGetCompressionWorkSpaceSize(XpressHuff, out var workSpaceSize, out _) != 0)
                return null;

            var compressed = raw[headerSize..];
            var output = new byte[size];
            var status = RtlDecompressBufferEx(
                XpressHuff, output, size, compressed, (uint)compressed.Length,
                out var written, new byte[workSpaceSize]);

            if (status != 0 || written == 0)
                return null;

            return written >= size ? output : output[..(int)written];
        }
        catch (DllNotFoundException)
        {
            return null;
        }
        catch (EntryPointNotFoundException)
        {
            return null;
        }
    }

    [DllImport("ntdll.dll")]
    private static extern int RtlGetCompressionWorkSpaceSize(
        ushort compressionFormatAndEngine, out uint bufferWorkSpaceSize, out uint fragmentWorkSpaceSize);

    [DllImport("ntdll.dll")]
    private static extern int RtlDecompressBufferEx(
        ushort compressionFormat,
        byte[] uncompressedBuffer, uint uncompressedBufferSize,
        byte[] compressedBuffer, uint compressedBufferSize,
        out uint finalUncompressedSize, byte[] workSpace);
}
