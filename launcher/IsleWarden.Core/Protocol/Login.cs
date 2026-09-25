using System.Security.Cryptography;
using System.Text;

namespace IsleWarden.Core.Protocol;

// Player login. Steam proves which Steam ID the player owns, Discord proves they are in the server's guild with
// a required role, and the launcher receives a device key. Native-app OAuth pattern (RFC 8252 loopback + PKCE):
//   1. The launcher listens on 127.0.0.1:<port> and opens <server>/login/start?port=&state=&challenge= in the browser.
//   2. Browser: Steam OpenID -> Discord OAuth2 -> redirect to http://127.0.0.1:<port>/callback?code=&state=
//   3. The launcher POSTs /api/login/complete with that code and its PKCE verifier and gets a LoginResponse.
// The final redirect only reaches a listener on the machine whose browser signed in, and only the launcher that
// started the flow knows the verifier, so a login link sent to someone else cannot hijack their account.

/// <summary>Redeems a finished browser login for a device key.</summary>
/// <param name="Code">One-time code the server sent to the launcher's loopback listener.</param>
/// <param name="CodeVerifier">PKCE verifier: proves this launcher is the one that started the login.</param>
/// <param name="Fingerprint">Hardware identifiers for the device record (the server stores hashes only).</param>
public sealed record LoginCompleteRequest(
    string Code,
    string CodeVerifier,
    string MachineName,
    string ConsentVersion,
    DeviceFingerprint? Fingerprint = null);

/// <param name="DeviceKey">The device's secret key — returned exactly once; the server stores only its hash.</param>
/// <param name="DiscordName">The linked Discord account; null when the server doesn't require Discord.</param>
public sealed record LoginResponse(
    string DeviceId,
    string DeviceKey,
    string SteamId,
    DeviceStatus Status,
    string? DiscordName);

/// <summary>
/// Stable codes for a failed login, returned in <see cref="ErrorResponse.Code"/>. A missing Discord membership or
/// role reuses <see cref="AccessCodes.DiscordNotMember"/> / <see cref="AccessCodes.DiscordRoleMissing"/>.
/// </summary>
public static class LoginCodes
{
    public const string Expired = "login-expired";
    public const string SteamFailed = "steam-login-failed";
    public const string DiscordFailed = "discord-login-failed";
    public const string DiscordLinkedElsewhere = "discord-linked-elsewhere";
    public const string SteamLinkedElsewhere = "steam-linked-elsewhere";
}

/// <summary>PKCE (RFC 7636, S256) shared by the launcher and the server.</summary>
public static class Pkce
{
    /// <summary>A fresh random verifier; also used for the loopback <c>state</c>.</summary>
    public static string NewVerifier() => Base64Url(RandomNumberGenerator.GetBytes(32));

    public static string Challenge(string verifier) => Base64Url(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)));

    public static bool Verify(string verifier, string challenge) =>
        CryptographicOperations.FixedTimeEquals(
            Encoding.ASCII.GetBytes(Challenge(verifier)), Encoding.ASCII.GetBytes(challenge));

    private static string Base64Url(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
}
