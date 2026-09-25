using IsleWarden.Core;

namespace IsleWarden.Agent;

/// <summary>Prints this machine's fingerprint so admins and players can inspect it. This command sends nothing.</summary>
internal static class FingerprintCommand
{
    public static int Run(string[] args)
    {
        var raw = new CommandLine(args).Has("--raw");
        var fingerprint = new DeviceFingerprintCollector().Collect();

        Console.WriteLine("Fingerprint máy này (các nguồn đọc được):");
        if (fingerprint.Components.Count == 0)
        {
            Console.WriteLine("  (không đọc được nguồn nào — máy ảo hoặc thiếu quyền)");
        }
        else
        {
            foreach (var (key, value) in fingerprint.Components)
                Console.WriteLine(raw ? $"  {key,-16} = {value}" : $"  {key,-16} = {Mask(value)}");
        }

        Console.WriteLine();
        Console.WriteLine($"DeviceId (SHA-256 các nguồn): {fingerprint.DeviceId}");
        Console.WriteLine();
        Console.WriteLine("Lưu ý: server chỉ nhận DeviceId và hash từng nguồn (kèm pepper), KHÔNG nhận serial thô.");
        if (!raw)
            Console.WriteLine("Dùng --raw để xem giá trị đầy đủ (chỉ hiện trên máy bạn).");
        return 0;
    }

    /// <summary>Masks raw values in the default output so shared screenshots don't leak serial numbers.</summary>
    private static string Mask(string value)
    {
        if (value.Length <= 4)
            return new string('•', value.Length);
        return value[..2] + new string('•', Math.Min(8, value.Length - 4)) + value[^2..];
    }
}
