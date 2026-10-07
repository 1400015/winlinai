"""Tests for Windows system actions (src/windows_system_actions.py)."""
import unittest
from unittest.mock import patch

from src.windows_system_actions import (
    is_windows,
    format_services_table,
    format_processes_table,
)


class TestIsWindows(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(is_windows(), bool)


class TestFormatServicesTable(unittest.TestCase):
    def test_empty(self):
        result = format_services_table([])
        self.assertEqual(result, "No services found")

    def test_with_services(self):
        services = [
            {"name": "wuauserv", "display_name": "Windows Update",
             "status": "Running", "start_type": "Manual"},
            {"name": "bits", "display_name": "Background Intelligent Transfer",
             "status": "Stopped", "start_type": "Automatic"},
        ]
        result = format_services_table(services)
        self.assertIn("wuauserv", result)
        self.assertIn("Windows Update", result)
        self.assertIn("Running", result)
        self.assertIn("bits", result)
        self.assertIn("Stopped", result)

    def test_header_present(self):
        services = [{"name": "test", "display_name": "Test",
                     "status": "Running", "start_type": "Manual"}]
        result = format_services_table(services)
        self.assertIn("Name", result)
        self.assertIn("Status", result)
        self.assertIn("StartType", result)


class TestFormatProcessesTable(unittest.TestCase):
    def test_empty(self):
        result = format_processes_table([])
        self.assertEqual(result, "No processes found")

    def test_with_processes(self):
        processes = [
            {"name": "chrome", "id": 1234, "cpu": 5.5, "memory_mb": 512.0},
            {"name": "python", "id": 5678, "cpu": 2.3, "memory_mb": 128.5},
        ]
        result = format_processes_table(processes)
        self.assertIn("chrome", result)
        self.assertIn("1234", result)
        self.assertIn("512.0", result)
        self.assertIn("python", result)
        self.assertIn("128.5", result)

    def test_header_present(self):
        processes = [{"name": "test", "id": 1, "cpu": 0, "memory_mb": 0}]
        result = format_processes_table(processes)
        self.assertIn("Name", result)
        self.assertIn("PID", result)
        self.assertIn("CPU", result)
        self.assertIn("Memory", result)


class TestListServices(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import list_services
            ok, services, error = list_services()
            self.assertFalse(ok)
            self.assertEqual(services, [])
            self.assertEqual(error, "Not on Windows")


class TestListProcesses(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import list_processes
            ok, processes, error = list_processes()
            self.assertFalse(ok)
            self.assertEqual(processes, [])
            self.assertEqual(error, "Not on Windows")


class TestGetSystemInfo(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import get_system_info
            ok, info, error = get_system_info()
            self.assertFalse(ok)
            self.assertEqual(info, {})
            self.assertEqual(error, "Not on Windows")


class TestListPackages(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import list_packages
            ok, packages, error = list_packages()
            self.assertFalse(ok)
            self.assertEqual(packages, [])
            self.assertEqual(error, "Not on Windows")

    def test_winget_not_available(self):
        with patch('src.windows_system_actions.is_windows', return_value=True):
            with patch('shutil.which', return_value=None):
                from src.windows_system_actions import list_packages
                ok, packages, error = list_packages()
                self.assertFalse(ok)
                self.assertEqual(packages, [])
                self.assertIn("winget", error)


class TestSearchPackages(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import search_packages
            ok, packages, error = search_packages("test")
            self.assertFalse(ok)
            self.assertEqual(packages, [])
            self.assertEqual(error, "Not on Windows")


class TestGetServiceStatus(unittest.TestCase):
    def test_not_windows(self):
        with patch('src.windows_system_actions.is_windows', return_value=False):
            from src.windows_system_actions import get_service_status
            ok, service, error = get_service_status("test")
            self.assertFalse(ok)
            self.assertIsNone(service)
            self.assertEqual(error, "Not on Windows")

    def test_invalid_name(self):
        with patch('src.windows_system_actions.is_windows', return_value=True):
            from src.windows_system_actions import get_service_status
            ok, service, error = get_service_status("invalid;name")
            self.assertFalse(ok)
            self.assertIsNone(service)
            self.assertIn("Invalid", error)


class TestWingetPolicy(unittest.TestCase):
    """_run_winget must enforce a narrow subcommand/query policy and use
    process_output.run_bounded (never a raw subprocess.run)."""

    def test_list_allowed(self):
        from src.windows_system_actions import _run_winget
        with patch('src.process_output.run_bounded', return_value=(0, "out", "")) as runner:
            _run_winget(["list"])
        runner.assert_called_once()
        argv = runner.call_args[0][0]
        self.assertEqual(argv[0], "winget")
        self.assertEqual(argv[1], "list")

    def test_search_with_valid_query_allowed(self):
        from src.windows_system_actions import _run_winget
        with patch('src.process_output.run_bounded', return_value=(0, "out", "")) as runner:
            _run_winget(["search", "python 3.12"])
        argv = runner.call_args[0][0]
        self.assertEqual(argv[1], "search")
        self.assertIn("python 3.12", argv)

    def test_unknown_subcommand_rejected(self):
        from src.windows_system_actions import _run_winget
        with self.assertRaises(ValueError):
            _run_winget(["install", "evil"])
        with self.assertRaises(ValueError):
            _run_winget(["uninstall", "x"])
        with self.assertRaises(ValueError):
            _run_winget([])

    def test_search_requires_query(self):
        from src.windows_system_actions import _run_winget
        with self.assertRaises(ValueError):
            _run_winget(["search"])

    def test_search_rejects_shell_metacharacters(self):
        from src.windows_system_actions import _run_winget
        for bad in ("foo; rm -rf /", "foo|bar", "$(whoami)", "a && b", "x`y`"):
            with self.subTest(query=bad):
                with self.assertRaises(ValueError):
                    _run_winget(["search", bad])

    def test_search_rejects_paths(self):
        from src.windows_system_actions import _run_winget
        with self.assertRaises(ValueError):
            _run_winget(["search", "C:\\Users\\x"])
        with self.assertRaises(ValueError):
            _run_winget(["search", "/etc/passwd"])

    def test_search_rejects_overlong_query(self):
        from src.windows_system_actions import _run_winget
        with self.assertRaises(ValueError):
            _run_winget(["search", "a" * 200])

    def test_run_bounded_receives_timeout_and_limit(self):
        from src.windows_system_actions import _run_winget
        with patch('src.process_output.run_bounded', return_value=(0, "", "")) as runner:
            _run_winget(["list"], timeout=42, output_limit=1234)
        kwargs = runner.call_args[1]
        self.assertEqual(kwargs["timeout"], 42)
        self.assertEqual(kwargs["limit"], 1234)


class TestWingetTableParser(unittest.TestCase):
    def test_parse_list_with_source(self):
        from src.windows_system_actions import _parse_winget_table
        stdout = "Name      Id          Version   Source\n---       --          -------   ------\nPython    Python.Python 3.12.0  winget\nGit       Git.Git       2.40.0    winget\n"
        packages = _parse_winget_table(stdout, limit=50, with_source=True)
        self.assertEqual(len(packages), 2)
        self.assertEqual(packages[0]["name"], "Python")
        self.assertEqual(packages[0]["id"], "Python.Python")
        self.assertEqual(packages[0]["version"], "3.12.0")
        self.assertEqual(packages[0]["source"], "winget")

    def test_parse_search_without_source(self):
        from src.windows_system_actions import _parse_winget_table
        stdout = "Name      Id          Version\n---       --          -------\nPython    Python.Python 3.12.0\n"
        packages = _parse_winget_table(stdout, limit=50, with_source=False)
        self.assertEqual(len(packages), 1)
        self.assertNotIn("source", packages[0])

    def test_parse_respects_limit(self):
        from src.windows_system_actions import _parse_winget_table
        stdout = "\n".join(f"Pkg{i}  Id{i}  1.0" for i in range(10))
        packages = _parse_winget_table(stdout, limit=3, with_source=False)
        self.assertEqual(len(packages), 3)

    def test_parse_empty(self):
        from src.windows_system_actions import _parse_winget_table
        self.assertEqual(_parse_winget_table("", limit=10, with_source=True), [])


class TestListPackagesUsesRunBounded(unittest.TestCase):
    def test_list_packages_goes_through_run_winget(self):
        with patch('src.windows_system_actions.is_windows', return_value=True):
            with patch('shutil.which', return_value=r"C:\winget.exe"):
                with patch('src.windows_system_actions._run_winget',
                           return_value=(0, "Name Id Version Source\n--- -- ------- -----\nPkg Id 1.0 winget\n", "")) as winget:
                    from src.windows_system_actions import list_packages
                    ok, packages, error = list_packages()
        self.assertTrue(ok)
        winget.assert_called_once_with(["list"], timeout=60)
        self.assertEqual(packages[0]["name"], "Pkg")

    def test_search_packages_goes_through_run_winget(self):
        with patch('src.windows_system_actions.is_windows', return_value=True):
            with patch('shutil.which', return_value=r"C:\winget.exe"):
                with patch('src.windows_system_actions._run_winget',
                           return_value=(0, "Name Id Version\n--- -- -------\nPkg Id 1.0\n", "")) as winget:
                    from src.windows_system_actions import search_packages
                    ok, packages, error = search_packages("pkg")
        self.assertTrue(ok)
        winget.assert_called_once_with(["search", "pkg"], timeout=30)

    def test_no_subprocess_run_in_module(self):
        """The module must not call subprocess.run or import subprocess directly."""
        import inspect
        import src.windows_system_actions as module
        source = inspect.getsource(module)
        # A real call would look like subprocess.run( ... ); a bare import is
        # `import subprocess`. Docstring mentions are fine.
        self.assertNotIn("subprocess.run(", source)
        self.assertNotIn("import subprocess", source)


if __name__ == "__main__":
    unittest.main()
