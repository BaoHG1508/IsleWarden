namespace IsleWarden.Core.Protocol;

// Access control: the INDEPENDENT gates a join request must pass, and the concrete reason when one blocks.
// Collapsing them into a single "allowed / not allowed" flag is a design bug: when a player asks "why can't
// I get in", the answer has to name WHICH gate is blocking. See docs/ACCESS-CONTROL-REFERENCE.md §1 and §6.1.

/// <summary>The gates, in the order the server evaluates them.</summary>
public enum AccessGate
{
    /// <summary>Device: valid key, not rejected, approved by an admin.</summary>
    Device,

    /// <summary>Ban list: Steam ID, device, hardware component.</summary>
    Ban,

    /// <summary>The Steam ID's linked Discord account is in the server's guild and holds a required role.</summary>
    Discord,

    /// <summary>Agreed to the current disclosure.</summary>
    Consent,

    /// <summary>Scan report — only blocks in Enforce mode.</summary>
    AntiCheat,

    /// <summary>The held play lease: expired after lost heartbeats, revoked by an admin, or released by the launcher.</summary>
    Lease
}

public enum GateStatus
{
    Passed,
    Blocked,

    /// <summary>Would have blocked, but the Steam ID holds an admin-granted bypass.</summary>
    Bypassed
}

/// <summary>Outcome of one gate — the launcher prints these so the player sees which steps passed.</summary>
public sealed record GateResult(AccessGate Gate, GateStatus Status, string? Note = null);

/// <summary>The concrete reason a join was blocked or a lease ended.</summary>
/// <param name="Code">Stable code from <see cref="AccessCodes"/> — automate on the code, never on the wording.</param>
/// <param name="Label">Short sentence for the player.</param>
/// <param name="Detail">Specifics: ban reason, the findings over the threshold, ...</param>
/// <param name="Until">When the block ends (timed ban); null = permanent or not applicable.</param>
/// <param name="SupportCode">Reference the player quotes to an admin: <c>R-123</c> = scan report, <c>B-45</c> = ban entry.</param>
public sealed record AccessBlock(
    AccessGate Gate,
    string Code,
    string Label,
    string? Detail = null,
    DateTimeOffset? Until = null,
    string? SupportCode = null);

/// <summary>
/// Stable block codes. The launcher and admin tooling act on these, so never change a released value —
/// only add new ones.
/// </summary>
public static class AccessCodes
{
    // Device gate
    public const string DeviceUnknown = "device-unknown";
    public const string DevicePending = "device-pending";
    public const string DeviceRejected = "device-rejected";

    // Ban gate
    public const string Banned = "banned";

    // Discord gate
    public const string DiscordNotLinked = "discord-not-linked";
    public const string DiscordNotMember = "discord-not-member";
    public const string DiscordRoleMissing = "discord-role-missing";

    // Consent gate
    public const string ConsentRequired = "consent-required";

    // Anti-cheat gate
    public const string AntiCheatBlocked = "anticheat-blocked";

    // Lease. Kept strictly apart from anti-cheat: a player dropped for lost heartbeats who sees the word
    // "anti-cheat" will assume they are suspected of cheating.
    public const string LeaseExpired = "lease-expired";
    public const string LeaseRevoked = "lease-revoked";
    public const string LeaseReleased = "lease-released";
    public const string LeaseInvalid = "lease-invalid";

    public static IReadOnlyList<string> All { get; } =
    [
        DeviceUnknown, DevicePending, DeviceRejected, Banned, DiscordNotLinked, DiscordNotMember, DiscordRoleMissing,
        ConsentRequired, AntiCheatBlocked, LeaseExpired, LeaseRevoked, LeaseReleased, LeaseInvalid
    ];
}
