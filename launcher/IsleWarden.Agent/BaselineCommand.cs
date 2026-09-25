using System.Diagnostics;
using IsleWarden.Core;

namespace IsleWarden.Agent;

/// <summary>Admin tool: builds a baseline of file hashes from a clean game install.</summary>
internal static class BaselineCommand
{
    public static int Run(string[] args)
    {
        var cmd = new CommandLine(args, "--game-dir", "--app-id", "--build-id", "--out", "--include", "--exclude");
        var appId = cmd.Get("--app-id") ?? "376210";
        var gameDir = cmd.Get("--game-dir");
        var install = SteamLocator.FindGame(appId);

        string? buildId = null;
        if (gameDir is null)
        {
            if (install is null)
            {
                Console.Error.WriteLine($"Không tìm thấy game (Steam app {appId}). Dùng --game-dir để chỉ định thư mục.");
                return 2;
            }

            gameDir = install.InstallDirectory;
            buildId = install.BuildId;
        }
        else if (install is not null && SamePath(install.InstallDirectory, gameDir))
        {
            buildId = install.BuildId;
        }

        buildId = cmd.Get("--build-id") ?? buildId;
        if (!Directory.Exists(gameDir))
        {
            Console.Error.WriteLine($"Không tồn tại thư mục game: {gameDir}");
            return 2;
        }

        var include = Split(cmd.Get("--include")) ?? BaselineBuilder.DefaultInclude;
        var exclude = Split(cmd.Get("--exclude")) ?? BaselineBuilder.DefaultExclude;
        var output = cmd.Get("--out") ?? $"{buildId ?? "baseline"}.json";

        Console.WriteLine($"Tạo baseline từ: {gameDir}");
        Console.WriteLine($"Build: {buildId ?? "(không rõ)"} · Mẫu: {string.Join(", ", include)} · Loại trừ: {string.Join(", ", exclude)}");

        var watch = Stopwatch.StartNew();
        var count = 0;
        var baseline = BaselineBuilder.Create(gameDir, include, exclude, appId, buildId,
            relative => Console.WriteLine($"  [{++count}] {relative}"));

        var fullOutput = Path.GetFullPath(output);
        Directory.CreateDirectory(Path.GetDirectoryName(fullOutput)!);
        IsleWardenJson.SaveBaseline(baseline, fullOutput);

        var totalMb = baseline.Files.Sum(f => f.Size) / 1024d / 1024d;
        Console.WriteLine($"Xong: {baseline.Files.Count} file, {totalMb:N0} MB, {watch.Elapsed.TotalSeconds:N1} giây → {fullOutput}");
        return 0;
    }

    private static List<string>? Split(string? value) =>
        string.IsNullOrWhiteSpace(value)
            ? null
            : value.Split([';', ','], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

    private static bool SamePath(string a, string b) =>
        string.Equals(Path.GetFullPath(a).TrimEnd('\\', '/'), Path.GetFullPath(b).TrimEnd('\\', '/'),
            StringComparison.OrdinalIgnoreCase);
}
