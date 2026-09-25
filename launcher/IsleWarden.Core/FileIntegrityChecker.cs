namespace IsleWarden.Core;

/// <summary>
/// Checks protected files by SHA-256 hash and Authenticode signature
/// (full certificate chain and timestamp validation via WinVerifyTrust).
/// </summary>
public sealed class FileIntegrityChecker
{
    private readonly FileHashCache _hashes;

    public FileIntegrityChecker() : this(new FileHashCache())
    {
    }

    public FileIntegrityChecker(FileHashCache hashes) => _hashes = hashes;

    public IEnumerable<Finding> Scan(Policy policy) => Scan(policy, new ScanContext());

    public IEnumerable<Finding> Scan(Policy policy, ScanContext context)
    {
        foreach (var f in policy.ProtectedFiles)
        {
            var path = PathTemplate.Resolve(f.Path, context.GameDirectory);
            if (path is null)
                continue; // Game directory unknown: Scanner already reports game-not-found.

            if (!File.Exists(path))
            {
                yield return new Finding(FindingCodes.FileMissing, Severity.Medium,
                    $"Thiếu file cần bảo vệ: {path}");
                continue;
            }

            if (f.Sha256 is { Length: > 0 })
            {
                var hash = _hashes.TryGetSha256(path);
                if (hash is null)
                {
                    yield return new Finding(FindingCodes.FileUnreadable, Severity.Low,
                        $"Không đọc được file: {path}");
                }
                else if (!f.Sha256.Any(h => h.Equals(hash, StringComparison.OrdinalIgnoreCase)))
                {
                    yield return new Finding(FindingCodes.FileTampered, Severity.High,
                        $"File bị thay đổi (hash không khớp): {path}", $"sha256={hash}");
                }
            }

            if (f.RequireSignature && CheckSignature(path, f.ExpectedSigner) is { } signatureFinding)
                yield return signatureFinding;
        }
    }

    private static Finding? CheckSignature(string path, string? expectedSigner)
    {
        var result = AuthenticodeVerifier.Verify(path);
        return result.Status switch
        {
            SignatureStatus.NotSigned => new Finding(FindingCodes.UnsignedFile, Severity.High,
                $"File không có chữ ký số hợp lệ: {path}", result.Description),
            SignatureStatus.Invalid => new Finding(FindingCodes.InvalidSignature, Severity.High,
                $"Chữ ký số của file không hợp lệ: {path}", result.Description),
            SignatureStatus.Error => new Finding(FindingCodes.SignatureCheckFailed, Severity.Low,
                $"Không kiểm tra được chữ ký số: {path}", result.Description),
            _ when expectedSigner is not null &&
                   (result.SignerSubject is null ||
                    !result.SignerSubject.Contains(expectedSigner, StringComparison.OrdinalIgnoreCase))
                => new Finding(FindingCodes.WrongSigner, Severity.High,
                    $"File ký bởi bên không mong đợi: {path}", $"signer={result.SignerSubject}"),
            _ => null
        };
    }

    /// <summary>Computes the SHA-256 as uppercase hex; null if the file can't be read.</summary>
    public static string? TryComputeSha256(string path) => FileHashCache.ComputeSha256(path);

    /// <summary>Subject of the file's signing certificate; null if the file is unsigned or unreadable.</summary>
    public static string? TryGetSignerSubject(string path) => AuthenticodeVerifier.TryGetSignerSubject(path);
}
