# Photo Viewer v2.0.2 installer build

- Installer: `PhotoViewer_v2.0.2_Setup.exe`
- Supports per-user and all-users installation.
- Existing valid installations are removed before installing this version.
- Orphaned Photo Viewer uninstall registry entries no longer block a reinstall when the registered uninstaller file is missing.
- Settings are stored separately at `%LOCALAPPDATA%\Photo Viewer\2.0.2\settings.json`.
- If no v2.0.2 settings exist, v2.0.1 settings are copied without deleting the old file.
