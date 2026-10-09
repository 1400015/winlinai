# WinLinAI Installer Build Script (PowerShell)
# Builds the Windows installer (.exe) using Inno Setup
#
# Prerequisites:
#   - Python 3.12 installed
#   - Inno Setup 6 installed (https://jrsoftware.org/isinfo.php)
#   - PyInstaller (pip install pyinstaller)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File installer/build-installer.ps1
#   powershell -ExecutionPolicy Bypass -File installer/build-installer.ps1 -Clean

param(
    [switch]$Clean,
    [switch]$SkipExe,
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"

function Stop-InstallerBuild {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host $Message -ForegroundColor Red
    exit 1
}

# The frozen app lives under installer\pyinstaller. The wheel directory dist\
# and the setuptools directory build\ are not copied, replaced, or deleted.
$ProjectDir = Split-Path -Parent $PSScriptRoot
$InstallerDir = Join-Path $ProjectDir "installer"
$OutputDir = Join-Path $InstallerDir "output"
$PyInstallerRoot = Join-Path $InstallerDir "pyinstaller"
$WorkPath = Join-Path $PyInstallerRoot "work"
$DistPath = Join-Path $PyInstallerRoot "dist"
$FrozenDir = Join-Path $DistPath "winlinai"
$FrozenExe = Join-Path $FrozenDir "winlinai.exe"

Write-Host "=== WinLinAI Installer Build ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"
Write-Host "Output:  $OutputDir"

# -Clean removes only this script's directories. A plain run leaves dist\ and
# build\ in place, and -SkipExe reuses installer\pyinstaller\dist\winlinai.
if ($Clean) {
    Write-Host "`nCleaning previous installer builds..." -ForegroundColor Yellow
    Remove-Item -Path $PyInstallerRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Step 1: Build the frozen executable with PyInstaller.
if (-not $SkipExe) {
    Write-Host "`n=== Step 1: Building executable with PyInstaller ===" -ForegroundColor Cyan

    & python -c "import PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
        & python -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) {
            Stop-InstallerBuild "PyInstaller installation failed"
        }
    }

    $specFile = Join-Path $InstallerDir "winlinai.spec"
    Set-Location $ProjectDir
    Remove-Item -Path $WorkPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $FrozenDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $WorkPath -Force | Out-Null
    New-Item -ItemType Directory -Path $DistPath -Force | Out-Null

    & python -m PyInstaller --noconfirm --workpath $WorkPath --distpath $DistPath $specFile
    if ($LASTEXITCODE -ne 0) {
        Stop-InstallerBuild "PyInstaller build failed"
    }
    if (-not (Test-Path $FrozenExe)) {
        Stop-InstallerBuild "PyInstaller finished without $FrozenExe"
    }

    Write-Host "Executable built: $FrozenExe" -ForegroundColor Green
} else {
    Write-Host "`n=== Skipping executable build (using existing) ===" -ForegroundColor Yellow
    if (-not (Test-Path $FrozenExe)) {
        Stop-InstallerBuild "-SkipExe requires $FrozenExe (run without -SkipExe or with -Clean first)"
    }
}

# Step 2: Download Visual C++ Redistributable (optional). A download failure
# does not abort the build: the redistributable is not packaged by the script.
Write-Host "`n=== Step 2: Preparing dependencies ===" -ForegroundColor Cyan
$vcredistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
$vcredistPath = Join-Path $InstallerDir "vcredist_x64.exe"

if (-not (Test-Path $vcredistPath)) {
    Write-Host "Downloading VC++ Redistributable..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $vcredistUrl -OutFile $vcredistPath -UseBasicParsing
        Write-Host "Downloaded: $vcredistPath" -ForegroundColor Green
    } catch {
        Write-Warning "Could not download VC++ Redistributable: $_"
        Write-Host "The installer will check for it at runtime." -ForegroundColor Yellow
    }
}

# Step 3: Build installer with Inno Setup. Reached only when the frozen
# executable from step 1 is present.
Write-Host "`n=== Step 3: Building installer with Inno Setup ===" -ForegroundColor Cyan

$isccPath = $null
$isccCommand = Get-Command iscc -ErrorAction SilentlyContinue
if ($isccCommand) {
    $isccPath = $isccCommand.Source
}
if (-not $isccPath) {
    $innoPaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($path in $innoPaths) {
        if ($path -and (Test-Path $path)) {
            $isccPath = $path
            break
        }
    }
}

if (-not $isccPath) {
    Stop-InstallerBuild "Inno Setup not found. Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
}

# Single source of truth: read __version__ from src/_version.py.
$versionFile = Join-Path $ProjectDir "src\_version.py"
$versionContent = Get-Content $versionFile -Raw
if ($versionContent -notmatch ('__version__' + [char]92 + 's*=' + [char]92 + 's*.([0-9][0-9A-Za-z.+-]*).*')) {
    Stop-InstallerBuild "Could not read __version__ from $versionFile"
}
$AppVersion = $Matches[1]
Write-Host "Building installer for version: $AppVersion"

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$issFile = Join-Path $InstallerDir "winlinai.iss"
& $isccPath "/DMyAppVersion=$AppVersion" $issFile
if ($LASTEXITCODE -ne 0) {
    Stop-InstallerBuild "Inno Setup build failed"
}

$installerFiles = @(Get-ChildItem -Path $OutputDir -Filter "*.exe" -ErrorAction SilentlyContinue)
if ($installerFiles.Count -eq 0) {
    Stop-InstallerBuild "Inno Setup finished without an installer in $OutputDir"
}

Write-Host "`n=== Build Complete ===" -ForegroundColor Green
foreach ($file in $installerFiles) {
    $sizeMB = [math]::Round($file.Length / 1MB, 2)
    Write-Host "Installer: $($file.FullName) ($sizeMB MB)" -ForegroundColor Green
}

Write-Host "`nDone! The installer is in: $OutputDir" -ForegroundColor Cyan
