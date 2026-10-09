"""Accept the service JSON probe on the real Windows PowerShell 5.1 engine."""

import json
import os
from pathlib import Path
import time
import unittest

from src.platform.pwsh_output import run_probe
from src.platform.shell_pwsh import launch_script, validate_pwsh_arguments
from src.process_output import run_bounded


@unittest.skipUnless(os.name == 'nt', 'Requires native Windows PowerShell 5.1')
class TestNativeServiceProbe(unittest.TestCase):
    def test_full_inventory_and_individual_service_on_powershell_51(self):
        # Pin the inbox engine, so pwsh 7 on the runner cannot satisfy the
        # Windows PowerShell 5.1 acceptance contract accidentally.
        system_root = os.environ.get('SystemRoot')
        self.assertTrue(system_root, 'SystemRoot must identify the native Windows installation')
        powershell = Path(system_root) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        self.assertTrue(powershell.is_file(), 'The inbox Windows PowerShell engine is required')

        def inbox_runner(argv, timeout, limit):
            self.assertEqual(argv[0], 'powershell')
            self.assertEqual(timeout, 30, 'The service probe must retain its current timeout')
            return run_bounded([str(powershell), *argv[1:]], timeout=timeout, limit=limit)

        # Serialize service names only for the reference inventory: this
        # direct query never feeds ServiceController objects into JSON.
        direct_script = """
if ($PSVersionTable.PSEdition -ne 'Desktop' -or
    $PSVersionTable.PSVersion.Major -ne 5 -or
    $PSVersionTable.PSVersion.Minor -ne 1) {
    throw 'This acceptance test requires Windows PowerShell 5.1 Desktop'
}
[pscustomobject]@{
    Edition = $PSVersionTable.PSEdition
    Version = $PSVersionTable.PSVersion.ToString()
    Names = @(Get-Service | ForEach-Object { [string]$_.Name })
} | ConvertTo-Json -Compress -Depth 2
"""
        direct_started = time.monotonic()
        code, stdout, stderr = inbox_runner(list(launch_script(direct_script)),
                                           timeout=30, limit=1024 * 1024)
        direct_elapsed = time.monotonic() - direct_started
        self.assertEqual(code, 0, stderr or stdout)
        direct = json.loads(stdout)
        self.assertEqual(direct['Edition'], 'Desktop')
        self.assertTrue(direct['Version'].startswith('5.1.'))
        names = direct['Names']
        self.assertIsInstance(names, list)
        self.assertTrue(names, 'Native Windows must return its real service inventory')
        self.assertTrue(all(isinstance(name, str) and name for name in names))

        probe_started = time.monotonic()
        result = run_probe(['Get-Service'], runner=inbox_runner)
        probe_elapsed = time.monotonic() - probe_started
        self.assertTrue(result['ok'], result.get('error') or result.get('raw'))
        self.assertEqual(result['returncode'], 0)
        services = result['data']
        if isinstance(services, dict):
            services = [services]
        self.assertIsInstance(services, list)
        self.assertEqual(len(services), len(names))
        self.assertEqual({service['Name'] for service in services}, set(names))

        expected_keys = {'Name', 'DisplayName', 'Status', 'StartType'}
        statuses = {'Stopped', 'StartPending', 'StopPending', 'Running',
                    'ContinuePending', 'PausePending', 'Paused'}
        start_types = {'Boot', 'System', 'Automatic', 'Manual', 'Disabled'}
        for service in services:
            self.assertEqual(set(service), expected_keys)
            for key in expected_keys:
                self.assertIsInstance(service[key], str)
            self.assertIn(service['Status'], statuses)
            self.assertIn(service['StartType'], start_types)

        # Service state may change between the two reads. Name and display
        # name identify the same real service without freezing its state.
        name = next((name for name in names
                     if validate_pwsh_arguments(['Get-Service', '-Name', name])), None)
        self.assertIsNotNone(name, 'The inventory must contain a name accepted by the read-only policy')
        individual = run_probe(['Get-Service', '-Name', name], runner=inbox_runner)
        self.assertTrue(individual['ok'], individual.get('error') or individual.get('raw'))
        service = individual['data']
        self.assertIsInstance(service, dict)
        self.assertEqual(set(service), expected_keys)
        self.assertEqual(service['Name'], name)
        listed_service = next(item for item in services if item['Name'] == name)
        self.assertEqual(service['DisplayName'], listed_service['DisplayName'])
        self.assertIn(service['Status'], statuses)
        self.assertIn(service['StartType'], start_types)
        print('Windows PowerShell {}: {} real services; direct {:.2f}s, JSON probe {:.2f}s'.format(
            direct['Version'], len(services), direct_elapsed, probe_elapsed), flush=True)


if __name__ == '__main__':
    unittest.main()
