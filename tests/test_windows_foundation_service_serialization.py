"""Exercise the generated service pipeline against counted PowerShell getters.

This can run with PowerShell on either host. Native Windows/5.1 acceptance
is separate; a Linux PowerShell run proves only the serialization boundary.
"""

import json
import shutil
import subprocess
import sys
import unittest

from src.platform.pwsh_output import wrap_cmdlet_json
from src.platform.shell_pwsh import launch_script


_FIXTURE = """
Add-Type -TypeDefinition @'
public enum FixtureStatus { Stopped = 1, Running = 4 }
public enum FixtureStartType { Automatic = 2, Manual = 3 }
public class FixtureService {
    public static int RelatedReads;
    public string Name { get; set; }
    public string DisplayName { get; set; }
    public FixtureStatus Status { get { return FixtureStatus.Running; } }
    public FixtureStartType StartType { get { return FixtureStartType.Automatic; } }
    public string[] DependentServices {
        get { RelatedReads++; return new string[] { "unneeded" }; }
    }
    public string[] ServicesDependedOn {
        get { RelatedReads++; return new string[] { "unneeded" }; }
    }
    public FixtureService(string name) {
        Name = name; DisplayName = "Serviço Ω - " + name;
    }
}
'@
function Get-Service {
    param([string]$Name)
    if ($PSBoundParameters.ContainsKey('Name')) {
        [FixtureService]::new($Name)
    } else {
        for ($i = 0; $i -lt 57; $i++) {
            [FixtureService]::new("svc_$i")
        }
    }
}
"""


class TestServiceSerialization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executable = shutil.which("powershell") or shutil.which("pwsh")
        if cls.executable is None:
            if sys.platform == "win32":
                raise AssertionError("PowerShell is required on Windows")
            raise unittest.SkipTest("PowerShell not available on this host")

    def serialize(self, cmdlet_argv):
        import base64

        generated = wrap_cmdlet_json(cmdlet_argv)
        pipeline = base64.b64decode(generated[5]).decode("utf-16-le")
        script = (_FIXTURE + "\n$serviceJson = & {\n" + pipeline + "\n};\n"
                  "[PSCustomObject]@{RelatedReads=[FixtureService]::RelatedReads; "
                  "ServicesJson=[string]$serviceJson} | ConvertTo-Json -Compress -Depth 2")
        argv = list(launch_script(script))
        argv[0] = self.executable
        result = subprocess.run(argv, capture_output=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["RelatedReads"], 0,
                         "Get-Service JSON must not read related-service getters")
        return json.loads(envelope["ServicesJson"])

    def assert_service_fields(self, service):
        self.assertEqual(set(service), {"Name", "DisplayName", "Status", "StartType"})
        self.assertEqual(service["DisplayName"], "Serviço Ω - " + service["Name"])
        self.assertEqual(service["Status"], "Running")
        self.assertEqual(service["StartType"], "Automatic")

    def test_full_list_ignores_related_getters_and_keeps_all_services(self):
        services = self.serialize(["Get-Service"])
        self.assertEqual([item["Name"] for item in services],
                         ["svc_{}".format(index) for index in range(57)])
        for service in services:
            self.assert_service_fields(service)

    def test_single_service_keeps_literal_operand_and_text_enums(self):
        # Quoting is tested at the wrapper boundary; run_probe separately
        # rejects operands outside its conservative allowlist.
        service = self.serialize(["Get-Service", "-Name", "it's"])
        self.assertEqual(service["Name"], "it's")
        self.assert_service_fields(service)


if __name__ == "__main__":
    unittest.main()
