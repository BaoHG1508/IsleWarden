using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace IsleWarden.Core;

/// <summary>JSON options shared by the Agent and the Server.</summary>
public static class IsleWardenJson
{
    /// <summary>HTTP protocol: camelCase, enums as strings, Vietnamese text left unescaped.</summary>
    public static JsonSerializerOptions Web { get; } =
        Configure(new JsonSerializerOptions(JsonSerializerDefaults.Web));

    /// <summary>Human-readable report output: indented, property names as declared (PascalCase).</summary>
    public static JsonSerializerOptions Pretty { get; } =
        Configure(new JsonSerializerOptions { WriteIndented = true });

    /// <summary>Files on disk, such as the policy and baseline.</summary>
    public static JsonSerializerOptions Config { get; } = Configure(new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        WriteIndented = true
    });

    /// <summary>Adds camelCase string enums and leaves non-ASCII text such as Vietnamese unescaped.</summary>
    public static JsonSerializerOptions Configure(JsonSerializerOptions options)
    {
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
        options.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping;
        return options;
    }

    public static Policy LoadPolicy(string path) =>
        JsonSerializer.Deserialize<Policy>(File.ReadAllText(path), Config)
        ?? throw new InvalidDataException("Nội dung policy rỗng.");

    public static Baseline LoadBaseline(string path) =>
        JsonSerializer.Deserialize<Baseline>(File.ReadAllText(path), Config)
        ?? throw new InvalidDataException("Nội dung baseline rỗng.");

    public static void SaveBaseline(Baseline baseline, string path) =>
        File.WriteAllText(path, JsonSerializer.Serialize(baseline, Config));
}
