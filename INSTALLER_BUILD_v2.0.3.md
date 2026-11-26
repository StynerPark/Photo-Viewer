# Photo Viewer v2.0.3 installer build

- Installer: `PhotoViewer_v2.0.3_Setup.exe`
- Standalone Windows 10/11 x64 package; Python is not required on the target PC.
- Existing per-user or all-users Photo Viewer installations are removed before the selected scope is installed.
- Orphaned uninstall registry records do not block installation when their uninstaller file is already missing.
- Settings are stored separately at `%LOCALAPPDATA%\Photo Viewer\2.0.3\settings.json`.
- If no v2.0.3 settings exist, v2.0.2 settings are copied without deleting the old file.
- UNC folder opening avoids blocking tree synchronization and per-folder shell icon lookups.
