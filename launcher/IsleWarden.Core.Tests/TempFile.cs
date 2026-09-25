namespace IsleWarden.Core.Tests;

internal sealed class TempFile : IDisposable
{
    public string Path { get; }

    private TempFile(string path) => Path = path;

    public static TempFile Create(string content)
    {
        var path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "iw-test-" + Guid.NewGuid().ToString("N") + ".bin");
        File.WriteAllText(path, content);
        return new TempFile(path);
    }

    public void Dispose()
    {
        try { File.Delete(Path); } catch { /* best-effort cleanup */ }
    }
}

internal sealed class TempDir : IDisposable
{
    public string Path { get; }

    public TempDir()
    {
        Path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "iw-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path);
    }

    public string Write(string relative, string content)
    {
        var full = System.IO.Path.Combine(Path, relative);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)!);
        File.WriteAllText(full, content);
        return full;
    }

    public string WriteBytes(string relative, byte[] content)
    {
        var full = System.IO.Path.Combine(Path, relative);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(full)!);
        File.WriteAllBytes(full, content);
        return full;
    }

    public void Dispose()
    {
        try { Directory.Delete(Path, recursive: true); } catch { /* best-effort cleanup */ }
    }
}
