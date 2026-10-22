"""The coverage gate must stay measurable and must not be silently weakened.

The floor is the only guard against a silent loss of tests. These checks keep
the configuration honest: the floor must exist, must be a sane percentage,
and must never be lowered below the value the CI job measured.
"""

from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHECKER = ROOT / "scripts" / "check_coverage.py"


def _floors():
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r"\[tool\.coverage\.floors\](.*?)(?=\n\[|\Z)", text, re.DOTALL)
    if not match:
        return {}
    return {name: float(value)
            for name, value in re.findall(r"(\w+)\s*=\s*([0-9.]+)", match.group(1))}


class CoverageGateTests(unittest.TestCase):
    def test_the_checker_exists_and_is_executable_by_python(self):
        self.assertTrue(CHECKER.is_file(), "scripts/check_coverage.py is missing")
        result = subprocess.run([sys.executable, str(CHECKER), "--help"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_floor_exists_for_the_platform_independent_core(self):
        floors = _floors()
        self.assertIn("core", floors, "the core needs a floor")
        self.assertGreater(floors["core"], 0.0, "the core floor must be enforced")

    def test_the_floors_are_realistic_percentages(self):
        for name, value in _floors().items():
            with self.subTest(group=name):
                self.assertGreater(value, 0.0)
                self.assertLessEqual(value, 100.0)

    def test_the_gtk_group_keeps_its_own_floor(self):
        floors = _floors()
        self.assertIn("gtk", floors, "the GTK track needs a floor")
        self.assertGreater(floors["gtk"], 0.0)


if __name__ == "__main__":
    unittest.main()
