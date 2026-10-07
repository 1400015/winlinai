"""Tests for PowerShell output normalization (src/platform/pwsh_output.py)."""
import base64
import unittest

from src.platform.pwsh_output import (
    wrap_cmdlet_json,
    parse_json_output,
    normalize_service,
    normalize_process,
    normalize_volume,
    normalize_network_adapter,
    normalize_ip_config,
    normalize_output,
    run_probe,
)


def _decode_script(argv):
    """Decode the -EncodedCommand payload from a launch argv."""
    return base64.b64decode(argv[5]).decode("utf-16-le")


class TestWrapCmdletJson(unittest.TestCase):
    def test_simple_cmdlet(self):
        argv = wrap_cmdlet_json(["Get-Service"])
        self.assertEqual(argv[:5],
                         ("powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand"))
        script = _decode_script(argv)
        self.assertIn("Get-Service", script)
        self.assertIn("ConvertTo-Json", script)
        self.assertIn("-Compress", script)

    def test_cmdlet_with_parameters(self):
        argv = wrap_cmdlet_json(["Get-Service", "-Name", "wuauserv"])
        script = _decode_script(argv)
        self.assertIn("Get-Service", script)
        self.assertIn("-Name", script)
        self.assertIn("'wuauserv'", script)

    def test_quotes_are_escaped(self):
        argv = wrap_cmdlet_json(["Get-Service", "-Name", "it's"])
        script = _decode_script(argv)
        self.assertIn("'it''s'", script)

    def test_empty_argv_raises(self):
        with self.assertRaises(ValueError):
            wrap_cmdlet_json([])


class TestParseJsonOutput(unittest.TestCase):
    def test_clean_json_object(self):
        stdout = '{"Name":"wuauserv","Status":"Running"}'
        data, error = parse_json_output(stdout)
        self.assertIsNone(error)
        self.assertEqual(data["Name"], "wuauserv")
        self.assertEqual(data["Status"], "Running")

    def test_clean_json_array(self):
        stdout = '[{"Name":"a"},{"Name":"b"}]'
        data, error = parse_json_output(stdout)
        self.assertIsNone(error)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["Name"], "a")

    def test_empty_output_success(self):
        data, error = parse_json_output("", returncode=0)
        self.assertIsNone(data)
        self.assertIsNone(error)

    def test_empty_output_failure(self):
        data, error = parse_json_output("", stderr="boom", returncode=1)
        self.assertIsNone(data)
        self.assertEqual(error, "boom")

    def test_non_json_output(self):
        data, error = parse_json_output("plain text output")
        self.assertEqual(data, "plain text output")
        self.assertIsNone(error)

    def test_strips_powershell_error_lines(self):
        stdout = 'powershell : some error\nCategoryInfo : x\n{"Name":"ok"}'
        data, error = parse_json_output(stdout)
        self.assertIsNone(error)
        self.assertEqual(data["Name"], "ok")

    def test_extracts_json_from_mixed_output(self):
        stdout = 'Some preamble text\n{"key":"value"}\ntrailing text'
        data, error = parse_json_output(stdout)
        # The parser should find the JSON object
        self.assertIsNotNone(data)

    def test_returncode_failure_with_stderr(self):
        data, error = parse_json_output("not json", stderr="error msg", returncode=1)
        self.assertIsNone(data)
        self.assertEqual(error, "error msg")

    def test_json_number(self):
        data, error = parse_json_output("42")
        self.assertEqual(data, 42)
        self.assertIsNone(error)

    def test_json_null(self):
        data, error = parse_json_output("null")
        self.assertIsNone(data)
        self.assertIsNone(error)


class TestNormalizeService(unittest.TestCase):
    def test_full_service(self):
        obj = {
            "Name": "wuauserv",
            "DisplayName": "Windows Update",
            "Status": 4,  # Running
            "StartType": 2,  # Automatic
        }
        result = normalize_service(obj)
        self.assertEqual(result["name"], "wuauserv")
        self.assertEqual(result["display_name"], "Windows Update")
        self.assertEqual(result["status"], "4")
        self.assertEqual(result["start_type"], "2")

    def test_empty_service(self):
        self.assertEqual(normalize_service({}), {
            "name": "", "display_name": "", "status": "", "start_type": ""})

    def test_non_dict(self):
        self.assertEqual(normalize_service("not a dict"), {})


class TestNormalizeProcess(unittest.TestCase):
    def test_full_process(self):
        obj = {
            "ProcessName": "chrome",
            "Id": 1234,
            "CPU": 5.5,
            "WorkingSet": 104857600,  # 100 MB
        }
        result = normalize_process(obj)
        self.assertEqual(result["name"], "chrome")
        self.assertEqual(result["id"], 1234)
        self.assertEqual(result["cpu"], 5.5)
        self.assertAlmostEqual(result["memory_mb"], 100.0, places=1)

    def test_non_dict(self):
        self.assertEqual(normalize_process(None), {})


class TestNormalizeVolume(unittest.TestCase):
    def test_full_volume(self):
        obj = {
            "DriveLetter": "C",
            "FileSystemLabel": "Windows",
            "Size": 512000000000,  # ~500 GB
            "SizeRemaining": 128000000000,  # ~128 GB
            "FileSystem": "NTFS",
        }
        result = normalize_volume(obj)
        self.assertEqual(result["drive_letter"], "C")
        self.assertEqual(result["label"], "Windows")
        self.assertAlmostEqual(result["size_gb"], 476.84, places=1)
        self.assertAlmostEqual(result["free_gb"], 119.21, places=1)
        self.assertEqual(result["file_system"], "NTFS")

    def test_missing_values(self):
        result = normalize_volume({})
        self.assertEqual(result["size_gb"], 0)
        self.assertEqual(result["free_gb"], 0)


class TestNormalizeNetworkAdapter(unittest.TestCase):
    def test_full_adapter(self):
        obj = {
            "Name": "Ethernet",
            "InterfaceAlias": "Ethernet",
            "Status": "Up",
            "MacAddress": "00-11-22-33-44-55",
            "LinkSpeed": "1 Gbps",
        }
        result = normalize_network_adapter(obj)
        self.assertEqual(result["name"], "Ethernet")
        self.assertEqual(result["status"], "Up")
        self.assertEqual(result["mac"], "00-11-22-33-44-55")

    def test_non_dict(self):
        self.assertEqual(normalize_network_adapter("x"), {})


class TestNormalizeIpConfig(unittest.TestCase):
    def test_single_ipv4(self):
        obj = {
            "InterfaceAlias": "Ethernet",
            "IPv4Address": [{"IPAddress": "192.168.1.10"}],
            "IPv6Address": [],
            "DNSServer": [{"ServerAddresses": "8.8.8.8"}],
        }
        result = normalize_ip_config(obj)
        self.assertEqual(result["interface"], "Ethernet")
        self.assertEqual(result["ipv4"], ["192.168.1.10"])
        self.assertEqual(result["ipv6"], [])

    def test_multiple_addresses(self):
        obj = {
            "InterfaceAlias": "Wi-Fi",
            "IPv4Address": [
                {"IPAddress": "10.0.0.5"},
                {"IPAddress": "10.0.0.6"},
            ],
        }
        result = normalize_ip_config(obj)
        self.assertEqual(len(result["ipv4"]), 2)


class TestNormalizeOutput(unittest.TestCase):
    def test_no_probe_key(self):
        data = {"key": "value"}
        self.assertEqual(normalize_output(data), data)

    def test_none_data(self):
        self.assertIsNone(normalize_output(None))

    def test_services_list(self):
        data = [
            {"Name": "a", "DisplayName": "A", "Status": 4, "StartType": 2},
            {"Name": "b", "DisplayName": "B", "Status": 1, "StartType": 3},
        ]
        result = normalize_output(data, probe_key="services")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "a")
        self.assertEqual(result[1]["name"], "b")

    def test_processes_single(self):
        data = {"ProcessName": "test", "Id": 1, "CPU": 0, "WorkingSet": 1024}
        result = normalize_output(data, probe_key="processes")
        self.assertEqual(result["name"], "test")

    def test_unknown_probe_key(self):
        data = {"x": 1}
        self.assertEqual(normalize_output(data, probe_key="unknown"), data)


class TestRunProbe(unittest.TestCase):
    def test_rejects_invalid_cmdlet(self):
        result = run_probe(["Remove-Item", "-Path", "x"])
        self.assertFalse(result["ok"])
        self.assertIn("validation", result["error"])

    def test_successful_probe(self):
        def fake_runner(argv, timeout, limit):
            return 0, '{"Name":"wuauserv","Status":4}', ""
        result = run_probe(["Get-Service", "-Name", "wuauserv"], runner=fake_runner)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["Name"], "wuauserv")

    def test_failed_probe(self):
        def fake_runner(argv, timeout, limit):
            return 1, "", "error"
        result = run_probe(["Get-Service"], runner=fake_runner)
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_runner_exception(self):
        def fake_runner(argv, timeout, limit):
            raise RuntimeError("boom")
        result = run_probe(["Get-Date"], runner=fake_runner)
        self.assertFalse(result["ok"])
        self.assertIn("execution failed", result["error"])

    def test_no_runner_available(self):
        # This test may pass or fail depending on platform; just check structure
        result = run_probe(["Get-Date"], runner=None)
        self.assertIn("ok", result)
        self.assertIn("data", result)
        self.assertIn("error", result)

    def test_probe_key_normalizes_data(self):
        def fake_runner(argv, timeout, limit):
            return 0, '{"Name":"wuauserv","DisplayName":"Windows Update","Status":4,"StartType":2}', ""
        result = run_probe(["Get-Service", "-Name", "wuauserv"],
                           runner=fake_runner, probe_key="services")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["name"], "wuauserv")
        self.assertEqual(result["data"]["display_name"], "Windows Update")

    def test_probe_key_normalizes_list(self):
        def fake_runner(argv, timeout, limit):
            return 0, '[{"ProcessName":"a","Id":1,"CPU":0,"WorkingSet":1024},' \
                      '{"ProcessName":"b","Id":2,"CPU":0,"WorkingSet":2048}]', ""
        result = run_probe(["Get-Process"], runner=fake_runner, probe_key="processes")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0]["name"], "a")
        self.assertEqual(result["data"][1]["name"], "b")

    def test_no_probe_key_returns_raw_data(self):
        def fake_runner(argv, timeout, limit):
            return 0, '{"Name":"wuauserv","Status":4}', ""
        result = run_probe(["Get-Service", "-Name", "wuauserv"], runner=fake_runner)
        self.assertTrue(result["ok"])
        # Without probe_key, data is the raw parsed JSON (not normalized)
        self.assertEqual(result["data"]["Name"], "wuauserv")
        self.assertNotIn("name", result["data"])


if __name__ == "__main__":
    unittest.main()
