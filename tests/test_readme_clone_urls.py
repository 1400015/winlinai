"""The README points every installation at this repository."""
import unittest
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


class TestReadmeCloneUrls(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_no_linux_ai_clone(self):
        """The Linux installation methods clone this repo, not the old one."""
        self.assertNotIn("linux_ai.git", self.text)

    def test_windows_clone_is_winlinai(self):
        """The Windows section's clone stays winlinai.git."""
        self.assertIn("git clone https://github.com/1400015/winlinai.git", self.text)

    def test_every_clone_targets_this_repository(self):
        clones = [line.strip() for line in self.text.splitlines()
                  if line.strip().startswith("git clone ")]
        self.assertGreaterEqual(len(clones), 4)
        for line in clones:
            self.assertIn("https://github.com/1400015/winlinai.git", line)

    def test_cd_commands_match_the_repository(self):
        self.assertNotIn("cd linux_ai", self.text)


if __name__ == "__main__":
    unittest.main()
