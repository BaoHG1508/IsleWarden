namespace IsleWarden.Core;

/// <summary>Finding severity, in ascending order.</summary>
/// <remarks>
/// Info is informational only and never makes a report unclean.
/// In Enforce mode the server blocks at a threshold (<c>EnforceThreshold</c>, High by default).
/// </remarks>
public enum Severity
{
    Info,
    Low,
    Medium,
    High,
    Critical
}
