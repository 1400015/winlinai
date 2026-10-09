"""Tests for installer assets: validate that files referenced by the
installer scripts actually exist (catches broken references without
needing Inno Setup or PyInstaller installed).

This is the "presence check" from the improvement plan (task A.2/A.3):
- winlinai.iss must reference existing files (icon, etc.)
- winlinai.spec must be valid Python and reference existing paths
- build-installer.ps1 and prepare-release.ps1 must have valid PowerShell syntax
"""
import ast
import functools
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path, PureWindowsPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = PROJECT_ROOT / "installer"


def _resolve_iss_path(relative: str) -> Path:
    """Resolve a path the way ISCC does: relative to the .iss directory."""
    return INSTALLER_DIR.joinpath(*PureWindowsPath(relative).parts)


def requires_powershell(test):
    """Skip when no PowerShell parser is available (non-Windows runners).

    On Windows the parser is part of the platform: a missing binary there is
    a real failure, not a skip.
    """
    @functools.wraps(test)
    def wrapper(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            if sys.platform == "win32":
                self.fail("PowerShell parser not found on Windows")
            self.skipTest("PowerShell not available on this host")
        return test(self, executable)
    return wrapper


class TestInnoSetupReferences(unittest.TestCase):
    """Parse winlinai.iss and verify referenced files exist."""

    @classmethod
    def setUpClass(cls):
        cls.iss_path = INSTALLER_DIR / "winlinai.iss"
        cls.iss_text = cls.iss_path.read_text(encoding="utf-8")

    def test_iss_file_exists(self):
        self.assertTrue(self.iss_path.is_file())

    def test_setup_icon_exists(self):
        """SetupIconFile is relative to the .iss file and must exist."""
        match = re.search(r"SetupIconFile=(\S+)", self.iss_text)
        self.assertIsNotNone(match, "SetupIconFile not found in .iss")
        self.assertTrue(match.group(1).startswith("..\\"),
                        "SetupIconFile must leave the installer directory")
        icon_path = _resolve_iss_path(match.group(1))
        self.assertTrue(icon_path.is_file(),
                        f"SetupIconFile does not exist: {icon_path}")
        expected = PROJECT_ROOT / "assets" / "io.github.linux_ai_assistant.ico"
        self.assertEqual(icon_path.resolve(), expected.resolve())

    def test_output_dir_is_beside_the_script(self):
        """ISCC writes beside the .iss file, where the build script looks."""
        match = re.search(r"^OutputDir=(.+)$", self.iss_text, re.MULTILINE)
        self.assertIsNotNone(match, "OutputDir not found in .iss")
        output = _resolve_iss_path(match.group(1).strip())
        self.assertEqual(output, INSTALLER_DIR / "output")

    def test_application_source_is_the_isolated_pyinstaller_dist(self):
        """The packaged app is the frozen directory, not the wheel dist."""
        sources = re.findall(r"Source:\s*\"([^\"]+)\"", self.iss_text)
        packaged = [source for source in sources if "winlinai" in source.lower()]
        self.assertEqual(packaged, ["pyinstaller\\dist\\winlinai\\*"])
        self.assertEqual(
            _resolve_iss_path(packaged[0].replace("*", "winlinai.exe")),
            INSTALLER_DIR / "pyinstaller" / "dist" / "winlinai" / "winlinai.exe")

    def test_iss_sources_are_generated_or_exist(self):
        """Source entries in [Files] may be build artifacts or existing files.
        Only pre-existing files are checked here."""
        sources = re.findall(r"Source:\s*\"([^\"]+)\"", self.iss_text)
        self.assertTrue(len(sources) > 0, "No Source entries found")
        for source in sources:
            # The frozen app and the optional redistributable are produced
            # by the build script and are allowed to be missing here.
            if ("pyinstaller\\dist" in source
                    or source.startswith("installer\\vcredist")):
                continue
            path = _resolve_iss_path(source)
            if "*" in source:
                parent = path.parent
                self.assertTrue(parent.is_dir(),
                                f"Source parent dir missing: {parent}")
            else:
                self.assertTrue(path.exists(),
                                f"Source file missing: {path}")

    def test_iss_version_is_not_hardcoded(self):
        """The .iss must not pin a version: the build script passes it."""
        self.assertNotIn('#define MyAppVersion "1.4.2"', self.iss_text)
        self.assertIn("#ifndef MyAppVersion", self.iss_text)

    def test_prepare_to_install_returns_string(self):
        """Inno Setup 6 declares PrepareToInstall as returning String."""
        self.assertIn(
            "function PrepareToInstall(var NeedsRestart: Boolean): String;",
            self.iss_text)

    def test_build_script_reads_version_from_source(self):
        """The PowerShell build passes /DMyAppVersion from src/_version.py."""
        script = (INSTALLER_DIR / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertIn("_version.py", script)
        self.assertIn("/DMyAppVersion=", script)
        # Windows PowerShell 5.1 Join-Path accepts only one child path.
        self.assertNotIn('Join-Path $ProjectDir "src" "_version.py"', script)
        self.assertIn('Join-Path $ProjectDir "src\\_version.py"', script)

    def test_build_script_cleans_only_with_clean_flag(self):
        """dist/build survive a plain run; -SkipExe reuses the frozen app."""
        script = (INSTALLER_DIR / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertNotIn("if ($Clean -or (Test-Path $DistDir)", script)
        self.assertIn("if ($Clean) {", script)
        self.assertIn("-SkipExe requires", script)

    def test_frozen_build_does_not_touch_the_wheel_directories(self):
        """PyInstaller must not copy or delete the wheel dist or build."""
        script = (INSTALLER_DIR / "build-installer.ps1").read_text(encoding="utf-8")
        self.assertNotIn("Copy-Item", script)
        self.assertNotIn("Remove-Item -Path $DistDir", script)
        self.assertNotIn("Remove-Item -Path $BuildDir", script)
        self.assertIn("--distpath", script)
        self.assertIn("--workpath", script)
        self.assertIn('$DistPath = Join-Path $PyInstallerRoot "dist"', script)
        self.assertIn('$WorkPath = Join-Path $PyInstallerRoot "work"', script)
        self.assertIn("--distpath $DistPath", script)
        self.assertIn("--workpath $WorkPath", script)

    def test_build_script_stops_before_inno_when_pyinstaller_fails(self):
        """A failed frozen build must not continue into the installer step."""
        script = (INSTALLER_DIR / "build-installer.ps1").read_text(encoding="utf-8")
        failed = script.index('Stop-InstallerBuild "PyInstaller build failed"')
        missing = script.index("PyInstaller finished without")
        installer = script.index("Building installer with Inno Setup")
        self.assertLess(failed, installer)
        self.assertLess(missing, installer)
        self.assertIn("exit 1", script)
        self.assertIn('Stop-InstallerBuild "PyInstaller installation failed"', script)
        self.assertIn('Stop-InstallerBuild "Inno Setup build failed"', script)

    def test_prepare_release_stops_after_a_failed_test_or_installer(self):
        """A failed test run or installer build must not continue the release."""
        script = (INSTALLER_DIR / "prepare-release.ps1").read_text(encoding="utf-8")
        self.assertNotIn("continuing with release preparation", script)
        self.assertNotIn("continuing without it", script)
        tests_failed = script.index('Write-Error "Tests failed"')
        installer_failed = script.index('Write-Error "Installer build failed"')
        self.assertLess(tests_failed, installer_failed)
        self.assertIn("exit 1", script[tests_failed:installer_failed])
        self.assertIn("exit 1", script[installer_failed:])


class TestPyInstallerSpec(unittest.TestCase):
    """Validate winlinai.spec."""

    @classmethod
    def setUpClass(cls):
        cls.spec_path = INSTALLER_DIR / "winlinai.spec"
        cls.spec_text = cls.spec_path.read_text(encoding="utf-8")

    def test_spec_file_exists(self):
        self.assertTrue(self.spec_path.is_file())

    def test_spec_is_valid_python(self):
        """The .spec must be parseable Python."""
        ast.parse(self.spec_text)

    def test_spec_entry_point_is_outside_the_package(self):
        """The analyzed script must not be src/app.py (relative imports,
        GTK path); the entry point lives outside the package."""
        self.assertNotIn("'src' / 'app.py'", self.spec_text.replace('"', "'"))
        self.assertNotIn("src.app.py", self.spec_text)
        self.assertIn("qt_entry.py", self.spec_text)
        entry = INSTALLER_DIR / "qt_entry.py"
        self.assertTrue(entry.is_file())
        entry_text = entry.read_text(encoding="utf-8")
        self.assertNotIn("import gi", entry_text)
        self.assertNotIn("from ..", entry_text)
        self.assertIn("from src.qt_app import run", entry_text)
        # pathex keeps the project root so `import src` works when frozen.
        self.assertIn("pathex=[str(project_root)]", self.spec_text)

    def test_spec_bundles_lazy_pywin32_timezone(self):
        """win32timezone is imported by the pywin32 extension, not by our code."""
        self.assertIn("'win32timezone'", self.spec_text)

    def test_spec_has_no_removed_pyinstaller6_options(self):
        """Options removed in PyInstaller 6 must not be present."""
        removed = ["win_no_prefer_redirects", "win_private_assemblies"]
        for option in removed:
            self.assertNotIn(option, self.spec_text,
                             f"Removed PyInstaller 6 option present: {option}")

    def test_spec_icon_exists(self):
        """The icon referenced in the EXE() call must exist."""
        match = re.search(r"icon=str\(project_root / 'assets' / '([^']+)'\)",
                          self.spec_text)
        self.assertIsNotNone(match, "icon reference not found in spec")
        icon_path = PROJECT_ROOT / "assets" / match.group(1)
        self.assertTrue(icon_path.is_file(),
                        f"Spec icon does not exist: {icon_path}")

    def test_spec_datas_paths_exist(self):
        """Directories bundled via datas= must exist."""
        for match in re.finditer(r"str\(project_root / '([^']+)'\), '([^']+)'", self.spec_text):
            source_dir = PROJECT_ROOT / match.group(1)
            self.assertTrue(source_dir.is_dir(),
                            f"datas source missing: {source_dir}")


class TestPowerShellScriptsSyntax(unittest.TestCase):
    """Validate PowerShell syntax of installer scripts."""

    def _validate_ps_syntax(self, executable: str, script_path: Path) -> tuple:
        """Return (ok, errors) using PowerShell's parser."""
        ps_script = f"""
$errors = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count -gt 0) {{
    foreach ($err in $errors) {{
        Write-Output "ERROR line $($err.Extent.StartLineNumber): $($err.Message)"
    }}
    exit 1
}} else {{
    Write-Output "OK"
    exit 0
}}
"""
        try:
            result = subprocess.run(
                [executable, "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=30)
            ok = result.returncode == 0 and "OK" in result.stdout
            return ok, result.stdout + result.stderr
        except Exception as error:
            return False, str(error)

    @requires_powershell
    def test_build_installer_ps1_syntax(self, executable):
        script = INSTALLER_DIR / "build-installer.ps1"
        self.assertTrue(script.is_file())
        ok, output = self._validate_ps_syntax(executable, script)
        self.assertTrue(ok, f"build-installer.ps1 has syntax errors:\n{output}")

    @requires_powershell
    def test_prepare_release_ps1_syntax(self, executable):
        script = INSTALLER_DIR / "prepare-release.ps1"
        self.assertTrue(script.is_file())
        ok, output = self._validate_ps_syntax(executable, script)
        self.assertTrue(ok, f"prepare-release.ps1 has syntax errors:\n{output}")


class TestAssetsExist(unittest.TestCase):
    """Core assets must be present."""

    def test_svg_icon_exists(self):
        self.assertTrue((PROJECT_ROOT / "assets" / "io.github.linux_ai_assistant.svg").is_file())

    def test_ico_icon_exists(self):
        self.assertTrue((PROJECT_ROOT / "assets" / "io.github.linux_ai_assistant.ico").is_file())

    def test_themes_dir_exists(self):
        themes = PROJECT_ROOT / "themes"
        self.assertTrue(themes.is_dir())
        self.assertTrue(len(list(themes.glob("*.json"))) > 0)


if __name__ == "__main__":
    unittest.main()
