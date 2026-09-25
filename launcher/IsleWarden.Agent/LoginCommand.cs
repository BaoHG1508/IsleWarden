using System.Diagnostics;
using IsleWarden.Core;
using IsleWarden.Core.Protocol;

namespace IsleWarden.Agent;

/// <summary>
/// Signs the player in with Steam and Discord in the browser, then stores the device key the server issues.
/// The flow is described in Core/Protocol/Login.cs.
/// </summary>
internal static class LoginCommand
{
    private static readonly TimeSpan BrowserTimeout = TimeSpan.FromMinutes(10);

    public static async Task<int> RunAsync(string[] args)
    {
        var cmd = new CommandLine(args, "--server");
        var server = (cmd.Get("--server") ?? AgentState.Load().ServerUrl)?.TrimEnd('/');
        if (string.IsNullOrWhiteSpace(server))
        {
            Console.Error.WriteLine("Cách dùng: IsleWarden.Agent login --server <URL> [--yes]");
            return 2;
        }

        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            stop.Cancel();
        };

        using var client = new ServerClient(server);
        using var browserWait = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
        try
        {
            var envelope = await client.GetPolicyAsync(stop.Token);
            if (!ConsoleUi.Consent(envelope, cmd.Has("--yes")))
            {
                Console.WriteLine("Bạn chưa đồng ý nên chưa đăng nhập.");
                return 1;
            }

            using var listener = LoopbackListener.Start();
            var verifier = Pkce.NewVerifier();
            var state = Pkce.NewVerifier();
            var url = $"{server}/login/start?port={listener.Port}&state={state}&challenge={Pkce.Challenge(verifier)}";

            Console.WriteLine("Đang mở trình duyệt: đăng nhập Steam, rồi Discord.");
            Console.WriteLine($"Nếu trình duyệt không tự mở, hãy mở liên kết này: {url}");
            OpenBrowser(url);

            browserWait.CancelAfter(BrowserTimeout);
            await using var callback = await listener.WaitForCallbackAsync(state, browserWait.Token);

            var consentVersion = envelope.Policy.DisclosureVersion;
            LoginResponse response;
            try
            {
                response = await client.CompleteLoginAsync(new LoginCompleteRequest(
                    callback.Code, verifier, Environment.MachineName, consentVersion,
                    new DeviceFingerprintCollector().Collect()), stop.Token);
            }
            catch (ServerException ex)
            {
                await callback.RespondAsync(LoginPages.Failed(ex.Message));
                Console.WriteLine($"Đăng nhập không thành công: {ex.Message}");
                return 1;
            }

            await callback.RespondAsync(LoginPages.Succeeded(response.SteamId, response.DiscordName));

            // A new key replaces the old one, so a lease saved by the previous login can't be resumed anyway.
            new AgentState
            {
                ServerUrl = server,
                DeviceId = response.DeviceId,
                SteamId = response.SteamId,
                ConsentVersion = consentVersion
            }.WithDeviceKey(response.DeviceKey).Save();

            Console.WriteLine(response.DiscordName is null
                ? $"Đã đăng nhập: Steam ID {response.SteamId}."
                : $"Đã đăng nhập: Steam ID {response.SteamId}, Discord {response.DiscordName}.");
            Console.WriteLine(response.Status switch
            {
                DeviceStatus.Approved => "Chạy 'IsleWarden.Agent play --launch' để vào server.",
                DeviceStatus.Pending => "Máy đang chờ admin duyệt. Sau khi được duyệt, chạy 'IsleWarden.Agent play --launch'.",
                _ => "Máy này đã bị admin từ chối. Liên hệ admin nếu bạn nghĩ đây là nhầm lẫn."
            });
            return response.Status == DeviceStatus.Rejected ? 1 : 0;
        }
        catch (OperationCanceledException) when (stop.IsCancellationRequested)
        {
            Console.WriteLine("Đã huỷ.");
            return 1;
        }
        catch (OperationCanceledException) when (browserWait.IsCancellationRequested)
        {
            Console.WriteLine($"Hết {BrowserTimeout.TotalMinutes:0} phút chờ đăng nhập trên trình duyệt. Hãy chạy lại lệnh login.");
            return 3;
        }
        catch (Exception ex) when (ex is ServerException or HttpRequestException or TaskCanceledException)
        {
            Console.Error.WriteLine($"Không kết nối được server: {ex.Message}");
            return 3;
        }
    }

    private static void OpenBrowser(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Không tự mở được trình duyệt ({ex.Message}).");
        }
    }
}
