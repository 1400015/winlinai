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


if __name__ == "__main__":
    unittest.main()
