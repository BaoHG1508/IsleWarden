using System.Text.Json;
using IsleWarden.Core;
using IsleWarden.Core.Protocol;
using Xunit;

namespace IsleWarden.Core.Tests;

/// <summary>
/// The access-control fields must survive the trip between server and launcher. They are init-only properties
/// next to positional record parameters — exactly where JSON (de)serialization tends to drop data silently.
/// </summary>
public class AccessProtocolTests
{
    [Fact]
    public void BlockAndGatesRoundTripWithCamelCaseEnums()
    {
        var response = new SessionStartResponse(SessionDecision.Denied, Message: "label")
        {
            Block = new AccessBlock(AccessGate.AntiCheat, AccessCodes.AntiCheatBlocked, "label", "detail",
                DateTimeOffset.Parse("2026-10-01T00:00:00Z"), "R-7"),
            Gates =
            [
                new GateResult(AccessGate.Device, GateStatus.Passed),
                new GateResult(AccessGate.AntiCheat, GateStatus.Bypassed, "streamer")
            ],
            ServerTime = DateTimeOffset.Parse("2026-09-26T00:00:00Z")
        };

        var json = JsonSerializer.Serialize(response, IsleWardenJson.Web);
        var back = JsonSerializer.Deserialize<SessionStartResponse>(json, IsleWardenJson.Web)!;

        Assert.Contains("\"antiCheat\"", json);
        Assert.Contains("\"bypassed\"", json);
        Assert.Equal(response.Block, back.Block);
        Assert.Equal(response.Gates, back.Gates);
        Assert.Equal(response.ServerTime, back.ServerTime);
    }

    [Fact]
    public void HeartbeatFromALauncherThatPredatesResumeStillParses()
    {
        const string json =
            """{"sessionId":"s","token":"t","report":{"timestampUtc":"2026-09-26T00:00:00Z","machine":"PC","clean":true,"findings":[]}}""";

        var request = JsonSerializer.Deserialize<HeartbeatRequest>(json, IsleWardenJson.Web)!;

        Assert.False(request.Resumed);
    }

    [Fact]
    public void ResponseFromAServerThatPredatesGatesHasNoBlockAndNoGates()
    {
        const string json = """{"decision":"granted","sessionId":"s","token":"t","heartbeatSeconds":30}""";

        var response = JsonSerializer.Deserialize<SessionStartResponse>(json, IsleWardenJson.Web)!;

        Assert.Null(response.Block);
        Assert.Empty(response.Gates);
        Assert.Null(response.ServerTime);
    }
}
