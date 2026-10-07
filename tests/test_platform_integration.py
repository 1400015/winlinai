"""Phase 3 integration: platform probes flow through the real execution path."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.platform import WINDOWS, WSL
from src.platform.probes import probe_argv_for


class TestProbeArgvFor(unittest.TestCase):
    def test_windows_probes_are_wrapped_for_powershell(self):
        for key in ("links", "addresses", "routes", "disk", "memory"):
            with self.subTest(key=key):
                argv = probe_argv_for(key, platform=WINDOWS)
                self.assertIsNotNone(argv)
                self.assertEqual(argv[:2], ("powershell", "-Command"))
                self.assertTrue(argv[2].startswith("Get-"))

    def test_windows_probe_is_none_when_policy_rejects(self):
        def reject(argv):
            return False
        self.assertIsNone(probe_argv_for("links", platform=WINDOWS, validate_pwsh=reject))

    def test_windows_probe_with_explicit_distro_wraps_posix_inner_command(self):
        argv = probe_argv_for("disk", platform=WINDOWS, wsl_distro="Ubuntu")
        self.assertEqual(argv, ("wsl.exe", "--distribution", "Ubuntu", "--exec", "df", "-h"))

    def test_wsl_probe_is_native_with_or_without_a_distro(self):
        for distro in (None, "Ubuntu", "another-distro", "--exec"):
            with self.subTest(distro=distro):
                self.assertEqual(probe_argv_for("disk", platform=WSL, wsl_distro=distro), ("df", "-h"))

    def test_unsupported_windows_inodes_returns_none(self):
        self.assertIsNone(probe_argv_for("inodes", platform=WINDOWS))

    def test_invalid_explicit_windows_destination_never_falls_back_to_host(self):
        for distro in ("", "--exec", "Ubuntu;wsl"):
            with self.subTest(distro=distro):
                self.assertIsNone(probe_argv_for("disk", platform=WINDOWS, wsl_distro=distro))

    def test_linux_keeps_none_and_native_path(self):
        self.assertIsNone(probe_argv_for("links", platform="linux"))
        self.assertIsNone(probe_argv_for("not-a-key", platform=WINDOWS))


class TestSystemUtilsPlatformPath(unittest.TestCase):
    def setUp(self):
        from src.system_utils import SystemUtils
        self.utils = SystemUtils(SimpleNamespace(get=Mock(return_value={"allowed_commands": ["df"]})))

    def test_validated_powershell_probe_runs_through_platform_path(self):
        utils = self.utils
        captured = {}
        def fake_run(argv, timeout, limit):
            captured["argv"] = argv
            return 0, "Name  InterfaceDescription", ""
        with patch("src.system_utils.run_bounded", side_effect=fake_run), \
                patch("src.platform.detect_platform", return_value="windows"):
            ok, output = utils.execute_command(["powershell", "-Command", "Get-NetAdapter"], timeout=5)
        self.assertTrue(ok)
        self.assertIn("InterfaceDescription", output)
        self.assertEqual(captured["argv"][:5],
                         ("powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand"))

    def test_mutation_cmdlet_is_rejected(self):
        with patch("src.platform.detect_platform", return_value="windows"):
            ok, output = self.utils.execute_command(["powershell", "-Command", "Remove-Item", "-Path", "x"])
        self.assertFalse(ok)
        self.assertIn("rejected", output)

    def test_injection_is_rejected(self):
        with patch("src.platform.detect_platform", return_value="windows"):
            ok, output = self.utils.execute_command(["powershell", "-Command", "Get-Service", "-Name", "a;rm"])
        self.assertFalse(ok)

    def test_bare_powershell_without_command_is_rejected(self):
        with patch("src.platform.detect_platform", return_value="windows"):
            ok, output = self.utils.execute_command(["powershell"])
        self.assertFalse(ok)

    def test_powershell_probe_is_not_special_cased_off_windows(self):
        # pwsh exists on Linux too; the bypass must not apply there.
        ok, output = self.utils.execute_command(["powershell", "-Command", "Get-NetAdapter"])
        self.assertFalse(ok)

    def test_platform_engines_are_denied_off_windows_even_if_config_allowlists_them(self):
        self.utils.config.get = Mock(return_value=["powershell", "wsl.exe", "pwsh"])
        with patch("src.system_utils.run_bounded") as run:
            for host in ("linux", WSL):
                with patch("src.platform.detect_platform", return_value=host):
                    for command in (["powershell", "-Command", "Get-NetAdapter"],
                                    ["wsl.exe", "--distribution", "Ubuntu", "--exec", "df", "-h"],
                                    ["pwsh", "-Command", "Remove-Item x"]):
                        with self.subTest(host=host, command=command):
                            self.assertFalse(self.utils.execute_command(command)[0])
            run.assert_not_called()

    def test_external_powershell_launch_options_are_rejected(self):
        with patch("src.platform.detect_platform", return_value=WINDOWS), \
                patch("src.system_utils.run_bounded") as run:
            for command in (["powershell", "-NoProfile", "-Command", "Get-NetAdapter"],
                            ["powershell", "-EncodedCommand", "anything"],
                            ["powershell.exe", "-Command", "Get-NetAdapter"],
                            ["powershell", "-Command", "Get-NetAdapter", ""]):
                with self.subTest(command=command):
                    self.assertFalse(self.utils.execute_command(command)[0])
            run.assert_not_called()

    def test_wsl_probe_with_validated_inner_command_runs(self):
        utils = self.utils
        def fake_run(argv, timeout, limit):
            return 0, "Filesystem Size Used", ""
        with patch("src.system_utils.run_bounded", side_effect=fake_run), \
                patch("src.platform.detect_platform", return_value="windows"):
            ok, output = utils.execute_command(
                ["wsl.exe", "--distribution", "Ubuntu", "--exec", "df", "-h"], timeout=5)
        self.assertTrue(ok)

    def test_wsl_probe_with_unsafe_inner_command_is_rejected(self):
        with patch("src.platform.detect_platform", return_value="windows"):
            ok, output = self.utils.execute_command(
                ["wsl.exe", "--distribution", "Ubuntu", "--exec", "bash", "-c", "id"])
        self.assertFalse(ok)

    def test_wsl_rejects_mutations_and_arbitrary_files_without_execution(self):
        with patch("src.platform.detect_platform", return_value=WINDOWS), \
                patch("src.system_utils.run_bounded") as run:
            for inner in (["rm", "-rf", "/tmp/x"], ["touch", "/tmp/x"],
                          ["curl", "https://example.com"], ["cat", "/etc/shadow"],
                          ["df", "-h", "/private"]):
                with self.subTest(inner=inner):
                    command = ["wsl.exe", "--distribution", "Ubuntu", "--exec", *inner]
                    self.assertFalse(self.utils.execute_command(command)[0])
            run.assert_not_called()

    def test_wsl_rejects_noncanonical_wrapper_options_and_empty_arguments(self):
        with patch("src.platform.detect_platform", return_value=WINDOWS), \
                patch("src.system_utils.run_bounded") as run:
            for command in (["wsl.exe", "--Distribution", "Ubuntu", "--exec", "df", "-h"],
                            ["wsl.exe", "--distribution", "Ubuntu", "--EXEC", "df", "-h"],
                            ["wsl.exe", "--distribution", "Ubuntu", "", "--exec", "df", "-h"]):
                with self.subTest(command=command):
                    self.assertFalse(self.utils.execute_command(command)[0])
            run.assert_not_called()

    def test_platform_runner_also_enforces_host_and_probe_policy(self):
        with patch("src.system_utils.run_bounded") as run:
            for host, command in ((WSL, ["powershell", "-Command", "Get-NetAdapter"]),
                                  (WINDOWS, ["powershell", "-Command", "Remove-Item", "-Path", "x"])):
                with self.subTest(host=host), patch("src.platform.detect_platform", return_value=host):
                    self.assertFalse(self.utils._run_platform_probe(command, timeout=3)[0])
            run.assert_not_called()

    def test_wsl_probe_with_wrong_wrapper_tokens_is_rejected(self):
        # A middle token must never become the wsl.exe subcommand.
        with patch("src.platform.detect_platform", return_value="windows"):
            ok, _ = self.utils.execute_command(
                ["wsl.exe", "malicious", "Ubuntu", "x", "ip", "route"])
            self.assertFalse(ok)
            ok, _ = self.utils.execute_command(
                ["wsl.exe", "--distribution", "Ubuntu", "wrong", "ip"])
            self.assertFalse(ok)

    def test_posix_allowlist_still_applies_to_normal_commands(self):
        ok, output = self.utils.execute_command(["ls"], timeout=5)
        self.assertFalse(ok)
        self.assertIn("not allowed", output.lower())


class TestOfflineAssistantPlatformProbe(unittest.TestCase):
    def setUp(self):
        from src.offline_assistant import OfflineAssistant
        self.OfflineAssistant = OfflineAssistant

    def assistant(self, platform="linux", wsl=""):
        utils = Mock()
        utils.execute_command = Mock(return_value=(True, "UP  eth0"))
        assistant = self.OfflineAssistant(
            utils,
            os_release={"ID": "ubuntu", "PRETTY_NAME": "Ubuntu", "ID_LIKE": "debian"},
            which=lambda name: None,
            is_systemd_running=False,
        )
        assistant._platform = platform
        assistant._wsl_distro = wsl
        return assistant, utils

    def test_windows_probe_uses_powershell_argv(self):
        assistant, utils = self.assistant(platform=WINDOWS)
        result = assistant._probe("links")
        self.assertEqual(utils.execute_command.call_args[0][0],
                         ["powershell", "-Command", "Get-NetAdapter"])
        self.assertEqual(result, "UP  eth0")

    def test_wsl_probe_runs_native_posix_command(self):
        assistant, utils = self.assistant(platform=WSL, wsl="Ubuntu")
        assistant._probe("disk")
        self.assertEqual(utils.execute_command.call_args[0][0],
                         ["df", "-h"])

    def test_windows_inodes_probe_is_unavailable_without_execution(self):
        assistant, utils = self.assistant(platform=WINDOWS)
        utils.execute_command.reset_mock()
        self.assertIsNone(assistant._probe("inodes"))
        utils.execute_command.assert_not_called()

    def test_windows_probe_without_utils_returns_none(self):
        assistant, _ = self.assistant(platform=WINDOWS)
        assistant.system_utils = None
        self.assertIsNone(assistant._probe("links"))

    def test_linux_probe_keeps_native_path(self):
        assistant, utils = self.assistant(platform="linux")
        assistant._distro = SimpleNamespace(
            available_tools=("ip", "df", "free"))
        assistant._probe("links")
        self.assertEqual(utils.execute_command.call_args[0][0], "ip link show")


if __name__ == "__main__":
    unittest.main()


class TestReviewFixes(unittest.TestCase):
    """Regression tests for the findings of the critical pass."""

    def test_wsl_wrapper_tokens_must_match_exactly(self):
        from src.system_utils import SystemUtils
        utils = SystemUtils(SimpleNamespace(get=Mock(return_value={
            "permissions": {"allowed_commands": ["df"]}})))
        with patch("src.platform.detect_platform", return_value="windows"):
            for argv in (["wsl.exe", "malicious", "Ubuntu", "x", "ip", "route"],
                         ["wsl.exe", "--distribution", "Ubuntu", "wrong", "ip"],
                         ["wsl.exe"]):
                with self.subTest(argv=argv):
                    ok, _ = utils.execute_command(argv, timeout=3)
                    self.assertFalse(ok)

    def test_file_reading_cmdlets_bypass_nothing(self):
        from src.platform.shell_pwsh import validate_pwsh_arguments
        for argv in (["Get-Content", "-Path", "C:\\secrets.txt"],
                     ["Get-ChildItem", "-Recurse"],
                     ["Get-Item", "-Path", "x"],
                     ["Get-Acl", "-Path", "x"]):
            with self.subTest(argv=argv):
                self.assertFalse(validate_pwsh_arguments(argv))

    def test_resolve_dnsname_is_not_a_local_probe(self):
        from src.platform.shell_pwsh import validate_pwsh_arguments
        self.assertFalse(validate_pwsh_arguments(["Resolve-DnsName", "example.com"]))

    def test_get_winevent_keeps_local_log_reads(self):
        from src.platform.shell_pwsh import validate_pwsh_arguments
        self.assertTrue(validate_pwsh_arguments(
            ["Get-WinEvent", "-LogName", "System", "-MaxEvents", "50"]))
        self.assertFalse(validate_pwsh_arguments(
            ["Get-WinEvent", "-LogName", "System", "-ComputerName", "other"]))

    def test_qt_lock_file_path_is_deterministic(self):
        import src.qt_app as qt_app
        path = qt_app.lock_file_path(base_dir="/tmp/x")
        self.assertTrue(path.endswith("qt-instance.lock"))
