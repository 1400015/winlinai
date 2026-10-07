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

# Paths
$ProjectDir = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $ProjectDir "dist"
$BuildDir = Join-Path $ProjectDir "build"
$InstallerDir = Join-Path $ProjectDir "installer"
$OutputDir = Join-Path $InstallerDir "output"
$ExeDir = Join-Path $DistDir "winlinai"

Write-Host "=== WinLinAI Installer Build ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"
Write-Host "Output:  $OutputDir"

# Clean previous builds
if ($Clean -or (Test-Path $DistDir) -or (Test-Path $BuildDir)) {
    Write-Host "`nCleaning previous builds..." -ForegroundColor Yellow
    Remove-Item -Path $DistDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
}

# Create directories
New-Item -ItemType Directory -Path $ExeDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Step 1: Build Python executable with PyInstaller
if (-not $SkipExe) {
    Write-Host "`n=== Step 1: Building executable with PyInstaller ===" -ForegroundColor Cyan

    # Install PyInstaller if needed
    $pyinstaller = Get-Command pyinstaller -ErrorAction SilentlyContinue
    if (-not $pyinstaller) {
        Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
        & python -m pip install pyinstaller
    }

    # Build spec file path
    $specFile = Join-Path $InstallerDir "winlinai.spec"

    Set-Location $ProjectDir
    & pyinstaller --clean --noconfirm $specFile

    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller build failed"
        exit 1
    }

    # Copy dist output to our structure
    $pyinstallerDist = Join-Path $DistDir "winlinai"
    if (Test-Path $pyinstallerDist) {
        Copy-Item -Path "$pyinstallerDist\*" -Destination $ExeDir -Recurse -Force
    }

    Write-Host "Executable built: $ExeDir" -ForegroundColor Green
} else {
    Write-Host "`n=== Skipping executable build (using existing) ===" -ForegroundColor Yellow
}

# Step 2: Download Visual C++ Redistributable (optional)
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

# Step 3: Build installer with Inno Setup
Write-Host "`n=== Step 3: Building installer with Inno Setup ===" -ForegroundColor Cyan

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    # Try common Inno Setup install locations
n    $innoPaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $innoPaths) {
        if (Test-Path $path) {
            $iscc = $path
            break
        }
    }
}

if (-not $iscc) {
    Write-Error "Inno Setup not found. Please install Inno Setup 6 from https://jrsoftware.org/isinfo.php"
    exit 1
}

$issFile = Join-Path $InstallerDir "winlinai.iss"
& $iscc $issFile

if ($LASTEXITCODE -ne 0) {
    Write-Error "Inno Setup build failed"
    exit 1
}

# Step 4: Summary
Write-Host "`n=== Build Complete ===" -ForegroundColor Green
$installerFiles = Get-ChildItem -Path $OutputDir -Filter "*.exe"
foreach ($file in $installerFiles) {
    $sizeMB = [math]::Round($file.Length / 1MB, 2)
    Write-Host "Installer: $($file.FullName) ($sizeMB MB)" -ForegroundColor Green
}

Write-Host "`nDone! The installer is in: $OutputDir" -ForegroundColor Cyan
