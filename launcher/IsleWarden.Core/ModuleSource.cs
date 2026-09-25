using System.Diagnostics;

namespace IsleWarden.Core;

public sealed record ModuleInfo(string Name, string Path);

/// <summary>Source of a process's loaded modules; an interface so tests can substitute a fake.</summary>
public interface IModuleSource
{
    /// <summary>Null, with the reason in <paramref name="error"/>, if the modules can't be read (access denied, protected process, ...).</summary>
    IReadOnlyList<ModuleInfo>? TryGetModules(int processId, out string? error);
}

/// <summary>
/// Reads the modules of real processes. A PID that was denied access is not retried, so the scan doesn't
/// open a handle to the EasyAntiCheat-protected game process on every pass.
/// </summary>
public sealed class SystemModuleSource : IModuleSource
{
    private readonly Dictionary<int, string> _denied = new();

    public IReadOnlyList<ModuleInfo>? TryGetModules(int processId, out string? error)
    {
        if (_denied.TryGetValue(processId, out error))
            return null;

        try
        {
            using var process = Process.GetProcessById(processId);
            var modules = new List<ModuleInfo>();
            foreach (ProcessModule module in process.Modules)
            {
                using (module)
                    modules.Add(new ModuleInfo(module.ModuleName ?? "", module.FileName ?? ""));
            }

            error = null;
            return modules;
        }
        catch (ArgumentException)
        {
            error = "Tiến trình đã thoát.";
            return null;
        }
        catch (Exception ex)
        {
            error = ex.Message;
            _denied[processId] = error;
            return null;
        }
    }
}
