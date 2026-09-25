<#
    Package an IsleWarden release.
      - Agent (player launcher): single self-contained .exe for Windows x64 (no .NET install needed).
      - Server: the Python server from server\ (the host needs Python 3.10+; see server\README.md).
    Output goes to .\dist
    (ASCII-only on purpose so Windows PowerShell 5.1 parses it regardless of file encoding.)
#>
[CmdletBinding()]
param(
    [string]$Runtime = "win-x64",
    [switch]$SkipAdminUi,                           # skip the React build (build machines without Node)
    [string]$Output = "dist",
    # Code-signing (optional). Provide your own certificate; nothing is signed if omitted.
    [string]$CertPath,                              # path to .pfx
    [string]$CertPassword,                          # .pfx password
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$dist = Join-Path $root $Output
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dist | Out-Null

Write-Host "== Agent (player launcher) -- $Runtime, self-contained, single file ==" -ForegroundColor Cyan
dotnet publish (Join-Path $root "launcher\IsleWarden.Agent\IsleWarden.Agent.csproj") `
    -c Release -r $Runtime --self-contained true `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=none `
    -o (Join-Path $dist "agent")
if ($LASTEXITCODE -ne 0) { throw "Agent publish failed." }

# Admin dashboard (React + Vite). Vite writes into server\islewarden_server\static\admin, so this
# must run BEFORE the server is copied -- otherwise the package ships a stale dashboard.
# Skip with -SkipAdminUi if Node is not installed on the build machine (the last build stays).
$adminUi = Join-Path $root "dashboard"
if ($SkipAdminUi) {
    Write-Host "== Admin dashboard -- skipped (-SkipAdminUi) ==" -ForegroundColor DarkYellow
} elseif (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Install Node.js LTS, or pass -SkipAdminUi to package the dashboard already in server\islewarden_server\static\admin."
} else {
    Write-Host "== Admin dashboard (React + Vite) ==" -ForegroundColor Cyan
    Push-Location $adminUi
    try {
        if (Test-Path (Join-Path $adminUi "package-lock.json")) { npm ci } else { npm install }
        if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Admin dashboard build failed." }
    }
    finally { Pop-Location }
}

Write-Host "== Server (Python) ==" -ForegroundColor Cyan
# What a host needs to run it. The virtual environment, tests, caches, local data and the development
# settings (which contain a well-known admin key) stay behind.
$serverOut = Join-Path $dist "server"
robocopy (Join-Path $root "server") $serverOut /E /NFL /NDL /NJH /NJS /NP `
    /XD .venv tests data __pycache__ .pytest_cache build *.egg-info `
    /XF appsettings.Development.json server-policy.json requirements-dev.txt *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the server failed (robocopy exit code $LASTEXITCODE)." }
$global:LASTEXITCODE = 0   # robocopy returns 1-7 on success

# Ship sample config files for the admin to edit.
Copy-Item (Join-Path $root "config\server-policy.example.json") (Join-Path $serverOut "server-policy.json") -Force
Copy-Item (Join-Path $root "config\policy.example.json") (Join-Path $dist "agent\policy.json") -Force

# Optional: code-sign the Agent .exe so players trust it and Windows SmartScreen stops warning.
$agentExePath = Join-Path $dist "agent\IsleWarden.Agent.exe"
if ($CertPath) {
    if (-not (Test-Path $CertPath)) { throw "Certificate not found: $CertPath" }
    $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signtool) {
        $found = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        $signtool = $found.FullName
    }
    if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)." }
    Write-Host "== Signing Agent ==" -ForegroundColor Cyan
    $signArgs = @("sign", "/fd", "SHA256", "/f", $CertPath, "/tr", $TimestampUrl, "/td", "SHA256")
    if ($CertPassword) { $signArgs += @("/p", $CertPassword) }
    $signArgs += $agentExePath
    & $signtool @signArgs
    if ($LASTEXITCODE -ne 0) { throw "Signing failed." }
    & $signtool verify /pa $agentExePath
}

Write-Host ""
Write-Host "Done. Output in $dist" -ForegroundColor Green
$agentExe = Get-ChildItem (Join-Path $dist "agent") -Filter "IsleWarden.Agent.exe" -ErrorAction SilentlyContinue
if ($agentExe) {
    $sizeMb = [math]::Round($agentExe.Length / 1MB, 0)
    Write-Host ("  Agent : " + $agentExe.FullName + " (" + $sizeMb + " MB)")
}
Write-Host ("  Server: " + $serverOut + " (on the host: pip install -r requirements.txt, then python -m islewarden_server; see README.md there)")
Write-Host ""
Write-Host "Reminder: code-sign the Agent .exe before release so players trust it and SmartScreen warnings drop." -ForegroundColor Yellow
