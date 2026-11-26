import unittest
from pathlib import Path


INSTALLER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "installer" / "PhotoViewer.iss"
)


class InstallerCleanReinstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER_SCRIPT.read_text(encoding="utf-8-sig")

    def test_prepare_to_install_removes_existing_builds_first(self):
        marker = "function PrepareToInstall(var NeedsRestart: Boolean): String;"
        prepare = self.script[self.script.index(marker) :]
        self.assertIn("RemoveAllExistingInstallations(Result);", prepare)

    def test_both_scopes_and_old_32_bit_machine_installs_are_covered(self):
        self.assertIn("HKEY_CURRENT_USER, UninstallRegistryKey", self.script)
        self.assertIn("HKEY_LOCAL_MACHINE, UninstallRegistryKey", self.script)
        self.assertIn("HKEY_LOCAL_MACHINE_32, UninstallRegistryKey", self.script)
        self.assertIn("LegacyUninstallRegistryKey", self.script)
        self.assertIn("RemoveMatchingInstallations", self.script)

    def test_old_viewer_is_closed_and_uninstalled_silently(self):
        self.assertIn("/F /T /IM {#AppExeName}", self.script)
        self.assertIn("/VERYSILENT /SUPPRESSMSGBOXES /NORESTART", self.script)
        self.assertIn("ewWaitUntilTerminated", self.script)

    def test_missing_uninstaller_is_treated_as_orphan_and_never_blocks_reinstall(self):
        start = self.script.index("if (Uninstaller = '') or (not FileExists(Uninstaller)) then")
        end = self.script.index("Parameters := '/VERYSILENT", start)
        orphan_branch = self.script[start:end]
        self.assertIn("RegDeleteKeyIncludingSubkeys(Root, RegistryKey)", orphan_branch)
        self.assertIn("installation will continue", orphan_branch)
        self.assertNotIn("Result := False", orphan_branch)
        self.assertNotIn("FailureMessage :=", orphan_branch)

    def test_leftover_registry_key_after_successful_uninstall_does_not_block(self):
        marker = "if RegKeyExists(Root, RegistryKey) then"
        start = self.script.index(marker, self.script.index("function RunRegisteredUninstaller"))
        end = self.script.index("end;", start) + len("end;")
        leftover_branch = self.script[start:end]
        self.assertIn("RegDeleteKeyIncludingSubkeys(Root, RegistryKey)", leftover_branch)
        self.assertNotIn("Result := False", leftover_branch)


if __name__ == "__main__":
    unittest.main()
