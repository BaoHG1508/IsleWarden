namespace IsleWarden.Agent;

/// <summary>Minimal argument parser: positional arguments, flags (--once) and options that take a value (--server URL).</summary>
internal sealed class CommandLine
{
    private readonly Dictionary<string, string?> _options = new(StringComparer.OrdinalIgnoreCase);

    public CommandLine(IEnumerable<string> args, params string[] valueOptions)
    {
        var withValue = new HashSet<string>(valueOptions, StringComparer.OrdinalIgnoreCase);
        using var e = args.GetEnumerator();
        while (e.MoveNext())
        {
            var arg = e.Current;
            if (!arg.StartsWith("--", StringComparison.Ordinal))
            {
                Positional.Add(arg);
                continue;
            }

            var eq = arg.IndexOf('=');
            if (eq > 0)
                _options[arg[..eq]] = arg[(eq + 1)..];
            else
                _options[arg] = withValue.Contains(arg) && e.MoveNext() ? e.Current : null;
        }
    }

    public List<string> Positional { get; } = new();

    public bool Has(string name) => _options.ContainsKey(name);

    public string? Get(string name) => _options.GetValueOrDefault(name);
}
