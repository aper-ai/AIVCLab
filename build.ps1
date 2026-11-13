[CmdletBinding()]
param(
    [string]$Python,
    [string]$Iscc
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$appVersion = '0.1.0'
$executableName = 'AperVirtualCellWorkbench'
$projectPath = $PSScriptRoot
$workspacePath = Split-Path -Parent $projectPath
$appPath = Join-Path $projectPath 'app.py'
$samplePath = Join-Path $projectPath 'samples'
$buildPath = Join-Path $projectPath 'build'
$bundlePath = Join-Path $buildPath 'bundle'
$distPath = Join-Path $projectPath 'dist'
$installerDefinition = Join-Path $projectPath 'installer\Workbench.iss'
$iconPath = Join-Path $projectPath 'installer\aper-workbench.ico'
$installerName = "AperAI-VirtualCell-Workbench-Setup-$appVersion-x64.exe"

if (-not $Python) {
    $Python = @(
        (Join-Path $projectPath '.venv\Scripts\python.exe')
        (Join-Path $workspacePath '.venv\Scripts\python.exe')
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $Python) {
        $Python = 'python.exe'
    }
}
if (-not $Iscc) {
    $Iscc = 'ISCC.exe'
    if (-not (Get-Command -Name $Iscc -ErrorAction SilentlyContinue)) {
        $installRoots = @(
            (Join-Path $env:LOCALAPPDATA 'Programs')
            (Join-Path $env:USERPROFILE 'AppData\Local\Programs')
            ${env:ProgramFiles(x86)}
            $env:ProgramFiles
        )
        $Iscc = $installRoots |
            Where-Object { $_ } |
            ForEach-Object { Join-Path $_ 'Inno Setup 6\ISCC.exe' } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
    }
}
if (-not $Iscc -or -not (Get-Command -Name $Iscc -ErrorAction SilentlyContinue)) {
    throw 'Inno Setup 6 compiler not found. Specify its ISCC.exe with -Iscc.'
}
$pythonCommand = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python not found. Specify a Python interpreter with PyInstaller and PySide6 using -Python.'
}
$pythonExe = $pythonCommand.Source
if (-not (Test-Path -LiteralPath $appPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $samplePath -PathType Container)) {
    throw 'Build input is incomplete. app.py and samples/ must exist in the workbench project.'
}

if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw 'Build input is incomplete. installer/aper-workbench.ico must exist in the workbench project.'
}

New-Item -ItemType Directory -Path $buildPath, $distPath -Force | Out-Null
$freezeArgs = @(
    '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir', '--windowed',
    '--name', $executableName,
    '--distpath', $bundlePath,
    '--workpath', (Join-Path $buildPath 'pyinstaller'),
    '--specpath', $buildPath,
    '--add-data', "${samplePath}:samples",
    '--add-data', "${iconPath}:installer",
    '--icon', $iconPath
)

$previousCachePath = $env:PYINSTALLER_CONFIG_DIR
$previousPath = $env:Path
$previousPythonPath = $env:PYTHONPATH
Push-Location -LiteralPath $projectPath
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $buildPath 'cache'
    # PyInstaller scans PATH for DLLs. Qt uses Windows ICU, which must not be shadowed by another application's ICU.
    $env:Path = @(
        (Join-Path $env:SystemRoot 'System32')
        $env:SystemRoot
        (Split-Path -Parent $pythonExe)
    ) -join [IO.Path]::PathSeparator
    $env:PYTHONPATH = $null
    & $pythonExe -c 'import sys, sysconfig; import PyInstaller; from PySide6 import QtWidgets; sys.exit(0 if sysconfig.get_platform().lower() == ''win-amd64'' else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'The installer needs x64 Python with PyInstaller and PySide6 available.'
    }
    & $pythonExe @freezeArgs $appPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    $env:PYINSTALLER_CONFIG_DIR = $previousCachePath
    $env:Path = $previousPath
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}

$payloadPath = Join-Path $bundlePath $executableName
$frozenExe = Join-Path $payloadPath "$executableName.exe"
$frozenSamples = Join-Path $payloadPath '_internal\samples'
$frozenIcon = Join-Path $payloadPath '_internal\installer\aper-workbench.ico'
if (-not (Test-Path -LiteralPath $frozenExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $frozenSamples -PathType Container) -or
    -not (Test-Path -LiteralPath $frozenIcon -PathType Leaf)) {
    throw 'The executable bundle is missing the program, the bundled samples, or the branded icon.'
}
if (Test-Path -LiteralPath (Join-Path $payloadPath '_internal\icuuc.dll') -PathType Leaf) {
    throw 'The executable bundle contains a private copy of the Windows ICU library (icuuc.dll).'
}

$compileArgs = @(
    '/Qp',
    "/DWorkbenchPayload=$payloadPath",
    "/DWorkbenchOutput=$distPath",
    "/DWorkbenchVersion=$appVersion",
    "/DWorkbenchIcon=$iconPath"
)
$translationsPath = Join-Path $projectPath 'installer\languages'
$chineseMessages = Join-Path $translationsPath 'ChineseSimplified.isl'
$translationLicense = Join-Path $translationsPath 'LICENSE'
if ((Test-Path -LiteralPath $chineseMessages -PathType Leaf) -and
    (Test-Path -LiteralPath $translationLicense -PathType Leaf)) {
    $compileArgs += @(
        "/DChineseMessages=$chineseMessages",
        "/DTranslationLicense=$translationLicense"
    )
}

& $Iscc @compileArgs $installerDefinition
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
}

$installerPath = Join-Path $distPath $installerName
Get-Item -LiteralPath $installerPath
