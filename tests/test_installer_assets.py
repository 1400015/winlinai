"""Tests for installer assets: validate that files referenced by the
installer scripts actually exist (catches broken references without
needing Inno Setup or PyInstaller installed).

This is the "presence check" from the improvement plan (task A.2/A.3):
- winlinai.iss must reference existing files (icon, etc.)
- winlinai.spec must be valid Python and reference existing paths
- build-installer.ps1 and prepare-release.ps1 must have valid PowerShell syntax
"""
import ast
import re
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = PROJECT_ROOT / "installer"


class TestInnoSetupReferences(unittest.TestCase):
    """Parse winlinai.iss and verify referenced files exist."""

    @classmethod
    def setUpClass(cls):
        cls.iss_path = INSTALLER_DIR / "winlinai.iss"
        cls.iss_text = cls.iss_path.read_text(encoding="utf-8")

    def test_iss_file_exists(self):
        self.assertTrue(self.iss_path.is_file())

    def test_setup_icon_exists(self):
        """SetupIconFile must point to an existing file."""
        match = re.search(r"SetupIconFile=(\S+)", self.iss_text)
        self.assertIsNotNone(match, "SetupIconFile not found in .iss")
        icon_path = PROJECT_ROOT / match.group(1)
        self.assertTrue(icon_path.is_file(),
                        f"SetupIconFile does not exist: {icon_path}")

    def test_iss_sources_are_generated_or_exist(self):
        """Source entries in [Files] may be build artifacts (dist/) or
        existing files. Only pre-existing files are checked here."""
        # Find all Source: lines in [Files] section
        sources = re.findall(r"Source:\s*\"([^\"]+)\"", self.iss_text)
        self.assertTrue(len(sources) > 0, "No Source entries found")
        for source in sources:
            # Build artifacts (generated during build) are allowed to be missing
            if source.startswith("dist\\") or source.startswith("installer\\vcredist"):
                continue
            path = PROJECT_ROOT / source.replace("\\", "/")
            # May contain wildcards — check parent directory
            if "*" in source:
                parent = path.parent
                self.assertTrue(parent.is_dir(),
                                f"Source parent dir missing: {parent}")
            else:
                self.assertTrue(path.exists(),
                                f"Source file missing: {path}")

    def test_app_version_matches_project(self):
        """The .iss version should match src/_version.py."""
        from src._version import __version__
        match = re.search(r'#define MyAppVersion "([^"]+)"', self.iss_text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), __version__,
                         "winlinai.iss version does not match src/_version.py")


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

    def _validate_ps_syntax(self, script_path: Path) -> tuple:
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
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=30)
            ok = result.returncode == 0 and "OK" in result.stdout
            return ok, result.stdout + result.stderr
        except Exception as error:
            return False, str(error)

    def test_build_installer_ps1_syntax(self):
        script = INSTALLER_DIR / "build-installer.ps1"
        self.assertTrue(script.is_file())
        ok, output = self._validate_ps_syntax(script)
        self.assertTrue(ok, f"build-installer.ps1 has syntax errors:\n{output}")

    def test_prepare_release_ps1_syntax(self):
        script = INSTALLER_DIR / "prepare-release.ps1"
        self.assertTrue(script.is_file())
        ok, output = self._validate_ps_syntax(script)
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
