import tempfile
import unittest
from pathlib import Path

import main


class InstallerSettingsTests(unittest.TestCase):
    def test_source_and_installed_builds_use_per_user_local_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            local_appdata = run_dir / "LocalAppData"
            self.assertEqual(
                main.resolve_settings_path(run_dir, local_appdata),
                local_appdata / main.APP_NAME / "settings.json",
            )

    def test_legacy_installed_settings_are_migrated_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_appdata = root / "Users" / "test" / "AppData" / "Local"
            legacy = local_appdata / main.LEGACY_APP_NAME / "settings.json"
            target = local_appdata / main.APP_NAME / "settings.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"theme":"dark"}', encoding="utf-8")

            self.assertTrue(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"theme":"dark"}')
            target.write_text('{"theme":"light"}', encoding="utf-8")
            self.assertFalse(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"theme":"light"}')


if __name__ == "__main__":
    unittest.main()
