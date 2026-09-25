using System.Text;

namespace IsleWarden.Core;

/// <summary>A node in a Valve KeyValues file (.vdf/.acf): either a string value or a set of children.</summary>
public sealed class VdfNode
{
    private readonly Dictionary<string, VdfNode> _children = new(StringComparer.OrdinalIgnoreCase);

    public VdfNode(string? value = null) => Value = value;

    public string? Value { get; }
    public IReadOnlyDictionary<string, VdfNode> Children => _children;
    public VdfNode? this[string key] => _children.GetValueOrDefault(key);

    public string? GetString(string key) => this[key]?.Value;

    internal void Add(string key, VdfNode node) => _children[key] = node;
}

/// <summary>Parses Steam's text KeyValues format (libraryfolders.vdf, appmanifest_*.acf).</summary>
public static class VdfParser
{
    private enum TokenKind
    {
        String,
        Open,
        Close
    }

    private readonly record struct Token(TokenKind Kind, string Text);

    public static VdfNode Parse(string text)
    {
        var tokens = Tokenize(text);
        var index = 0;
        var root = new VdfNode();
        ParseObject(tokens, ref index, root, expectClose: false);
        return root;
    }

    private static void ParseObject(List<Token> tokens, ref int index, VdfNode target, bool expectClose)
    {
        while (index < tokens.Count)
        {
            var key = tokens[index++];
            if (key.Kind == TokenKind.Close)
            {
                if (expectClose)
                    return;
                continue; // Ignore a stray } at the root.
            }

            if (key.Kind != TokenKind.String || index >= tokens.Count)
                continue;

            var next = tokens[index++];
            switch (next.Kind)
            {
                case TokenKind.Open:
                    var child = new VdfNode();
                    ParseObject(tokens, ref index, child, expectClose: true);
                    target.Add(key.Text, child);
                    break;
                case TokenKind.String:
                    target.Add(key.Text, new VdfNode(next.Text));
                    break;
                case TokenKind.Close when expectClose:
                    return; // Key without a value just before the closing brace.
            }
        }
    }

    private static List<Token> Tokenize(string text)
    {
        var tokens = new List<Token>();
        var i = 0;
        while (i < text.Length)
        {
            var c = text[i];
            if (char.IsWhiteSpace(c))
            {
                i++;
                continue;
            }

            if (c == '/' && i + 1 < text.Length && text[i + 1] == '/')
            {
                while (i < text.Length && text[i] != '\n')
                    i++;
                continue;
            }

            if (c == '{')
            {
                tokens.Add(new Token(TokenKind.Open, "{"));
                i++;
                continue;
            }

            if (c == '}')
            {
                tokens.Add(new Token(TokenKind.Close, "}"));
                i++;
                continue;
            }

            if (c == '"')
            {
                i++;
                var sb = new StringBuilder();
                while (i < text.Length && text[i] != '"')
                {
                    if (text[i] == '\\' && i + 1 < text.Length)
                    {
                        var escaped = text[i + 1];
                        switch (escaped)
                        {
                            case 'n': sb.Append('\n'); break;
                            case 't': sb.Append('\t'); break;
                            case '\\': sb.Append('\\'); break;
                            case '"': sb.Append('"'); break;
                            default: sb.Append('\\').Append(escaped); break;
                        }

                        i += 2;
                        continue;
                    }

                    sb.Append(text[i++]);
                }

                i++; // Skip the closing quote.
                tokens.Add(new Token(TokenKind.String, sb.ToString()));
                continue;
            }

            // Unquoted string.
            var start = i;
            while (i < text.Length && !char.IsWhiteSpace(text[i]) && text[i] is not ('{' or '}' or '"'))
                i++;
            tokens.Add(new Token(TokenKind.String, text[start..i]));
        }

        return tokens;
    }
}
