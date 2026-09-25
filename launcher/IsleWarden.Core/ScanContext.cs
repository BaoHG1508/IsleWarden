namespace IsleWarden.Core;

/// <summary>Scan environment, resolved once when the Agent starts.</summary>
public sealed record ScanContext
{
    /// <summary>When the launcher started the session; the reference point for the startup order check.</summary>
    public DateTimeOffset AgentStartedUtc { get; init; } = DateTimeOffset.UtcNow;

    public string? GameDirectory { get; init; }
    public string? GameBuildId { get; init; }

    /// <summary>Baseline for the exact installed build, read from a file or downloaded from the server.</summary>
    public Baseline? Baseline { get; init; }

    /// <summary>Finds the game directory and build ID, preferring the policy's <c>GameDirectory</c> over Steam.</summary>
    public static ScanContext Resolve(Policy policy, DateTimeOffset agentStartedUtc, string? steamRoot = null)
    {
        string? directory = null;
        string? buildId = null;

        if (!string.IsNullOrWhiteSpace(policy.GameDirectory))
            directory = Environment.ExpandEnvironmentVariables(policy.GameDirectory);

        if (!string.IsNullOrWhiteSpace(policy.SteamAppId))
        {
            var install = SteamLocator.FindGame(policy.SteamAppId, steamRoot);
            if (install is not null)
            {
                directory ??= install.InstallDirectory;
                buildId = install.BuildId;
            }
        }

        return new ScanContext
        {
            AgentStartedUtc = agentStartedUtc,
            GameDirectory = directory is not null && Directory.Exists(directory) ? directory : null,
            GameBuildId = buildId
        };
    }
}
