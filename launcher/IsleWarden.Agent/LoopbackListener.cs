using System.Net;
using System.Net.Sockets;
using System.Text;

namespace IsleWarden.Agent;

/// <summary>
/// Receives the browser's redirect at the end of the login (RFC 8252 loopback redirect). A raw TcpListener on
/// 127.0.0.1: no URL reservation or admin rights needed, no firewall prompt, and nothing outside this machine
/// can reach it.
/// </summary>
internal sealed class LoopbackListener : IDisposable
{
    private readonly TcpListener _listener;

    private LoopbackListener(TcpListener listener)
    {
        _listener = listener;
        Port = ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    public int Port { get; }

    public static LoopbackListener Start()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return new LoopbackListener(listener);
    }

    /// <summary>
    /// Waits for <c>GET /callback?code=..&amp;state=..</c> carrying our state. Connections are handled in parallel,
    /// so an idle browser pre-connect or a favicon request can't hold up the real redirect.
    /// </summary>
    public async Task<LoopbackCallback> WaitForCallbackAsync(string expectedState, CancellationToken ct)
    {
        var result = new TaskCompletionSource<LoopbackCallback>(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var cancel = ct.Register(() => result.TrySetCanceled(ct));

        _ = Task.Run(async () =>
        {
            while (!result.Task.IsCompleted)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync(ct);
                }
                catch
                {
                    return;
                }

                _ = HandleAsync(client, expectedState, result, ct);
            }
        }, CancellationToken.None);

        return await result.Task;
    }

    public void Dispose() => _listener.Stop();

    private static async Task HandleAsync(TcpClient client, string expectedState,
        TaskCompletionSource<LoopbackCallback> result, CancellationToken ct)
    {
        var handedOver = false;
        try
        {
            using var readTimeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            readTimeout.CancelAfter(TimeSpan.FromSeconds(10));

            var target = await ReadRequestTargetAsync(client.GetStream(), readTimeout.Token);
            var query = target is not null && target.StartsWith("/callback?", StringComparison.Ordinal)
                ? ParseQuery(target["/callback?".Length..])
                : null;

            if (query is null)
            {
                await LoopbackCallback.WriteAsync(client, 404, "", ct);
                return;
            }

            if (query.GetValueOrDefault("state") != expectedState || query.GetValueOrDefault("code") is not { Length: > 0 } code)
            {
                await LoopbackCallback.WriteAsync(client, 400,
                    LoginPages.Failed("Liên kết đăng nhập không khớp với launcher đang chạy. Hãy chạy lại lệnh login."), ct);
                return;
            }

            handedOver = result.TrySetResult(new LoopbackCallback(client, code));
            if (!handedOver)
                await LoopbackCallback.WriteAsync(client, 409, LoginPages.Failed("Lượt đăng nhập này đã được xử lý."), ct);
        }
        catch
        {
            // A browser that disconnects or never sends a request is simply dropped.
        }
        finally
        {
            if (!handedOver)
                client.Dispose();
        }
    }

    /// <summary>The request target of the first line ("GET /callback?... HTTP/1.1"); null if it isn't a GET.</summary>
    private static async Task<string?> ReadRequestTargetAsync(NetworkStream stream, CancellationToken ct)
    {
        var buffer = new byte[8192];
        var length = 0;
        while (length < buffer.Length)
        {
            var read = await stream.ReadAsync(buffer.AsMemory(length), ct);
            if (read == 0)
                break;
            length += read;
            if (Encoding.ASCII.GetString(buffer, 0, length).Contains("\r\n", StringComparison.Ordinal))
                break;
        }

        var firstLine = Encoding.ASCII.GetString(buffer, 0, length).Split("\r\n")[0].Split(' ');
        return firstLine is ["GET", var target, ..] ? target : null;
    }

    private static Dictionary<string, string> ParseQuery(string query) =>
        query.Split('&', StringSplitOptions.RemoveEmptyEntries)
            .Select(pair => pair.Split('=', 2))
            .GroupBy(parts => Uri.UnescapeDataString(parts[0]))
            .ToDictionary(g => g.Key, g => Uri.UnescapeDataString(g.First().ElementAtOrDefault(1) ?? ""));
}

/// <summary>The browser request that carried the login code; the browser waits until we answer it.</summary>
internal sealed class LoopbackCallback(TcpClient client, string code) : IAsyncDisposable
{
    private bool _answered;

    public string Code { get; } = code;

    /// <summary>Shows the result in the browser tab and closes the connection.</summary>
    public async Task RespondAsync(string html)
    {
        _answered = true;
        try
        {
            await WriteAsync(client, 200, html, CancellationToken.None);
        }
        catch (IOException)
        {
            // The tab was closed; the launcher window shows the result anyway.
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (!_answered)
            await RespondAsync(LoginPages.Failed("Launcher đã dừng trước khi đăng nhập xong."));
        client.Dispose();
    }

    public static async Task WriteAsync(TcpClient client, int status, string html, CancellationToken ct)
    {
        var body = Encoding.UTF8.GetBytes(html);
        var reason = status switch { 200 => "OK", 400 => "Bad Request", 404 => "Not Found", _ => "Conflict" };
        var head = Encoding.ASCII.GetBytes(
            $"HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {body.Length}\r\n" +
            "Cache-Control: no-store\r\nConnection: close\r\n\r\n");

        var stream = client.GetStream();
        await stream.WriteAsync(head, ct);
        await stream.WriteAsync(body, ct);
        await stream.FlushAsync(ct);
    }
}

/// <summary>The page the browser shows at the end of the login. Player-facing, so Vietnamese.</summary>
internal static class LoginPages
{
    public static string Succeeded(string steamId, string? discordName) => Page("#39b3c6", "Đăng nhập thành công",
        $"Steam ID: {WebUtility.HtmlEncode(steamId)}"
        + (discordName is null ? "" : $"<br>Discord: {WebUtility.HtmlEncode(discordName)}")
        + "<br><br>Bạn có thể đóng tab này và quay lại launcher.");

    public static string Failed(string message) =>
        Page("#e58", "Không đăng nhập được", WebUtility.HtmlEncode(message));

    private static string Page(string color, string title, string bodyHtml) =>
        $$"""
          <!DOCTYPE html>
          <html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{{title}}</title>
          <style>body{font-family:"Segoe UI",system-ui,sans-serif;background:#0f1720;color:#e7eef5;display:grid;place-items:center;min-height:90vh;margin:0}
          main{max-width:520px;padding:24px 28px;background:#18232f;border:1px solid #294050;border-radius:12px}h1{font-size:19px;margin:0 0 10px;color:{{color}};}</style>
          </head><body><main><h1>{{title}}</h1><p>{{bodyHtml}}</p></main></body></html>
          """;
}
