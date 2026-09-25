namespace IsleWarden.Core;

/// <summary>Expands <c>{GameDir}</c> and environment variables in policy paths.</summary>
public static class PathTemplate
{
    public const string GameDirToken = "{GameDir}";

    public static bool UsesGameDirectory(string path) =>
        path.Contains(GameDirToken, StringComparison.OrdinalIgnoreCase);

    /// <summary>Returns null if the path needs the game directory and it is unknown.</summary>
    public static string? Resolve(string path, string? gameDirectory)
    {
        if (UsesGameDirectory(path))
        {
            if (gameDirectory is null)
                return null;
            path = path.Replace(GameDirToken, gameDirectory, StringComparison.OrdinalIgnoreCase);
        }

        return Environment.ExpandEnvironmentVariables(path);
    }
}
