using System.Text.Json;
using IsleWarden.Core;

namespace IsleWarden.Agent;

/// <summary>Scans locally using policy.json, without a server (observe/testing mode).</summary>
internal static class ScanCommand
{
    public static async Task<int> RunAsync(string[] args)
    {
        var cmd = new CommandLine(args);
        var once = cmd.Has("--once");
        var policyPath = cmd.Positional.FirstOrDefault() ?? "policy.json";

        Policy policy;
        try
        {
            policy = IsleWardenJson.LoadPolicy(policyPath);
        }
        catch (Exception ex)
        {
            await Console.Error.WriteLineAsync($"Không đọc được policy '{policyPath}': {ex.Message}");
            await Console.Error.WriteLineAsync("Gợi ý: sao chép config/policy.example.json thành policy.json rồi chỉnh lại.");
            return 2;
        }

        var context = ScanContext.Resolve(policy, AgentInfo.StartedUtc);
        context = context with { Baseline = LoadLocalBaseline(policy, policyPath, context.GameBuildId) };

        Console.WriteLine($"IsleWarden Agent {AgentInfo.Version} — chế độ {policy.Mode}, quét mỗi {policy.IntervalSeconds}s (Ctrl+C để dừng).");
        if (!string.IsNullOrWhiteSpace(policy.Disclosure))
            Console.WriteLine($"[Thông báo cho người chơi | {policy.DisclosureVersion}] {policy.Disclosure}");
        Console.WriteLine(context.GameDirectory is null
            ? "Thư mục game: (không xác định)"
            : $"Thư mục game: {context.GameDirectory} (build {context.GameBuildId ?? "?"})");
        Console.WriteLine();

        var scanner = new Scanner();
        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            stop.Cancel();
        };

        var worst = 0;
        while (!stop.IsCancellationRequested)
        {
            var report = scanner.Run(policy, context);
            Console.WriteLine(JsonSerializer.Serialize(report, IsleWardenJson.Pretty));

            if (!report.Clean)
            {
                worst = 1;
                if (policy.Mode == EnforcementMode.Enforce)
                    Console.WriteLine(">> ENFORCE: khi vào server qua lệnh 'play', phiên sẽ bị từ chối hoặc thu hồi.");
            }

            if (once)
                break;

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(Math.Max(5, policy.IntervalSeconds)), stop.Token);
            }
            catch (TaskCanceledException)
            {
                break;
            }
        }

        return once ? worst : 0;
    }

    /// <summary>Loads the local baseline. Relative paths resolve against the policy file's folder; <c>{BuildId}</c> is substituted.</summary>
    internal static Baseline? LoadLocalBaseline(Policy policy, string policyPath, string? buildId)
    {
        if (policy.Baseline?.Path is not { Length: > 0 } configured)
            return null;

        var relative = configured.Replace("{BuildId}", buildId ?? "unknown", StringComparison.OrdinalIgnoreCase);
        var path = Path.IsPathRooted(relative)
            ? relative
            : Path.Combine(Path.GetDirectoryName(Path.GetFullPath(policyPath)) ?? ".", relative);

        if (!File.Exists(path))
            return null;

        try
        {
            return IsleWardenJson.LoadBaseline(path);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Không đọc được baseline '{path}': {ex.Message}");
            return null;
        }
    }
}
