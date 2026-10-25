import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kiosk.launcher.display import open_display


class LauncherDisplayTests(unittest.TestCase):
    def test_available_chrome_precedes_edge_with_separate_user_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            edge = root / "msedge.exe"
            chrome = root / "chrome.exe"
            edge.touch()
            chrome.touch()
            with patch("kiosk.launcher.display.browser_candidates", return_value=[str(edge), str(chrome)]), patch("kiosk.launcher.display.user_directory", return_value=root), patch("kiosk.launcher.display.subprocess.Popen") as start:
                open_display("http://127.0.0.1:5000", "kiosk")
                arguments = start.call_args.args[0]
                self.assertEqual(arguments[0], str(chrome))
                self.assertIn("--start-fullscreen", arguments)
                self.assertIn("--user-data-dir=" + str(root / "browser/chrome"), arguments)
                chrome.unlink()
                open_display("http://127.0.0.1:5000", "admin")
                arguments = start.call_args.args[0]
                self.assertEqual(arguments[0], str(edge))
                self.assertNotIn("--start-fullscreen", arguments)
                self.assertIn("--user-data-dir=" + str(root / "browser/edge"), arguments)
                self.assertEqual(arguments[-1], "http://127.0.0.1:5000/admin/login")


if __name__ == "__main__":
    unittest.main()
