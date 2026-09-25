using System.Runtime.InteropServices;
using System.Text;

namespace IsleWarden.Core.Tests;

/// <summary>
/// Builds fake Prefetch file content so tests don't depend on <c>C:\Windows\Prefetch</c>
/// (readable only by Administrators).
/// </summary>
internal static class PrefetchFixture
{
    private const int InfoOffset = 0x54;
    private const ushort XpressHuff = 4;

    /// <summary>Uncompressed .pf content (SCCA format, as older Windows versions write it).</summary>
    public static byte[] Scca(string executableName, uint version = 30, DateTimeOffset? lastRun = null, uint runCount = 3)
    {
        var (lastRunOffset, runCountOffset) = version switch
        {
            17 => (InfoOffset + 0x24, InfoOffset + 0x3C),
            23 => (InfoOffset + 0x2C, InfoOffset + 0x44),
            26 => (InfoOffset + 0x2C, InfoOffset + 0x7C),
            _ => (InfoOffset + 0x2C, InfoOffset + 0x74)
        };

        var buffer = new byte[InfoOffset + 0x100];
        BitConverter.GetBytes(version).CopyTo(buffer, 0);
        Encoding.ASCII.GetBytes("SCCA").CopyTo(buffer, 4);
        BitConverter.GetBytes((uint)buffer.Length).CopyTo(buffer, 0x0C);
        Encoding.Unicode.GetBytes(executableName).CopyTo(buffer, 0x10);
        BitConverter.GetBytes((lastRun ?? DateTimeOffset.UtcNow).UtcDateTime.ToFileTimeUtc()).CopyTo(buffer, lastRunOffset);
        BitConverter.GetBytes(runCount).CopyTo(buffer, runCountOffset);
        return buffer;
    }

    /// <summary>Wraps content in an XPRESS Huffman-compressed MAM container, as newer Windows versions write it.</summary>
    public static byte[] Mam(byte[] content)
    {
        if (RtlGetCompressionWorkSpaceSize(XpressHuff, out var workSpaceSize, out _) != 0)
            throw new InvalidOperationException("ntdll không cấp được vùng làm việc để nén.");

        var compressed = new byte[content.Length * 2 + 4096];
        var status = RtlCompressBuffer(
            XpressHuff, content, (uint)content.Length, compressed, (uint)compressed.Length,
            4096, out var written, new byte[workSpaceSize]);

        if (status != 0)
            throw new InvalidOperationException($"RtlCompressBuffer trả về 0x{status:X8}.");

        var result = new byte[8 + written];
        "MAM"u8.CopyTo(result);
        result[3] = (byte)XpressHuff;
        BitConverter.GetBytes((uint)content.Length).CopyTo(result, 4);
        Array.Copy(compressed, 0, result, 8, written);
        return result;
    }

    [DllImport("ntdll.dll")]
    private static extern int RtlGetCompressionWorkSpaceSize(
        ushort compressionFormatAndEngine, out uint bufferWorkSpaceSize, out uint fragmentWorkSpaceSize);

    [DllImport("ntdll.dll")]
    private static extern int RtlCompressBuffer(
        ushort compressionFormatAndEngine,
        byte[] uncompressedBuffer, uint uncompressedBufferSize,
        byte[] compressedBuffer, uint compressedBufferSize,
        uint uncompressedChunkSize, out int finalCompressedSize, byte[] workSpace);
}
