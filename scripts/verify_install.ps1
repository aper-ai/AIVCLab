[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$Python = 'python.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Installation verification requires Windows.' }
$uninstallKey = '{7D5D4566-0C97-42D9-BCF4-A743A29DB94A}_is1'
foreach ($root in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
    if (Test-Path -LiteralPath (Join-Path $root $uninstallKey)) {
        throw 'Run installer verification in a clean Windows test environment. An existing Workbench installation must not be replaced.'
    }
}
$projectPath = Split-Path -Parent $PSScriptRoot
$output = Join-Path $projectPath 'verification\windows-install'
New-Item -ItemType Directory -Path $output -Force | Out-Null
# The registry guard above and a new disposable directory protect an existing copy.
$installPath = Join-Path ([IO.Path]::GetTempPath()) ("Aper AI test-" + [guid]::NewGuid().ToString('N'))
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$evidenceScript = Join-Path $PSScriptRoot 'build_evidence.py'
$installedExe = Join-Path $installPath 'AperVirtualCellWorkbench.exe'
$uninstaller = Join-Path $installPath 'unins000.exe'
$checks = [Collections.Generic.List[string]]::new()
$failure = ''

function Invoke-Waited([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -PassThru
    if (-not $process.WaitForExit(180000)) {
        $process.Kill()
        throw "Process timed out: $File"
    }
    if ($process.ExitCode -ne 0) { throw "Process failed ($($process.ExitCode)): $File" }
}

try {
    Invoke-Waited $installerPath @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', ('/DIR="{0}"' -f $installPath), ('/LOG="{0}"' -f (Join-Path $output 'install.log')))
    if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) { throw 'The installed executable is missing.' }
    if (-not (Test-Path -LiteralPath (Join-Path $installPath 'build-info.json') -PathType Leaf)) { throw 'Installed source provenance is missing.' }
    $checks.Add('Silent installation created the executable and build provenance.')
    $smokePath = Join-Path $output 'installed-smoke'
    $smokeResult = Join-Path $smokePath 'smoke-result.json'
    Remove-Item -LiteralPath $smokeResult -Force -ErrorAction SilentlyContinue
    Invoke-Waited $installedExe @('--smoke-test', ('"{0}"' -f $smokePath))
    & $Python $evidenceScript verify-smoke $smokeResult --packaged yes
    if ($LASTEXITCODE -ne 0) { throw 'The installed application did not produce passing smoke evidence.' }
    $checks.Add('Installed application passed the packaged desktop workflow checks.')
} catch {
    $failure = $_.Exception.Message
} finally {
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        try {
            Invoke-Waited $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="{0}"' -f (Join-Path $output 'uninstall.log')))
            if (Test-Path -LiteralPath $installedExe -PathType Leaf) { throw 'Uninstall left the application executable installed.' }
            $checks.Add('Silent uninstall removed the installed application executable.')
        } catch {
            $failure += " Uninstall: $($_.Exception.Message)"
        }
    } else {
        $failure += ' The test installation has no uninstaller.'
    }
    $result = @{
        passed = (-not $failure -and $checks.Count -eq 3)
        checks = $checks.ToArray()
        error = $failure
        installer_sha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        platform = [Environment]::OSVersion.VersionString
        timestamp = [DateTime]::UtcNow.ToString('o')
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'install-result.json') -Encoding utf8
}
if ($failure) { throw $failure }
