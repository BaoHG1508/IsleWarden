using System.Net;
using System.Net.Http.Json;
using IsleWarden.Core;
using IsleWarden.Core.Protocol;

namespace IsleWarden.Agent;

internal sealed class ServerException(string message, HttpStatusCode status) : Exception(message)
{
    public HttpStatusCode Status { get; } = status;
}

internal sealed class ServerClient : IDisposable
{
    private readonly HttpClient _http;

    public ServerClient(string baseUrl)
    {
        _http = new HttpClient
        {
            BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"),
            Timeout = TimeSpan.FromSeconds(15)
        };
        _http.DefaultRequestHeaders.UserAgent.ParseAdd($"IsleWarden.Agent/{AgentInfo.Version}");
    }

    public Task<PolicyEnvelope> GetPolicyAsync(CancellationToken ct) =>
        GetAsync<PolicyEnvelope>("api/policy", ct);

    /// <summary>Downloads the baseline for this exact build; null if the server has none for it.</summary>
    public async Task<Baseline?> TryGetBaselineAsync(string buildId, CancellationToken ct)
    {
        using var response = await _http.GetAsync($"api/baselines/{Uri.EscapeDataString(buildId)}", ct);
        if (response.StatusCode == HttpStatusCode.NotFound)
            return null;

        await EnsureSuccessAsync(response, ct);
        return await response.Content.ReadFromJsonAsync<Baseline>(IsleWardenJson.Web, ct);
    }

    public Task<LoginResponse> CompleteLoginAsync(LoginCompleteRequest request, CancellationToken ct) =>
        PostAsync<LoginCompleteRequest, LoginResponse>("api/login/complete", request, ct);

    public Task<SessionStartResponse> StartSessionAsync(SessionStartRequest request, CancellationToken ct) =>
        PostAsync<SessionStartRequest, SessionStartResponse>("api/session/start", request, ct);

    public Task<HeartbeatResponse> HeartbeatAsync(HeartbeatRequest request, CancellationToken ct) =>
        PostAsync<HeartbeatRequest, HeartbeatResponse>("api/session/heartbeat", request, ct);

    public async Task EndSessionAsync(SessionEndRequest request, CancellationToken ct)
    {
        using var response = await _http.PostAsJsonAsync("api/session/end", request, IsleWardenJson.Web, ct);
        await EnsureSuccessAsync(response, ct);
    }

    public void Dispose() => _http.Dispose();

    private async Task<T> GetAsync<T>(string path, CancellationToken ct)
    {
        using var response = await _http.GetAsync(path, ct);
        await EnsureSuccessAsync(response, ct);
        return await response.Content.ReadFromJsonAsync<T>(IsleWardenJson.Web, ct)
               ?? throw new ServerException("Server trả dữ liệu rỗng.", response.StatusCode);
    }

    private async Task<TResponse> PostAsync<TRequest, TResponse>(string path, TRequest body, CancellationToken ct)
    {
        using var response = await _http.PostAsJsonAsync(path, body, IsleWardenJson.Web, ct);
        await EnsureSuccessAsync(response, ct);
        return await response.Content.ReadFromJsonAsync<TResponse>(IsleWardenJson.Web, ct)
               ?? throw new ServerException("Server trả dữ liệu rỗng.", response.StatusCode);
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response, CancellationToken ct)
    {
        if (response.IsSuccessStatusCode)
            return;

        string message;
        try
        {
            message = (await response.Content.ReadFromJsonAsync<ErrorResponse>(IsleWardenJson.Web, ct))?.Error
                      ?? response.ReasonPhrase ?? $"HTTP {(int)response.StatusCode}";
        }
        catch
        {
            message = response.ReasonPhrase ?? $"HTTP {(int)response.StatusCode}";
        }

        throw new ServerException(message, response.StatusCode);
    }
}
