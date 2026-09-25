namespace IsleWarden.Core.Protocol;

// HTTP messages between the Agent (launcher) and IsleWarden.Server. (De)serialize with IsleWardenJson.Web.

public enum DeviceStatus
{
    Pending,
    Approved,
    Rejected
}

public enum SessionDecision
{
    Granted,
    Denied,
    PendingApproval,
    ConsentRequired,
    Banned
}

public enum SessionState
{
    Active,
    Revoked,
    Expired,
    Ended
}

/// <summary>The current policy plus the link to the player-facing disclosure page.</summary>
public sealed record PolicyEnvelope(Policy Policy, string? ConsentUrl);

/// <summary>Join request: carries the first scan report.</summary>
public sealed record SessionStartRequest(
    string DeviceId,
    string DeviceKey,
    string ConsentVersion,
    string AgentVersion,
    string? GameBuildId,
    ScanReport Report);

/// <summary>
/// Answer to a join request. When granted, <c>SessionId</c> + <c>Token</c> are the <em>play lease</em> —
/// separate from <c>DeviceKey</c>, which is the device's identity.
/// </summary>
/// <param name="ExpiresUtc">Lease expiry on the server's clock; renewed by each heartbeat.</param>
public sealed record SessionStartResponse(
    SessionDecision Decision,
    string? SessionId = null,
    string? Token = null,
    DateTimeOffset? ExpiresUtc = null,
    int HeartbeatSeconds = 30,
    string? Message = null)
{
    /// <summary>The blocking gate and why; null when granted.</summary>
    public AccessBlock? Block { get; init; }

    /// <summary>The gates evaluated, in order — stops at the first one that blocks.</summary>
    public IReadOnlyList<GateResult> Gates { get; init; } = [];

    /// <summary>
    /// Server time of the reply. Time left on the lease is <c>ExpiresUtc − ServerTime</c>; never compare
    /// <c>ExpiresUtc</c> with the player's own clock.
    /// </summary>
    public DateTimeOffset? ServerTime { get; init; }
}

/// <summary>Periodic signal while playing, carrying the latest scan report.</summary>
/// <param name="Resumed">The launcher just restarted and is resuming the lease it held before.</param>
public sealed record HeartbeatRequest(string SessionId, string Token, ScanReport Report, bool Resumed = false);

public sealed record HeartbeatResponse(SessionState State, DateTimeOffset? ExpiresUtc = null, string? Message = null)
{
    /// <summary>Why the lease ended; null while it is still valid.</summary>
    public AccessBlock? Block { get; init; }

    /// <summary>Server time of the reply — see <see cref="SessionStartResponse.ServerTime"/>.</summary>
    public DateTimeOffset? ServerTime { get; init; }

    /// <summary>The Steam ID holds an anti-cheat bypass: reports are still recorded, but findings never end the lease.</summary>
    public bool AntiCheatBypassed { get; init; }
}

/// <summary>The launcher hands its lease back on purpose (quit, window closed, shutdown).</summary>
/// <param name="Reason">Short reason; the server truncates it to 64 characters.</param>
public sealed record SessionEndRequest(string SessionId, string Token, string? Reason = null);

/// <param name="Code">Stable machine-readable reason when there is one, e.g. a <see cref="LoginCodes"/> value.</param>
public sealed record ErrorResponse(string Error, string? Code = null);
