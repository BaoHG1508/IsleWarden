using System.Text;
using IsleWarden.Agent;

// IsleWarden Agent: the player-side launcher.

Console.OutputEncoding = Encoding.UTF8;

return args switch
{
    ["scan", .. var rest] => await ScanCommand.RunAsync(rest),
    ["baseline", .. var rest] => BaselineCommand.Run(rest),
    ["login", .. var rest] => await LoginCommand.RunAsync(rest),
    ["play", .. var rest] => await PlayCommand.RunAsync(rest),
    ["fingerprint", .. var rest] => FingerprintCommand.Run(rest),
    ["help" or "--help" or "-h" or "/?"] => Usage(),
    _ => await ScanCommand.RunAsync(args)
};

static int Usage()
{
    Console.WriteLine($"IsleWarden Agent {AgentInfo.Version}");
    Console.WriteLine();
    Console.WriteLine("  scan [policy.json] [--once]                 Quét cục bộ theo policy, không cần server.");
    Console.WriteLine("  login [--server URL] [--yes]                Đăng nhập Steam + Discord trên trình duyệt, nhận khoá thiết bị.");
    Console.WriteLine("  play [--launch] [--yes] [--server URL]      Vào server: quét, xin quyền, gửi heartbeat khi chơi.");
    Console.WriteLine("  baseline [--game-dir DIR] [--out FILE]      (Admin) Sinh baseline hash cho bản game đang cài.");
    Console.WriteLine("           [--include \"*.exe;*.dll\"] [--exclude \"EasyAntiCheat\"] [--build-id ID]");
    Console.WriteLine("  fingerprint [--raw]                         Hiện fingerprint máy (che bớt; --raw xem đầy đủ).");
    return 0;
}
