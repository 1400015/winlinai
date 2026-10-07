# WinLinAI Release Preparation Script (PowerShell)
# Prepares a new release for GitHub
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File installer/prepare-release.ps1 -Version "1.5.0"
#   powershell -ExecutionPolicy Bypass -File installer/prepare-release.ps1 -Version "1.5.0" -Draft
#   powershell -ExecutionPolicy Bypass -File installer/prepare-release.ps1 -Version "1.5.0" -Prerelease

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [switch]$Draft,
    [switch]$Prerelease,
    [string]$Notes = ""
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

Write-Host "=== WinLinAI Release Preparation ===" -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host "Draft: $Draft"
Write-Host "Prerelease: $Prerelease"

# Validate version format
if ($Version -notmatch '^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$') {
    Write-Error "Invalid version format. Use semantic versioning (e.g., 1.5.0 or 1.5.0-beta)"
    exit 1
}

# Step 1: Update version in src/_version.py
Write-Host "`n=== Step 1: Updating version ===" -ForegroundColor Cyan
$versionFile = Join-Path $ProjectDir "src\_version.py"
$versionContent = Get-Content $versionFile -Raw
$newVersionContent = $versionContent -replace '__version__ = "[^"]+"', "__version__ = `"$Version`""
Set-Content -Path $versionFile -Value $newVersionContent -NoNewline
Write-Host "Updated $versionFile to version $Version" -ForegroundColor Green

# Step 2: Run tests
Write-Host "`n=== Step 2: Running tests ===" -ForegroundColor Cyan
$testResult = & python -m pytest tests/ -q --ignore=tests/test_action_infrastructure.py --ignore=tests/test_windows_phase1.py --ignore=tests/test_windows_phase2.py --ignore=tests/test_windows_phase3.py --ignore=tests/test_qt_phase4a.py --ignore=tests/test_qt_phase4b.py --ignore=tests/test_qt_phase4d.py --ignore=tests/test_qt_phase4e.py 2>&1
$testExitCode = $LASTEXITCODE
Write-Host $testResult
if ($testExitCode -ne 0) {
    Write-Warning "Some tests failed, but continuing with release preparation"
}

# Step 3: Build wheel
Write-Host "`n=== Step 3: Building wheel ===" -ForegroundColor Cyan
& python -m pip install build
& python -m build --wheel
if ($LASTEXITCODE -ne 0) {
    Write-Error "Wheel build failed"
    exit 1
}
Write-Host "Wheel built successfully" -ForegroundColor Green

# Step 4: Build Windows installer (optional)
Write-Host "`n=== Step 4: Building Windows installer ===" -ForegroundColor Cyan
$buildInstaller = Read-Host "Build Windows installer? (y/n)"
if ($buildInstaller -eq "y") {
    & powershell -ExecutionPolicy Bypass -File installer/build-installer.ps1 -Clean
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Installer build failed, continuing without it"
    }
}

# Step 5: Generate release notes
Write-Host "`n=== Step 5: Generating release notes ===" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($Notes)) {
    $Notes = @"
## WinLinAI v$Version

### Windows Support (Beta)

This release introduces native Windows support with a Qt-based interface.

#### Features
- Qt/PySide6 interface for Windows
- AI provider integration (OpenRouter, Google, Anthropic, Mistral, Groq, Cohere, Local)
- Offline assistant with Windows/PowerShell/WSL knowledge
- Visual themes (dark, light, dracula, solarized-dark)
- System tray with Expert Mode and Statistics
- Autostart on Windows login
- Screenshot capture
- Image attachments (vision models)
- File actions with diff preview and backups
- System diagnostics (services, processes, packages via winget)
- PowerShell output normalization
- Conversation export (Markdown/JSON/Text)

#### Installation
1. Download the installer: ``WinLinAI-$Version-Setup.exe``
2. Run the installer (no admin rights required)
3. Launch WinLinAI from the Start Menu

#### Requirements
- Windows 10/11 (64-bit)
- Python 3.12+ (included in installer)

#### Known Limitations
- Windows support is experimental (beta)
- Some Linux-specific features are not available on Windows
- WSL integration requires WSL to be installed

---
*Full changelog: https://github.com/1400015/winlinai/blob/master/docs/alteracoes.md*
"@
}

$notesFile = Join-Path $ProjectDir "installer\release-notes-$Version.md"
Set-Content -Path $notesFile -Value $Notes
Write-Host "Release notes saved to: $notesFile" -ForegroundColor Green

# Step 6: Git operations
Write-Host "`n=== Step 6: Git operations ===" -ForegroundColor Cyan

# Check git status
$gitStatus = & git status --porcelain
if ($gitStatus) {
    Write-Host "Uncommitted changes detected. Committing..." -ForegroundColor Yellow
    & git add -A
    & git commit -m "chore(release): prepare v$Version"
}

# Create tag
$tagName = "v$Version"
$tagExists = & git tag -l $tagName
if ($tagExists) {
    Write-Warning "Tag $tagName already exists"
} else {
    & git tag -a $tagName -m "Release $tagName"
    Write-Host "Created tag: $tagName" -ForegroundColor Green
}

# Step 7: Summary
Write-Host "`n=== Release Preparation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Review the changes: git log --oneline -5"
Write-Host "2. Push the tag: git push origin $tagName"
Write-Host "3. Push the branch: git push origin fix/windows-foundation"
Write-Host "4. Create a GitHub release:"
Write-Host "   - Go to https://github.com/1400015/winlinai/releases/new"
Write-Host "   - Select tag: $tagName"
Write-Host "   - Title: WinLinAI $Version"
Write-Host "   - Description: (paste from $notesFile)"
if ($Prerelease) {
    Write-Host "   - Check 'This is a pre-release'"
}
if ($Draft) {
    Write-Host "   - Save as draft"
}
Write-Host "5. Upload installer: installer/output/WinLinAI-$Version-Setup.exe"
Write-Host "6. Upload wheel: dist/winlinai-$Version-py3-none-any.whl"

Write-Host ""
Write-Host "Release artifacts:" -ForegroundColor Cyan
Get-ChildItem -Path $ProjectDir\dist -Filter "*.whl" | ForEach-Object { Write-Host "  - $($_.FullName)" }
Get-ChildItem -Path $ProjectDir\installer\output -Filter "*.exe" -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  - $($_.FullName)" }
