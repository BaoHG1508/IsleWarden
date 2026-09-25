using System.Management;
using System.Runtime.Versioning;

namespace IsleWarden.Core;

/// <summary>
/// Reads stable hardware identifiers via WMI (disk, baseboard and BIOS serials, CPU ID). Windows only;
/// any source may be missing (virtual machine, no access, blank OEM value) and is skipped. The more
/// sources, the harder it is to evade the fingerprint by swapping one component; see docs/HWID-BANNING.md.
/// </summary>
public static class WmiIdentifiers
{
    // Placeholder values OEMs commonly leave in blank fields; never used as identifiers.
    private static readonly HashSet<string> Junk = new(StringComparer.OrdinalIgnoreCase)
    {
        "", "0", "none", "null", "default string", "to be filled by o.e.m.",
        "system serial number", "not applicable", "not available", "invalid",
        "00000000", "ffffffff", "o.e.m.", "oem"
    };

    /// <summary>Collects every readable WMI identifier as {name: value}; empty on non-Windows.</summary>
    public static IReadOnlyDictionary<string, string> Collect()
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        if (OperatingSystem.IsWindows())
            CollectWindows(result);
        return result;
    }

    [SupportedOSPlatform("windows")]
    private static void CollectWindows(Dictionary<string, string> result)
    {
        Add(result, "diskSerial", DiskSerial);
        Add(result, "baseboardSerial", () => Query("Win32_BaseBoard", "SerialNumber"));
        Add(result, "biosSerial", () => Query("Win32_BIOS", "SerialNumber"));
        Add(result, "cpuId", () => Query("Win32_Processor", "ProcessorId"));
    }

    private static void Add(Dictionary<string, string> target, string key, Func<string?> read)
    {
        try
        {
            var value = read()?.Trim();
            if (value is not null && !Junk.Contains(value))
                target[key] = value;
        }
        catch
        {
            // Skip an unreadable source; the others still count.
        }
    }

    /// <summary>Serial of the disk hosting Windows, else the first non-USB disk; USB drives may be temporary, so they are skipped.</summary>
    [SupportedOSPlatform("windows")]
    private static string? DiskSerial()
    {
        var systemDrive = Path.GetPathRoot(Environment.SystemDirectory)?.TrimEnd('\\', '/'); // e.g. "C:"
        string? firstFixed = null;

        using var searcher = new ManagementObjectSearcher(
            "SELECT SerialNumber, InterfaceType, Index FROM Win32_DiskDrive");
        foreach (var drive in searcher.Get().Cast<ManagementObject>())
        {
            using (drive)
            {
                if (drive["InterfaceType"] as string == "USB")
                    continue;

                var serial = (drive["SerialNumber"] as string)?.Trim();
                if (string.IsNullOrEmpty(serial) || Junk.Contains(serial))
                    continue;

                firstFixed ??= serial;
                if (systemDrive is not null && DriveHostsSystem(drive, systemDrive))
                    return serial;
            }
        }

        return firstFixed;
    }

    [SupportedOSPlatform("windows")]
    private static bool DriveHostsSystem(ManagementObject drive, string systemDrive)
    {
        try
        {
            foreach (var partition in Related(drive, "Win32_DiskDriveToDiskPartition"))
            using (partition)
            {
                foreach (var logical in Related(partition, "Win32_LogicalDiskToPartition"))
                using (logical)
                {
                    if (string.Equals(logical["DeviceID"] as string, systemDrive, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
        }
        catch
        {
            // Partitions can't be traced: treat as unknown and fall back to the first fixed disk.
        }

        return false;
    }

    [SupportedOSPlatform("windows")]
    private static IEnumerable<ManagementObject> Related(ManagementObject source, string associationClass) =>
        source.GetRelated(null, associationClass, null, null, null, null, false, null).Cast<ManagementObject>();

    [SupportedOSPlatform("windows")]
    private static string? Query(string wmiClass, string property)
    {
        using var searcher = new ManagementObjectSearcher($"SELECT {property} FROM {wmiClass}");
        foreach (var item in searcher.Get().Cast<ManagementObject>())
        {
            using (item)
            {
                var value = item[property] as string;
                if (!string.IsNullOrWhiteSpace(value))
                    return value;
            }
        }

        return null;
    }
}
