"""Install a built wheel outside the checkout and verify its public surface."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestInstalledWindowsFoundation(unittest.TestCase):
    def test_installed_wheel_contains_platform_modules_data_and_dependencies(self):
        self.assertIsNotNone(importlib.util.find_spec("build"), "Install build to validate the wheel")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            distribution = temporary / "dist"
            installed = temporary / "installed"
            build = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(distribution)],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheels = list(distribution.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            install = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheels[0])],
                cwd=temporary, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            script = textwrap.dedent("""
                import importlib
                import importlib.metadata
                import os
                from pathlib import Path
                import sys
                from packaging.requirements import Requirement
                import src
                target = Path(sys.argv[1]).resolve()
                assert os.path.commonpath([str(Path(src.__file__).resolve()), str(target)]) == str(target)
                for name in ('src.platform', 'src.platform.ui_selection', 'src.platform.probes',
                             'src.platform.windows_files', 'src.platform.shell_pwsh',
                             'src.platform.wsl_bridge', 'src.platform.tray_config'):
                    importlib.import_module(name)
                from src.platform.ui_selection import select_ui_track
                assert select_ui_track('auto', 'windows') == 'qt'
                assert select_ui_track('auto', 'linux') == 'gtk'
                import src.app
                assert 'src.main_window' not in sys.modules
                assert 'src.tray_icon' not in sys.modules
                data = Path(src.__file__).parent / 'knowledge_data'
                assert (data / 'schema' / 'knowledge-module.schema.json').is_file()
                assert (data / 'windows-core.yaml').is_file()
                assert list((target / 'share' / 'linux-ai-assistant' / 'themes').glob('*.json'))
                metadata = importlib.metadata.distribution('winlinai')
                commands = {item.name: item.value for item in metadata.entry_points if item.group == 'console_scripts'}
                assert commands['linux-ai-assistant'] == commands['winlinai'] == 'src.app:main'
                requirements = {item.name: item for item in map(Requirement, metadata.requires)}
                for name, expected in (('notify2', 'linux'), ('pywin32', 'win32')):
                    marker = requirements[name].marker
                    assert marker is not None
                    for platform in ('linux', 'win32', 'darwin'):
                        assert marker.evaluate({'sys_platform': platform}) == (platform == expected)
                assert '306' in str(requirements['pywin32'].specifier)
            """)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(installed)
            result = subprocess.run([sys.executable, "-c", script, str(installed)],
                                    cwd=temporary, env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
