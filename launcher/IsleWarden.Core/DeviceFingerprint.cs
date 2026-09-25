using System.Net.NetworkInformation;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Win32;

namespace IsleWarden.Core;

/// <summary>
/// Device fingerprint for device bans on your server. <c>DeviceId</c> is the SHA-256 of the combined
/// hardware/OS components, so the server can match devices without storing raw serial numbers.
/// </summary>
public sealed record DeviceFingerprint(
    string DeviceId,
    IReadOnlyDictionary<string, string> Components);

/// <summary>
/// Collects stable identifiers from this machine and hashes them into a <c>DeviceId</c>. Any component
/// may be missing (no access, virtual machine, ...) and is skipped; the fingerprint uses whatever was read.
/// </summary>
public sealed class DeviceFingerprintCollector
{
    public DeviceFingerprint Collect()
    {
        var components = new SortedDictionary<string, string>(StringComparer.Ordinal);

        var machineGuid = TryMachineGuid();
        if (machineGuid is not null)
            components["machineGuid"] = machineGuid;

        var mac = TryPrimaryMac();
        if (mac is not null)
            components["mac"] = mac;

        foreach (var (key, value) in WmiIdentifiers.Collect())
            components[key] = value;

        var raw = string.Join("|", components.Select(kv => $"{kv.Key}={kv.Value}"));
        var deviceId = raw.Length == 0
            ? "UNKNOWN"
            : Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(raw)));

        return new DeviceFingerprint(deviceId, components);
    }

    /// <summary>MachineGuid is generated at Windows setup and stays stable until the OS is reinstalled.</summary>
    private static string? TryMachineGuid()
    {
        if (!OperatingSystem.IsWindows())
            return null;

        try
        {
            using var baseKey = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
            using var key = baseKey.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography");
            return key?.GetValue("MachineGuid") as string;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>MAC address of an active network adapter, preferring wired over Wi-Fi.</summary>
    private static string? TryPrimaryMac()
    {
        try
        {
            var nic = NetworkInterface.GetAllNetworkInterfaces()
                .Where(n => n.OperationalStatus == OperationalStatus.Up
                            && n.NetworkInterfaceType != NetworkInterfaceType.Loopback
                            && n.NetworkInterfaceType != NetworkInterfaceType.Tunnel)
                .OrderBy(n => n.NetworkInterfaceType == NetworkInterfaceType.Wireless80211 ? 1 : 0)
                .FirstOrDefault();

            var mac = nic?.GetPhysicalAddress().ToString();
            return string.IsNullOrWhiteSpace(mac) ? null : mac;
        }
        catch
        {
            return null;
        }
    }
}
