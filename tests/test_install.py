import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("installer", Path(__file__).parents[1] / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.app = Path(self.tmp.name) / "Adobe After Effects 2026/Adobe After Effects 2026.app"
        (self.app / "Contents").mkdir(parents=True)
        (self.app / "Contents/Info.plist").write_text("fixture")
        (self.app.parent / "aerender").write_text("fixture")

    def test_installs_both_hosts_and_preserves_preferences(self):
        report = installer.install(self.home, self.app)
        self.assertEqual(report["after_effects"], "installed")
        self.assertTrue((self.app.parent / "Scripts/Resolve AE Bridge.jsx").is_file())
        target, scripts = installer.destinations(self.home)
        self.assertEqual(len(list(scripts.glob("*.py"))), 3)
        cfg = json.loads((target / "config.json").read_text())
        cfg["jobs_directory"] = "/my/custom/jobs"
        cfg["output_module"] = "My Custom ProRes"
        (target / "config.json").write_text(json.dumps(cfg))
        installer.install(self.home, self.app)
        updated = json.loads((target / "config.json").read_text())
        self.assertEqual(updated["jobs_directory"], "/my/custom/jobs")
        self.assertEqual(updated["output_module"], "My Custom ProRes")

    def test_absent_ae_is_explicitly_pending(self):
        with patch.object(installer, "find_after_effects", return_value=None):
            report = installer.install(self.home)
        self.assertEqual(report["after_effects"], "pending")
        self.assertTrue(report["warnings"])

    def test_invalid_app_rejected_before_install(self):
        with self.assertRaises(ValueError):
            installer.install(self.home, self.home / "absent.app")
        self.assertFalse(installer.destinations(self.home)[0].exists())

    def test_staging_never_copies_to_detected_host(self):
        with patch.object(installer, "find_after_effects", return_value=self.app):
            installer.install(self.home)
        self.assertFalse((self.app.parent / "Scripts").exists())
