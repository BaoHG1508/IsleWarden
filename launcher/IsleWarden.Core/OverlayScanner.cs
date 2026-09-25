using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;

namespace IsleWarden.Core;

/// <summary>
/// Overlay scan settings. Kept out of <see cref="Policy"/> because <see cref="OverlayScanner"/> is not yet
/// wired into Scanner; when it is, move this rule into Policy and its finding codes into <c>FindingCodes</c>.
/// </summary>
public sealed record OverlayScanRule
{
    public bool Enabled { get; init; }
    public Severity Severity { get; init; } = Severity.Medium;

    /// <summary>Processes whose overlays are allowed, with or without ".exe", e.g. steam, discord, obs64.</summary>
    public List<string> AllowedProcesses { get; init; } = new();

    /// <summary>Fraction of the game window's area (0 to 1) a window must cover to count as drawing over the game.</summary>
    public double MinOverlapFraction { get; init; } = 0.15;

    /// <summary>Only consider windows with the topmost, layered or transparent extended style, typical of overlays.</summary>
    public bool RequireTopmostOrLayered { get; init; } = true;
}

/// <summary>
/// Detects foreign overlays: top-level windows of processes other than the game that cover the game
/// window and have the topmost/layered/transparent styles typical of overlays. Only window-based overlays
/// are caught; overlays drawn through DirectX hooks are not windows and are left to <see cref="ModuleScanner"/>.
/// </summary>
/// <remarks>
/// Prone to false positives (Steam, Discord, IMEs and screen recorders all use legitimate overlays), so it
/// is off by default; run it in Observe mode with an allowlist before enforcing.
/// </remarks>
public sealed class OverlayScanner
{
    // Windows system and shell processes are always ignored to reduce false positives.
    private static readonly HashSet<string> SystemProcesses = new(StringComparer.OrdinalIgnoreCase)
    {
        "explorer", "dwm", "textinputhost", "applicationframehost", "shellexperiencehost",
        "searchhost", "searchapp", "startmenuexperiencehost", "ctfmon", "systemsettings",
        "lockapp", "peopleexperiencehost", "widgets", "nvcontainer"
    };

    private const int GwlExStyle = -20;
    private const long WsExTopmost = 0x00000008;
    private const long WsExTransparent = 0x00000020;
    private const long WsExLayered = 0x00080000;

    private readonly IProcessSource _processes;

    public OverlayScanner() : this(new SystemProcessSource())
    {
    }

    public OverlayScanner(IProcessSource processes) => _processes = processes;

    public IEnumerable<Finding> Scan(OverlayScanRule rule, string? gameProcessName)
    {
        if (rule is not { Enabled: true } || string.IsNullOrWhiteSpace(gameProcessName))
            return [];

        if (!OperatingSystem.IsWindows())
            return [new Finding("overlay-scan-unavailable", Severity.Info,
                "Quét overlay chỉ chạy trên Windows.")];

        return ScanWindows(rule, gameProcessName);
    }

    [SupportedOSPlatform("windows")]
    private List<Finding> ScanWindows(OverlayScanRule rule, string gameProcessName)
    {
        var findings = new List<Finding>();

        var pidToName = _processes.GetProcesses()
            .GroupBy(p => p.Id)
            .ToDictionary(g => g.Key, g => ProcessScanner.NormalizeName(g.First().Name));

        var gameName = ProcessScanner.NormalizeName(gameProcessName);
        var allowed = new HashSet<string>(
            rule.AllowedProcesses.Select(ProcessScanner.NormalizeName), StringComparer.OrdinalIgnoreCase);

        var windows = EnumerateTopLevelWindows();

        // The game window is the largest visible window owned by the game process.
        var gameWindow = windows
            .Where(w => pidToName.GetValueOrDefault(w.Pid) == gameName && Area(w.Rect) > 0)
            .OrderByDescending(w => Area(w.Rect))
            .FirstOrDefault();

        if (gameWindow.Handle == IntPtr.Zero)
            return findings; // Game not running or has no window yet: no conclusion.

        var gameArea = Area(gameWindow.Rect);

        foreach (var w in windows)
        {
            if (w.Handle == gameWindow.Handle || Area(w.Rect) <= 0)
                continue;

            var name = pidToName.GetValueOrDefault(w.Pid);
            if (name == gameName || (name is not null && (allowed.Contains(name) || SystemProcesses.Contains(name))))
                continue;

            var isOverlayStyle = (w.ExStyle & (WsExTopmost | WsExLayered | WsExTransparent)) != 0;
            if (rule.RequireTopmostOrLayered && !isOverlayStyle)
                continue;

            var overlap = OverlapFraction(gameWindow.Rect, w.Rect, gameArea);
            if (overlap < rule.MinOverlapFraction)
                continue;

            var owner = name ?? $"pid {w.Pid}";
            var title = string.IsNullOrWhiteSpace(w.Title) ? "(không tiêu đề)" : w.Title;
            var flags = DescribeStyle(w.ExStyle);

            findings.Add(new Finding("foreign-overlay", rule.Severity,
                $"Cửa sổ lạ đang phủ lên game: {owner}",
                $"title=\"{title}\"; phủ {overlap:P0}; {flags}"));
        }

        return findings;
    }

    private static string DescribeStyle(long exStyle)
    {
        var parts = new List<string>();
        if ((exStyle & WsExTopmost) != 0) parts.Add("topmost");
        if ((exStyle & WsExLayered) != 0) parts.Add("layered");
        if ((exStyle & WsExTransparent) != 0) parts.Add("click-through");
        return parts.Count == 0 ? "style=-" : string.Join("+", parts);
    }

    private static long Area(Rect r) => Math.Max(0L, (long)(r.Right - r.Left)) * Math.Max(0L, (r.Bottom - r.Top));

    private static double OverlapFraction(Rect game, Rect other, long gameArea)
    {
        if (gameArea <= 0) return 0;
        var left = Math.Max(game.Left, other.Left);
        var top = Math.Max(game.Top, other.Top);
        var right = Math.Min(game.Right, other.Right);
        var bottom = Math.Min(game.Bottom, other.Bottom);
        if (right <= left || bottom <= top) return 0;
        var inter = (long)(right - left) * (bottom - top);
        return (double)inter / gameArea;
    }

    [SupportedOSPlatform("windows")]
    private List<WindowInfo> EnumerateTopLevelWindows()
    {
        var result = new List<WindowInfo>();

        EnumWindows((hWnd, _) =>
        {
            if (!IsWindowVisible(hWnd))
                return true;

            if (!GetWindowRect(hWnd, out var rect))
                return true;

            GetWindowThreadProcessId(hWnd, out var pid);
            var exStyle = (long)GetWindowLongPtrW(hWnd, GwlExStyle);

            result.Add(new WindowInfo(hWnd, (int)pid, rect, exStyle, GetTitle(hWnd)));
            return true;
        }, IntPtr.Zero);

        return result;
    }

    [SupportedOSPlatform("windows")]
    private static string GetTitle(IntPtr hWnd)
    {
        var length = GetWindowTextLengthW(hWnd);
        if (length <= 0)
            return string.Empty;

        var sb = new StringBuilder(length + 1);
        GetWindowTextW(hWnd, sb, sb.Capacity);
        return sb.ToString();
    }

    private readonly record struct WindowInfo(IntPtr Handle, int Pid, Rect Rect, long ExStyle, string Title);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetWindowRect(IntPtr hWnd, out Rect lpRect);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtrW(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowTextLengthW(IntPtr hWnd);
}
