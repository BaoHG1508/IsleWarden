using IsleWarden.Core;
using IsleWarden.Core.Protocol;

namespace IsleWarden.Agent;

/// <summary>Console output: the disclosure prompt, scan summaries, and the server's access decisions.</summary>
internal static class ConsoleUi
{
    /// <summary>Shows the disclosure and asks the player to agree.</summary>
    public static bool Consent(PolicyEnvelope envelope, bool assumeYes)
    {
        var policy = envelope.Policy;
        Console.WriteLine($"=== Thông báo cho người chơi (phiên bản {policy.DisclosureVersion}) ===");
        Console.WriteLine(string.IsNullOrWhiteSpace(policy.Disclosure) ? "(Server chưa cấu hình nội dung thông báo.)" : policy.Disclosure);
        if (!string.IsNullOrWhiteSpace(envelope.ConsentUrl))
            Console.WriteLine($"Chi tiết: {envelope.ConsentUrl}");
        Console.WriteLine();

        if (assumeYes)
        {
            Console.WriteLine("Đã đồng ý (--yes).");
            return true;
        }

        Console.Write("Bạn có đồng ý để launcher kiểm tra như trên không? (y/N): ");
        var answer = Console.ReadLine()?.Trim().ToLowerInvariant();
        return answer is "y" or "yes" or "co" or "có" or "dong y" or "đồng ý";
    }

    public static void PrintSummary(ScanReport report)
    {
        var time = report.TimestampUtc.ToLocalTime().ToString("HH:mm:ss");
        if (report.Findings.Count == 0)
        {
            Console.WriteLine($"[{time}] Quét: sạch.");
            return;
        }

        Console.WriteLine($"[{time}] Quét: {(report.Clean ? "sạch" : "CÓ PHÁT HIỆN")} ({report.Findings.Count} mục)");
        foreach (var f in report.Findings)
            Console.WriteLine($"    - [{f.Severity}] {f.Code}: {f.Message}");
    }

    /// <summary>Prints every gate the server evaluated, then the grant or exactly what blocked it.</summary>
    public static void PrintDecision(SessionStartResponse response)
    {
        foreach (var gate in response.Gates)
        {
            var note = gate.Note is null ? "" : $" — {gate.Note}";
            Console.WriteLine($"  {Mark(gate.Status),-11} {GateName(gate.Gate)}{note}");
        }

        if (response.Block is { } block)
            PrintBlock(block);
        else if (response.Decision == SessionDecision.Granted)
            Console.WriteLine("Đã được cấp suất chơi.");
        else
            Console.WriteLine(DescribeDecision(response)); // a server that predates per-gate codes
    }

    /// <summary>Why a held lease ended, as the server reported it.</summary>
    public static void PrintEnded(HeartbeatResponse response)
    {
        if (response.Block is { } block)
            PrintBlock(block);
        else
            Console.WriteLine($"Suất chơi đã kết thúc ({response.State}): {response.Message}");
    }

    public static void PrintBlock(AccessBlock block)
    {
        Console.WriteLine(block.Gate == AccessGate.Lease
            ? $"Suất chơi đã kết thúc: {block.Label}"
            : $"Bị chặn ở bước {GateName(block.Gate)}: {block.Label}");
        if (!string.IsNullOrWhiteSpace(block.Detail))
            Console.WriteLine($"  Chi tiết: {block.Detail}");
        if (block.Until is { } until)
            Console.WriteLine($"  Tới: {until.ToLocalTime():dd/MM/yyyy HH:mm}");
        if (block.SupportCode is not null)
            Console.WriteLine($"  Mã tra cứu (gửi admin khi khiếu nại): {block.SupportCode}");
        Console.WriteLine($"  Mã lỗi: {block.Code}");
    }

    public static string DescribeDecision(SessionStartResponse response) => response.Decision switch
    {
        SessionDecision.Granted => "Đã được cấp quyền vào server.",
        SessionDecision.PendingApproval => "Thiết bị đang chờ admin duyệt. Hãy thử lại sau khi được duyệt.",
        SessionDecision.ConsentRequired => "Nội dung thông báo đã thay đổi, cần đồng ý lại trước khi vào server.",
        SessionDecision.Banned => $"Tài khoản đang bị cấm: {response.Message}",
        _ => $"Server từ chối: {response.Message}"
    };

    private static string Mark(GateStatus status) => status switch
    {
        GateStatus.Passed => "[ok]",
        GateStatus.Bypassed => "[miễn trừ]",
        _ => "[CHẶN]"
    };

    private static string GateName(AccessGate gate) => gate switch
    {
        AccessGate.Device => "Thiết bị",
        AccessGate.Ban => "Lệnh cấm",
        AccessGate.Discord => "Discord",
        AccessGate.Consent => "Thông báo",
        AccessGate.AntiCheat => "Anti-cheat",
        _ => "Suất chơi"
    };
}
