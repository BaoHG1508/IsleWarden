using Microsoft.Win32;

namespace IsleWarden.Core;

public sealed record SteamGameInstall(string AppId, string InstallDirectory, string? BuildId, string LibraryPath);

/// <summary>
/// Finds the game's install directory through Steam (registry → libraryfolders.vdf → appmanifest), so
/// policies can use <c>{GameDir}</c> instead of fixed paths that differ between machines.
/// </summary>
public static class SteamLocator
{
    public static string? FindSteamRoot()
    {
        if (!OperatingSystem.IsWindows())
            return null;

        (string Key, string Value)[] sources =
        [
            (@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamPath"),
            (@"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (@"HKEY_LOCAL_MACHINE\SOFTWARE\Valve\Steam", "InstallPath")
        ];

        foreach (var (key, value) in sources)
        {
            try
            {
                if (Registry.GetValue(key, value, null) is string path && Directory.Exists(path))
                    return Path.GetFullPath(path);
            }
            catch
            {
                // Unreadable key: try the next source.
            }
        }

        var fallback = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Steam");
        return Directory.Exists(fallback) ? fallback : null;
    }

    public static SteamGameInstall? FindGame(string appId, string? steamRoot = null)
    {
        steamRoot ??= FindSteamRoot();
        if (steamRoot is null)
            return null;

        foreach (var library in GetLibraries(steamRoot))
        {
            var manifestPath = Path.Combine(library, "steamapps", $"appmanifest_{appId}.acf");
            if (!File.Exists(manifestPath))
                continue;

            VdfNode? state;
            try
            {
                state = VdfParser.Parse(File.ReadAllText(manifestPath))["AppState"];
            }
            catch
            {
                continue;
            }

            var installDir = state?.GetString("installdir");
            if (state is null || string.IsNullOrWhiteSpace(installDir))
                continue;

            var directory = Path.Combine(library, "steamapps", "common", installDir);
            if (Directory.Exists(directory))
                return new SteamGameInstall(appId, directory, state.GetString("buildid"), library);
        }

        return null;
    }

    /// <summary>Steam libraries: the Steam root plus the libraries listed in libraryfolders.vdf.</summary>
    public static IReadOnlyList<string> GetLibraries(string steamRoot)
    {
        var libraries = new List<string> { steamRoot };
        var file = Path.Combine(steamRoot, "steamapps", "libraryfolders.vdf");
        if (File.Exists(file))
        {
            try
            {
                var root = VdfParser.Parse(File.ReadAllText(file))["libraryfolders"];
                foreach (var entry in root?.Children.Values ?? [])
                {
                    // Current format: "0" { "path" "..." }; legacy format: "1" "D:\\SteamLibrary".
                    var path = entry.GetString("path") ?? entry.Value;
                    if (!string.IsNullOrWhiteSpace(path) && Directory.Exists(path))
                        libraries.Add(path);
                }
            }
            catch
            {
                // Corrupt file: fall back to the Steam root alone.
            }
        }

        return libraries
            .Select(Path.GetFullPath)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }
}
