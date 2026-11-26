import tempfile
import unittest
from pathlib import Path

import main


class InstallerSettingsTests(unittest.TestCase):
    def test_version_is_2_0_3(self):
        self.assertEqual(main.APP_VERSION, "2.0.3")

    def test_source_and_installed_builds_use_versioned_per_user_local_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            local_appdata = run_dir / "LocalAppData"
            self.assertEqual(
                main.resolve_settings_path(run_dir, local_appdata),
                local_appdata / main.APP_NAME / main.APP_VERSION / "settings.json",
            )

    def test_unversioned_settings_are_migrated_once_and_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_appdata = root / "Users" / "test" / "AppData" / "Local"
            legacy = local_appdata / main.APP_NAME / "settings.json"
            target = local_appdata / main.APP_NAME / main.APP_VERSION / "settings.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"theme":"dark"}', encoding="utf-8")

            self.assertTrue(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"theme":"dark"}')
            self.assertEqual(legacy.read_text(encoding="utf-8"), '{"theme":"dark"}')
            target.write_text('{"theme":"light"}', encoding="utf-8")
            self.assertFalse(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"theme":"light"}')

    def test_v2_0_2_settings_are_copied_without_removing_the_old_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = Path(temp_dir) / "Local"
            old = local_appdata / main.APP_NAME / "2.0.2" / "settings.json"
            target = local_appdata / main.APP_NAME / main.APP_VERSION / "settings.json"
            old.parent.mkdir(parents=True)
            old.write_text('{"theme":"light","custom":17}', encoding="utf-8")

            self.assertTrue(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_bytes(), old.read_bytes())
            self.assertTrue(old.exists())

    def test_old_product_settings_are_used_when_unversioned_settings_do_not_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_appdata = root / "Users" / "test" / "AppData" / "Local"
            legacy = local_appdata / main.LEGACY_APP_NAME / "settings.json"
            target = local_appdata / main.APP_NAME / main.APP_VERSION / "settings.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text('{"theme":"legacy"}', encoding="utf-8")

            self.assertTrue(main.migrate_legacy_settings(target, local_appdata))
            self.assertEqual(target.read_text(encoding="utf-8"), '{"theme":"legacy"}')


if __name__ == "__main__":
    unittest.main()
