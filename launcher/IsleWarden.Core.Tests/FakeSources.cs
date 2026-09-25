using IsleWarden.Core;

namespace IsleWarden.Core.Tests;

internal sealed class FakeProcessSource : IProcessSource
{
    private readonly List<(ProcessInfo Info, string? Path, DateTimeOffset? Started)> _processes = new();

    public FakeProcessSource Add(int id, string name, string? path = null, DateTimeOffset? started = null)
    {
        _processes.Add((new ProcessInfo(id, name), path, started));
        return this;
    }

    public IReadOnlyList<ProcessInfo> GetProcesses() => _processes.Select(p => p.Info).ToList();

    public string? TryGetExecutablePath(int processId) =>
        _processes.FirstOrDefault(p => p.Info.Id == processId).Path;

    public DateTimeOffset? TryGetStartTimeUtc(int processId) =>
        _processes.FirstOrDefault(p => p.Info.Id == processId).Started;
}

internal sealed class FakeModuleSource : IModuleSource
{
    private readonly Dictionary<int, List<ModuleInfo>> _modules = new();
    private readonly HashSet<int> _denied = new();

    public FakeModuleSource AddModule(int processId, string name, string path)
    {
        (_modules.TryGetValue(processId, out var list) ? list : _modules[processId] = new()).Add(new ModuleInfo(name, path));
        return this;
    }

    public FakeModuleSource Deny(int processId)
    {
        _denied.Add(processId);
        return this;
    }

    public IReadOnlyList<ModuleInfo>? TryGetModules(int processId, out string? error)
    {
        if (_denied.Contains(processId))
        {
            error = "Truy cập bị từ chối (giả lập).";
            return null;
        }

        error = null;
        return _modules.GetValueOrDefault(processId, new());
    }
}
