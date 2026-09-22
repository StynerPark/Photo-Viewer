# Photo Viewer v2.0.0 installer build

- Installer: `PhotoViewer_v2.0.0_Setup.exe`
- Target: Windows 10/11 x64
- Packaging: PyInstaller one-folder application bundled with VLC, wrapped by Inno Setup
- The installer is self-contained and does not require a separate Python installation.
- Existing user settings are preserved; the installer excludes runtime `settings.json` files.
- Settings coexist by version under `%LocalAppData%\Photo Viewer\<version>\settings.json`.
- Before installation, existing per-user and all-users Photo Viewer installations are removed, regardless of version, and the selected scope is installed cleanly.
