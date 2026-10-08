"""Read-only Windows probes wired into the offline chat (no PowerShell runs).

The assistant's platform is fixed per test; nothing depends on the host.
No test executes powershell, winget or the network.
"""
import unittest
from unittest.mock import Mock, patch

from src.offline_assistant import OfflineAssistant, Reply


def _assistant(platform):
    assistant = OfflineAssistant(
        os_release={"ID": "ubuntu", "PRETTY_NAME": "Ubuntu 24.04", "ID_LIKE": "debian"},
        which=lambda name: None,
        is_systemd_running=True,
    )
    assistant._platform = platform
    return assistant


class TestWindowsServicesOffline(unittest.TestCase):
    def _services(self, message, lang="pt"):
        return _assistant("windows")._services_reply(
            _assistant("windows")._distro, lang, message)

    def test_list_services_table(self):
        with patch("src.windows_system_actions.list_services",
                   return_value=(True, [{"name": "wuauserv", "display_name": "Windows Update",
                                         "status": "Running", "start_type": "Manual"}], None)):
            reply = self._services("listar serviços")
        self.assertEqual(reply.commands, [])
        self.assertIn("StartType", reply.text)
        self.assertIn("wuauserv", reply.text)

    def test_list_services_calls_probe_once(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.list_services",
                   return_value=(True, [{"name": "wuauserv", "display_name": "Windows Update",
                                          "status": "Running", "start_type": "Manual"}], None)) as probe, \
                patch("src.windows_system_actions.get_service_status") as status:
            reply = assistant._services_reply(assistant._distro, "pt", "listar serviços")
        probe.assert_called_once()
        status.assert_not_called()
        self.assertIn("wuauserv", reply.text)
        self.assertEqual(reply.commands, [])

    def test_single_service_status(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.get_service_status",
                   return_value=(True, {"name": "wuauserv", "display_name": "Windows Update",
                                        "status": "Running", "start_type": "Manual"}, None)) as status:
            reply = assistant._services_reply(assistant._distro, "pt",
                                              "estado do serviço wuauserv")
        status.assert_called_once_with("wuauserv")
        self.assertEqual(reply.commands, [])

    def test_start_mutation_refused(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.list_services") as probe, \
                patch("src.windows_system_actions.get_service_status") as status:
            for message in ("iniciar serviço wuauserv", "ativar serviço wuauserv"):
                reply = assistant._services_reply(assistant._distro, "pt", message)
                self.assertEqual(reply.commands, [])
                for forbidden in ("systemctl", "sc.exe", "net start",
                                  "Start-Service", "Stop-Service"):
                    self.assertNotIn(forbidden, reply.text)
        probe.assert_not_called()
        status.assert_not_called()

    def test_forbidden_token_refused_without_powershell(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions._run_powershell") as run:
            reply = assistant._services_reply(
                assistant._distro, "pt",
                "estado do serviço wuauserv; Remove-Item C:\\Windows")
        run.assert_not_called()
        self.assertEqual(reply.commands, [])
        self.assertIn("não é aceite", reply.text)

    def test_quote_in_name_refused(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions._run_powershell") as run:
            for message in ("estado do serviço wuauserv'", 'estado do serviço wuauserv|'):
                reply = assistant._services_reply(assistant._distro, "pt", message)
                run.assert_not_called()
                self.assertEqual(reply.commands, [])

    def test_probe_failure_reports_error(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.list_services",
                   return_value=(False, [], "probe unavailable")):
            reply = assistant._services_reply(assistant._distro, "pt", "listar serviços")
        self.assertEqual(reply.commands, [])
        self.assertIn("probe unavailable", reply.text)


class TestWindowsDiskAndMemoryOffline(unittest.TestCase):
    def test_disk_uses_volumes(self):
        assistant = _assistant("windows")
        runner = Mock()
        runner.execute_command = Mock(return_value=(False, "not allowed"))
        assistant._run = runner.execute_command
        with patch("src.windows_system_actions.list_volumes",
                   return_value=(True, [{"drive_letter": "C", "label": "System",
                                         "size_gb": 100.0, "free_gb": 42.0,
                                         "file_system": "NTFS"}], None)) as volumes:
            reply = assistant._disk_reply(assistant._distro, "pt")
        volumes.assert_called_once()
        self.assertIn("C", reply.text)
        self.assertEqual(reply.commands, [])
        runner.execute_command.assert_not_called()

    def test_memory_uses_processes(self):
        assistant = _assistant("windows")
        runner = Mock()
        runner.execute_command = Mock(return_value=(False, "not allowed"))
        assistant._run = runner.execute_command
        with patch("src.windows_system_actions.list_processes",
                   return_value=(True, [{"name": "winlinai", "id": 42, "cpu": 1.0,
                                         "memory_mb": 100.0}], None)) as processes:
            reply = assistant._memory_reply(assistant._distro, "pt")
        processes.assert_called_once()
        self.assertIn("winlinai", reply.text)
        runner.execute_command.assert_not_called()

    def test_wsl_disk_does_not_use_volumes(self):
        assistant = _assistant("wsl")
        assistant._run = Mock(return_value=None)
        with patch("src.windows_system_actions.list_volumes") as volumes:
            assistant._disk_reply(assistant._distro, "pt")
        volumes.assert_not_called()

    def test_processes_via_handle(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.list_processes",
                   return_value=(True, [{"name": "explorer", "id": 4, "cpu": 0.5,
                                         "memory_mb": 80.0}], None)) as processes:
            reply = assistant.handle("processos", "pt")
        processes.assert_called_once()
        self.assertIn("explorer", reply.text)

    def test_handle_disk_uses_volumes_not_df(self):
        assistant = _assistant("windows")
        assistant._run = Mock(return_value=None)
        with patch("src.windows_system_actions.list_volumes",
                   return_value=(True, [{"drive_letter": "C", "label": "System",
                                         "size_gb": 100.0, "free_gb": 42.0,
                                         "file_system": "NTFS"}], None)) as volumes:
            assistant.handle("espaço em disco", "pt")
        volumes.assert_called_once()
        assistant._run.assert_not_called()


class TestLinuxPathsUnchanged(unittest.TestCase):
    def test_linux_services_still_lists_commands(self):
        assistant = _assistant("linux")
        with patch("src.windows_system_actions.list_services") as probe:
            reply = assistant.handle("services", "en")
        probe.assert_not_called()
        self.assertIn("systemctl", reply.text)

    def test_void_enable_service_keeps_runit_argv(self):
        assistant = OfflineAssistant(
            os_release={"ID": "void", "PRETTY_NAME": "Void", "ID_LIKE": ""},
            which=lambda name: None,
            is_systemd_running=False,
        )
        assistant._platform = "linux"
        reply = assistant.handle("ativar serviço chronyd", "pt")
        joined = [part for command in reply.commands for part in command.argv]
        self.assertTrue(any("runit" in part or "ln" in part for part in joined),
                        reply.text)

    def test_linux_disk_still_df(self):
        assistant = _assistant("linux")
        assistant._run = Mock(return_value="Filesystem  Size\n/dev/sda1  100G")
        with patch("src.windows_system_actions.list_volumes") as volumes:
            reply = assistant.handle("disco", "pt")
        volumes.assert_not_called()
        self.assertIn("df -h", reply.text)


class TestProposeAndVolumes(unittest.TestCase):
    def test_propose_services_on_windows_is_empty(self):
        assistant = _assistant("windows")
        with patch("src.windows_system_actions.list_services",
                   return_value=(True, [], None)):
            reply = assistant.propose("services", "pt")
        self.assertEqual(reply.text, "")
        self.assertEqual(reply.commands, [])

    def test_propose_linux_unchanged(self):
        assistant = _assistant("linux")
        reply = assistant.propose("services", "en")
        # On Linux the services intent is a template with commands or empty;
        # the contract is only that the Windows branch did not take over.
        self.assertIsInstance(reply, Reply)

    def test_list_volumes_argv_and_no_cim(self):
        from src.windows_system_actions import format_volumes_table, list_volumes
        captured = {}

        def fake_run(cmdlet_argv, timeout=30):
            captured["argv"] = cmdlet_argv
            return {"ok": True, "data": [{"DriveLetter": "C", "FileSystemLabel": "System",
                                         "Size": 107374182400, "SizeRemaining": 45097156608,
                                         "FileSystem": "NTFS"}], "error": None}

        with patch("src.windows_system_actions.is_windows", return_value=True), \
                patch("src.windows_system_actions._run_powershell", side_effect=fake_run):
            ok, volumes, error = list_volumes()
        self.assertTrue(ok)
        self.assertEqual(captured["argv"], ["Get-Volume"])
        table = format_volumes_table(volumes)
        self.assertIn("C", table)
        self.assertNotIn("Get-CimInstance", table)

    def test_list_volumes_not_windows(self):
        from src.windows_system_actions import list_volumes
        with patch("src.windows_system_actions.is_windows", return_value=False):
            ok, volumes, error = list_volumes()
        self.assertFalse(ok)
        self.assertEqual(volumes, [])
        self.assertEqual(error, "Not on Windows")


if __name__ == "__main__":
    unittest.main()
