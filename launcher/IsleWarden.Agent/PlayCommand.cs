using System.Diagnostics;
using System.Net;
using IsleWarden.Core;
using IsleWarden.Core.Protocol;

namespace IsleWarden.Agent;

/// <summary>
/// Joins the server: consent → scan → take a lease (or resume the one already held) → (launch the game) →
/// heartbeat with fresh scans until the player quits or the server ends the lease.
/// </summary>
/// <remarks>
/// The lease (session id + token) is separate from the device identity (DeviceKey). It is saved DPAPI-protected
/// in agent.json, so a launcher that restarts mid-game (crash, closed by mistake) resumes it within the server's
/// grace period instead of losing its place. Quitting on purpose — Ctrl+C, closing the window, shutting down —
/// hands the lease back at once with a reason, so the server does not have to wait for it to expire.
/// </remarks>
internal static class PlayCommand
{
    /// <summary>Retry cadence after a failed heartbeat: tighter than the normal period, to reconnect before the lease runs out.</summary>
    private static readonly TimeSpan RetryDelay = TimeSpan.FromSeconds(5);

    public static async Task<int> RunAsync(string[] args)
    {
        var cmd = new CommandLine(args, "--server");
        var state = AgentState.Load();
        var server = cmd.Get("--server") ?? state.ServerUrl;
        var deviceKey = state.GetDeviceKey();
        if (server is null || state.DeviceId is null || deviceKey is null)
        {
            Console.Error.WriteLine("Máy này chưa đăng nhập. Chạy: IsleWarden.Agent login --server <URL>");
            return 2;
        }

        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            stop.Cancel();
        };
        using var shutdown = new ShutdownSignals(stop);

        using var client = new ServerClient(server);
        try
        {
            var envelope = await client.GetPolicyAsync(stop.Token);
            var policy = envelope.Policy;
            if (state.ConsentVersion != policy.DisclosureVersion)
            {
                if (!ConsoleUi.Consent(envelope, cmd.Has("--yes")))
                {
                    Console.WriteLine("Bạn chưa đồng ý nên không thể vào server.");
                    return 1;
                }

                state = state with { ConsentVersion = policy.DisclosureVersion };
                state.Save();
            }

            var context = ScanContext.Resolve(policy, AgentInfo.StartedUtc);
            if (policy.Baseline is not null && context.GameBuildId is not null)
                context = context with { Baseline = await client.TryGetBaselineAsync(context.GameBuildId, stop.Token) };

            Console.WriteLine(context.GameDirectory is null
                ? "Thư mục game: (không xác định)"
                : $"Thư mục game: {context.GameDirectory} (build {context.GameBuildId ?? "?"})");

            var scanner = new Scanner();
            HeldLease? lease = null;

            if (state.Lease is { } saved)
            {
                // A network error here propagates and keeps the saved lease for the next attempt.
                if (await TryResumeAsync(client, scanner, policy, context, server, saved, stop.Token) is { } resumed)
                {
                    (lease, context) = resumed;
                }
                else
                {
                    state = state with { Lease = null };
                    state.Save();
                }
            }

            if (lease is null)
            {
                var report = scanner.Run(policy, context);
                ConsoleUi.PrintSummary(report);

                var start = await client.StartSessionAsync(new SessionStartRequest(
                    state.DeviceId, deviceKey, policy.DisclosureVersion, AgentInfo.Version, context.GameBuildId, report), stop.Token);
                ConsoleUi.PrintDecision(start);
                if (start.Decision != SessionDecision.Granted || start.SessionId is null || start.Token is null)
                    return start.Decision == SessionDecision.PendingApproval ? 4 : 1;

                lease = new HeldLease(start.SessionId, start.Token, TimeSpan.FromSeconds(Math.Max(5, start.HeartbeatSeconds)));
                lease.Renew(start.ExpiresUtc, start.ServerTime);
                state = state with { Lease = SavedLease.Create(server, lease, context.AgentStartedUtc) };
                state.Save();

                Console.WriteLine("Giữ launcher chạy trong suốt lúc chơi — tắt launcher là trả suất chơi và rời server (Ctrl+C để thoát).");
                if (cmd.Has("--launch"))
                    LaunchGame(policy);
            }

            try
            {
                return await HeartbeatLoopAsync(client, scanner, policy, context, lease, shutdown, stop.Token);
            }
            finally
            {
                // The loop only returns once the lease is handed back or known to be over; only a crash leaves
                // it on disk for the next launcher to resume.
                (state with { Lease = null }).Save();
                shutdown.Released();
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested)
        {
            Console.WriteLine("Đã dừng.");
            return 0;
        }
        catch (Exception ex) when (ex is ServerException or HttpRequestException or TaskCanceledException)
        {
            Console.Error.WriteLine($"Không kết nối được server: {ex.Message}");
            return 3;
        }
        finally
        {
            shutdown.Released();
        }
    }

    /// <summary>
    /// Resumes the lease a previous launcher left behind if the server still considers it live. The original
    /// launcher start time stays the startup-order reference: the game was started under that launcher, not
    /// "before the launcher". The unwatched gap is bounded by the same grace period as a network blip.
    /// </summary>
    /// <returns>The resumed lease and scan context, or null when the saved lease is unusable or already over.</returns>
    private static async Task<(HeldLease Lease, ScanContext Context)?> TryResumeAsync(
        ServerClient client, Scanner scanner, Policy policy, ScanContext context, string server, SavedLease saved,
        CancellationToken ct)
    {
        if (!string.Equals(saved.ServerUrl, server, StringComparison.OrdinalIgnoreCase) || saved.GetToken() is not { } token)
            return null;

        var resumeContext = context with { AgentStartedUtc = saved.LauncherStartedUtc };
        var report = scanner.Run(policy, resumeContext);
        ConsoleUi.PrintSummary(report);

        var heartbeat = await client.HeartbeatAsync(
            new HeartbeatRequest(saved.SessionId, token, report, Resumed: true), ct);
        if (heartbeat.State != SessionState.Active)
        {
            Console.WriteLine($"Suất chơi trước đã kết thúc ({heartbeat.Block?.Label ?? heartbeat.Message}) — xin suất mới.");
            return null;
        }

        var lease = new HeldLease(saved.SessionId, token, TimeSpan.FromSeconds(Math.Max(5, saved.HeartbeatSeconds)));
        lease.Renew(heartbeat.ExpiresUtc, heartbeat.ServerTime);
        Console.WriteLine("Đã nối lại suất chơi đang giữ (launcher vừa khởi động lại) — không bị rớt khỏi server.");
        return (lease, resumeContext);
    }

    private static async Task<int> HeartbeatLoopAsync(
        ServerClient client, Scanner scanner, Policy policy, ScanContext context,
        HeldLease lease, ShutdownSignals shutdown, CancellationToken stop)
    {
        ScanReport? pending = null;
        var delay = lease.Heartbeat;

        try
        {
            while (true)
            {
                await Task.Delay(delay, stop);

                // A retry reuses the report just taken while it is still fresh, instead of rescanning every 5 s.
                if (pending is null || DateTimeOffset.UtcNow - pending.TimestampUtc > lease.Heartbeat)
                {
                    pending = scanner.Run(policy, context);
                    ConsoleUi.PrintSummary(pending);
                }

                try
                {
                    var heartbeat = await client.HeartbeatAsync(new HeartbeatRequest(lease.SessionId, lease.Token, pending), stop);
                    pending = null;
                    if (heartbeat.State != SessionState.Active)
                    {
                        ConsoleUi.PrintEnded(heartbeat);
                        return heartbeat.State == SessionState.Revoked ? 1 : 0;
                    }

                    lease.Renew(heartbeat.ExpiresUtc, heartbeat.ServerTime);
                    delay = lease.Heartbeat;
                }
                catch (Exception ex) when (IsTransient(ex) && !stop.IsCancellationRequested)
                {
                    if (lease.Remaining <= TimeSpan.Zero)
                    {
                        Console.WriteLine("Mất kết nối quá thời gian ân hạn — server đã coi suất chơi là hết hạn. Mở lại launcher khi có mạng.");
                        return 3;
                    }

                    Console.WriteLine($"Mất kết nối tới server: {ex.Message} — thử lại sau {RetryDelay.TotalSeconds:0} giây " +
                                      $"(suất chơi còn khoảng {lease.Remaining.TotalSeconds:0} giây).");
                    delay = RetryDelay;
                }
                catch (ServerException ex)
                {
                    Console.WriteLine($"Server từ chối heartbeat: {ex.Message}");
                    return 3;
                }
            }
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested)
        {
            // Quitting on purpose: hand the lease back now so the server drops the whitelist without waiting.
            try
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                await client.EndSessionAsync(
                    new SessionEndRequest(lease.SessionId, lease.Token, shutdown.Reason ?? "launcher-stopped"), timeout.Token);
                Console.WriteLine("Đã trả suất chơi.");
            }
            catch
            {
                Console.WriteLine("Không báo được server — suất chơi sẽ tự hết hạn sau thời gian ân hạn.");
            }

            return 0;
        }
    }

    /// <summary>Worth retrying: network failures, timeouts and 5xx answers.</summary>
    private static bool IsTransient(Exception ex) =>
        ex is HttpRequestException or TaskCanceledException
        || ex is ServerException { Status: >= HttpStatusCode.InternalServerError };

    private static void LaunchGame(Policy policy)
    {
        if (string.IsNullOrWhiteSpace(policy.LaunchUri))
        {
            Console.WriteLine("Server chưa cấu hình launchUri — hãy tự mở game.");
            return;
        }

        try
        {
            Process.Start(new ProcessStartInfo(policy.LaunchUri) { UseShellExecute = true });
            Console.WriteLine($"Đang mở game: {policy.LaunchUri}");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Không mở được game: {ex.Message}");
        }
    }
}

/// <summary>
/// The lease being held. Time left is computed on the server's clock (ExpiresUtc − ServerTime) and then counted
/// down with a Stopwatch, so a wrong clock on the player's PC changes nothing.
/// </summary>
internal sealed class HeldLease(string sessionId, string token, TimeSpan heartbeat)
{
    private readonly Stopwatch _sinceRenewal = new();
    private TimeSpan _validFor;

    public string SessionId { get; } = sessionId;
    public string Token { get; } = token;
    public TimeSpan Heartbeat { get; } = heartbeat;

    /// <summary>Estimated time until the server expires the lease; negative once past.</summary>
    public TimeSpan Remaining => _validFor - _sinceRenewal.Elapsed;

    public void Renew(DateTimeOffset? expiresUtc, DateTimeOffset? serverTime)
    {
        // Servers that send no server time: assume two heartbeat periods.
        _validFor = expiresUtc is { } expires && serverTime is { } now ? expires - now : Heartbeat * 2;
        _sinceRenewal.Restart();
    }
}
