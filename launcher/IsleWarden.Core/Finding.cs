namespace IsleWarden.Core;

/// <param name="Code">Stable code from <see cref="FindingCodes"/>.</param>
/// <param name="Detail">Optional technical detail, such as a path or hash.</param>
public sealed record Finding(
    string Code,
    Severity Severity,
    string Message,
    string? Detail = null);
