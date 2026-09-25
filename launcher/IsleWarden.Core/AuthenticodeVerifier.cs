using System.Runtime.InteropServices;
using System.Security.Cryptography.X509Certificates;

namespace IsleWarden.Core;

public enum SignatureStatus
{
    Valid,
    NotSigned,
    Invalid,
    Error
}

/// <param name="HResult">WinVerifyTrust return code (0 = valid).</param>
/// <param name="SignerSubject">Subject of the signing certificate; null if it could not be read.</param>
public sealed record SignatureResult(SignatureStatus Status, int HResult, string? SignerSubject, string Description);

/// <summary>
/// Full Authenticode verification via WinVerifyTrust: certificate chain to a trusted root, file integrity
/// and timestamp (a timestamped signature stays valid after the certificate expires).
/// Revocation is not checked online by default, to avoid slowing down the player's machine.
/// </summary>
public static class AuthenticodeVerifier
{
    private const int TrustENoSignature = unchecked((int)0x800B0100);
    private const int TrustESubjectFormUnknown = unchecked((int)0x800B0003);
    private const int TrustESubjectNotTrusted = unchecked((int)0x800B0004);
    private const int TrustEBadDigest = unchecked((int)0x80096010);
    private const int TrustEExplicitDistrust = unchecked((int)0x800B0111);
    private const int CertEExpired = unchecked((int)0x800B0101);
    private const int CertEUntrustedRoot = unchecked((int)0x800B0109);
    private const int CertEChaining = unchecked((int)0x800B010A);
    private const int CertERevoked = unchecked((int)0x800B010C);

    private const uint WtdUiNone = 2;
    private const uint WtdRevokeNone = 0;
    private const uint WtdRevokeWholeChain = 1;
    private const uint WtdChoiceFile = 1;
    private const uint WtdStateActionVerify = 1;
    private const uint WtdStateActionClose = 2;
    private const uint WtdRevocationCheckNone = 0x10;
    private const uint WtdRevocationCheckChainExcludeRoot = 0x80;
    private const uint WtdCacheOnlyUrlRetrieval = 0x1000;

    private static readonly Guid GenericVerifyV2 = new("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");

    public static SignatureResult Verify(string path, bool checkRevocation = false)
    {
        if (!OperatingSystem.IsWindows())
            return new SignatureResult(SignatureStatus.Error, 0, null, "Chỉ hỗ trợ kiểm tra chữ ký trên Windows.");

        if (!File.Exists(path))
            return new SignatureResult(SignatureStatus.Error, 0, null, "Không tìm thấy file.");

        var hr = WinVerify(Path.GetFullPath(path), checkRevocation);
        return hr switch
        {
            0 => new SignatureResult(SignatureStatus.Valid, hr, TryGetSignerSubject(path), "Chữ ký hợp lệ."),
            TrustENoSignature or TrustESubjectFormUnknown =>
                new SignatureResult(SignatureStatus.NotSigned, hr, null, Describe(hr)),
            TrustEBadDigest or TrustESubjectNotTrusted or TrustEExplicitDistrust or
                CertEExpired or CertEUntrustedRoot or CertEChaining or CertERevoked =>
                new SignatureResult(SignatureStatus.Invalid, hr, TryGetSignerSubject(path), Describe(hr)),
            _ => new SignatureResult(SignatureStatus.Error, hr, null, Describe(hr))
        };
    }

    /// <summary>Subject of the signing certificate embedded in the file; null if the file is unsigned or unreadable.</summary>
    public static string? TryGetSignerSubject(string path)
    {
        try
        {
#pragma warning disable SYSLIB0057 // .NET has no replacement API for reading the Authenticode certificate embedded in a PE file.
            using var certificate = X509Certificate.CreateFromSignedFile(path);
#pragma warning restore SYSLIB0057
            return certificate.Subject;
        }
        catch
        {
            return null;
        }
    }

    private static string Describe(int hr) => hr switch
    {
        TrustENoSignature => "File không có chữ ký số.",
        TrustESubjectFormUnknown => "Định dạng file không hỗ trợ chữ ký số.",
        TrustESubjectNotTrusted => "Chủ thể ký không được tin cậy.",
        TrustEBadDigest => "File đã bị sửa sau khi ký (hash không khớp chữ ký).",
        TrustEExplicitDistrust => "Chứng chỉ ký bị đánh dấu không tin cậy.",
        CertEExpired => "Chứng chỉ đã hết hạn và chữ ký không có dấu thời gian hợp lệ.",
        CertEUntrustedRoot => "Chứng chỉ gốc không được tin cậy.",
        CertEChaining => "Không dựng được chuỗi chứng chỉ tới gốc tin cậy.",
        CertERevoked => "Chứng chỉ ký đã bị thu hồi.",
        _ => $"WinVerifyTrust trả mã 0x{hr:X8}."
    };

    private static int WinVerify(string path, bool checkRevocation)
    {
        var pathPtr = Marshal.StringToHGlobalUni(path);
        var fileInfoPtr = IntPtr.Zero;
        try
        {
            var fileInfo = new WintrustFileInfo
            {
                cbStruct = (uint)Marshal.SizeOf<WintrustFileInfo>(),
                pcwszFilePath = pathPtr
            };
            fileInfoPtr = Marshal.AllocHGlobal(Marshal.SizeOf<WintrustFileInfo>());
            Marshal.StructureToPtr(fileInfo, fileInfoPtr, false);

            var data = new WintrustData
            {
                cbStruct = (uint)Marshal.SizeOf<WintrustData>(),
                dwUIChoice = WtdUiNone,
                fdwRevocationChecks = checkRevocation ? WtdRevokeWholeChain : WtdRevokeNone,
                dwUnionChoice = WtdChoiceFile,
                pFile = fileInfoPtr,
                dwStateAction = WtdStateActionVerify,
                dwProvFlags = checkRevocation
                    ? WtdRevocationCheckChainExcludeRoot
                    : WtdRevocationCheckNone | WtdCacheOnlyUrlRetrieval
            };

            var action = GenericVerifyV2;
            var hr = WinVerifyTrust(IntPtr.Zero, ref action, ref data);

            // Release the state WinVerifyTrust keeps after WTD_STATEACTION_VERIFY.
            data.dwStateAction = WtdStateActionClose;
            WinVerifyTrust(IntPtr.Zero, ref action, ref data);
            return hr;
        }
        finally
        {
            if (fileInfoPtr != IntPtr.Zero)
                Marshal.FreeHGlobal(fileInfoPtr);
            Marshal.FreeHGlobal(pathPtr);
        }
    }

    [DllImport("wintrust.dll", ExactSpelling = true)]
    private static extern int WinVerifyTrust(IntPtr hwnd, ref Guid actionId, ref WintrustData data);

    [StructLayout(LayoutKind.Sequential)]
    private struct WintrustFileInfo
    {
        public uint cbStruct;
        public IntPtr pcwszFilePath;
        public IntPtr hFile;
        public IntPtr pgKnownSubject;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WintrustData
    {
        public uint cbStruct;
        public IntPtr pPolicyCallbackData;
        public IntPtr pSIPClientData;
        public uint dwUIChoice;
        public uint fdwRevocationChecks;
        public uint dwUnionChoice;
        public IntPtr pFile;
        public uint dwStateAction;
        public IntPtr hWVTStateData;
        public IntPtr pwszURLReference;
        public uint dwProvFlags;
        public uint dwUIContext;
        public IntPtr pSignatureSettings;
    }
}
