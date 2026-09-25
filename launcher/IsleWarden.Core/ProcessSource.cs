using System.Diagnostics;
using System.Runtime.InteropServices;

namespace IsleWarden.Core;

public sealed record ProcessInfo(int Id, string Name);

/// <summary>Abstracts the process list so scanners can be tested without real processes.</summary>
public interface IProcessSource
{
    IReadOnlyList<ProcessInfo> GetProcesses();

    string? TryGetExecutablePath(int processId);

    DateTimeOffset? TryGetStartTimeUtc(int processId);
}

/// <summary>Reads the machine's real processes, requesting only minimal query access.</summary>
public sealed class SystemProcessSource : IProcessSource
{
    public IReadOnlyList<ProcessInfo> GetProcesses()
    {
        Process[] processes;
        try
        {
            processes = Process.GetProcesses();
        }
        catch
        {
            return [];
        }

        var list = new List<ProcessInfo>(processes.Length);
        foreach (var p in processes)
        {
            using (p)
            {
                try
                {
                    list.Add(new ProcessInfo(p.Id, p.ProcessName));
                }
                catch
                {
                    // The process exited in the meantime.
                }
            }
        }

        return list;
    }

    public string? TryGetExecutablePath(int processId)
    {
        if (OperatingSystem.IsWindows())
            return NativeProcess.TryQueryImagePath(processId);

        try
        {
            using var p = Process.GetProcessById(processId);
            return p.MainModule?.FileName;
        }
        catch
        {
            return null;
        }
    }

    public DateTimeOffset? TryGetStartTimeUtc(int processId)
    {
        try
        {
            using var p = Process.GetProcessById(processId);
            return new DateTimeOffset(p.StartTime).ToUniversalTime();
        }
        catch
        {
            return null;
        }
    }
}

/// <summary>
/// Reads a process's image path with PROCESS_QUERY_LIMITED_INFORMATION, which also works for protected
/// processes and processes of a different bitness, and needs no memory-read access.
/// </summary>
internal static class NativeProcess
{
    private const uint ProcessQueryLimitedInformation = 0x1000;

    public static string? TryQueryImagePath(int processId)
    {
        var handle = OpenProcess(ProcessQueryLimitedInformation, false, processId);
        if (handle == IntPtr.Zero)
            return null;

        try
        {
            var buffer = new char[1024];
            var size = (uint)buffer.Length;
            return QueryFullProcessImageNameW(handle, 0, buffer, ref size)
                ? new string(buffer, 0, (int)size)
                : null;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint desiredAccess, [MarshalAs(UnmanagedType.Bool)] bool inheritHandle, int processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryFullProcessImageNameW(IntPtr process, uint flags, [Out] char[] exeName, ref uint size);
}
