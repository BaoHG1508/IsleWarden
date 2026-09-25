using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using IsleWarden.Core;

namespace IsleWarden.Agent;

internal static class AgentInfo
{
    public static string Version { get; } =
        typeof(AgentInfo).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";

    /// <summary>When the launcher process started — the reference for the game startup-order check.</summary>
    public static DateTimeOffset StartedUtc { get; } = GetStartTime();

    private static DateTimeOffset GetStartTime()
    {
        try
        {
            using var self = Process.GetCurrentProcess();
            return new DateTimeOffset(self.StartTime).ToUniversalTime();
        }
        catch
        {
            return DateTimeOffset.UtcNow;
        }
    }
}

/// <summary>Launcher state on disk: the registered device, the accepted disclosure version, and the lease held.</summary>
internal sealed record AgentState
{
    public string? ServerUrl { get; init; }
    public string? DeviceId { get; init; }

    /// <summary>Device key, DPAPI-protected — only the current Windows account can decrypt it.</summary>
    public string? ProtectedDeviceKey { get; init; }

    public string? SteamId { get; init; }
    public string? ConsentVersion { get; init; }

    /// <summary>The lease currently held; only left behind when the launcher dies without handing it back.</summary>
    public SavedLease? Lease { get; init; }

    public static string DefaultPath { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "IsleWarden", "agent.json");

    public static AgentState Load(string? path = null)
    {
        path ??= DefaultPath;
        if (!File.Exists(path))
            return new AgentState();

        try
        {
            return JsonSerializer.Deserialize<AgentState>(File.ReadAllText(path), IsleWardenJson.Config) ?? new AgentState();
        }
        catch
        {
            return new AgentState();
        }
    }

    public void Save(string? path = null)
    {
        path ??= DefaultPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, JsonSerializer.Serialize(this, IsleWardenJson.Config));
    }

    public string? GetDeviceKey() => ProtectedDeviceKey is null ? null : Secret.Unprotect(ProtectedDeviceKey);

    public AgentState WithDeviceKey(string deviceKey) => this with { ProtectedDeviceKey = Secret.Protect(deviceKey) };
}

/// <summary>A held lease, saved so a restarted launcher can resume it within the server's grace period.</summary>
/// <param name="ServerUrl">A lease only means something to the server that granted it.</param>
/// <param name="ProtectedToken">The lease token, DPAPI-protected like the device key.</param>
/// <param name="LauncherStartedUtc">When the launcher that took the lease started — the startup-order reference after a resume.</param>
internal sealed record SavedLease(
    string ServerUrl,
    string SessionId,
    string ProtectedToken,
    int HeartbeatSeconds,
    DateTimeOffset LauncherStartedUtc)
{
    public static SavedLease Create(string serverUrl, HeldLease lease, DateTimeOffset launcherStartedUtc) =>
        new(serverUrl, lease.SessionId, Secret.Protect(lease.Token), (int)lease.Heartbeat.TotalSeconds, launcherStartedUtc);

    public string? GetToken() => Secret.Unprotect(ProtectedToken);
}

/// <summary>Encrypts secrets with Windows DPAPI for the current user.</summary>
internal static class Secret
{
    private const int UiForbidden = 0x1;

    public static string Protect(string plain)
    {
        if (!OperatingSystem.IsWindows())
            return "plain:" + plain;

        return "dpapi:" + Convert.ToBase64String(Crypt(Encoding.UTF8.GetBytes(plain), protect: true));
    }

    public static string? Unprotect(string stored)
    {
        try
        {
            if (stored.StartsWith("plain:", StringComparison.Ordinal))
                return stored[6..];

            if (stored.StartsWith("dpapi:", StringComparison.Ordinal) && OperatingSystem.IsWindows())
                return Encoding.UTF8.GetString(Crypt(Convert.FromBase64String(stored[6..]), protect: false));
        }
        catch (Exception ex) when (ex is FormatException or CryptographicException)
        {
            // Corrupt, or protected by another Windows account: treat as not registered.
        }

        return null;
    }

    private static byte[] Crypt(byte[] input, bool protect)
    {
        var inBlob = new DataBlob { cbData = input.Length, pbData = Marshal.AllocHGlobal(Math.Max(1, input.Length)) };
        var outBlob = new DataBlob();
        try
        {
            Marshal.Copy(input, 0, inBlob.pbData, input.Length);
            var ok = protect
                ? CryptProtectData(ref inBlob, null, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, UiForbidden, ref outBlob)
                : CryptUnprotectData(ref inBlob, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, UiForbidden, ref outBlob);
            if (!ok)
                throw new CryptographicException(Marshal.GetLastWin32Error());

            var result = new byte[outBlob.cbData];
            Marshal.Copy(outBlob.pbData, result, 0, outBlob.cbData);
            return result;
        }
        finally
        {
            Marshal.FreeHGlobal(inBlob.pbData);
            if (outBlob.pbData != IntPtr.Zero)
                LocalFree(outBlob.pbData);
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob
    {
        public int cbData;
        public IntPtr pbData;
    }

    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(ref DataBlob dataIn, string? description, IntPtr entropy,
        IntPtr reserved, IntPtr prompt, int flags, ref DataBlob dataOut);

    [DllImport("crypt32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(ref DataBlob dataIn, IntPtr description, IntPtr entropy,
        IntPtr reserved, IntPtr prompt, int flags, ref DataBlob dataOut);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr handle);
}
