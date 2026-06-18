# Portable Media Viewer

Windows portable image/video browser.

## Download

For the ready-to-run portable build, download the latest release:

https://github.com/StynerPark/Mins-app/releases

## Run from source

Use `run.bat` for the script version, or run `PortableMediaViewer.exe` after building.

Install Python dependencies first:

```powershell
python -m pip install -r requirements.txt
```

For video playback, place a VLC/libVLC runtime folder named `vlc` next to `main.py`.
The `vlc` runtime is intentionally not committed to this repository.

Runtime settings are created as `settings.json` on first use. See
`settings.example.json` for the default structure.

## Build

```powershell
python build_exe.py
```

The build output is created under `dist/PortableMediaViewer`.

## Included Features

- Folder tree, preview panel, and folder contents browser
- Large/medium/small thumbnail, list, and details view modes
- Sorting by name, date, size, and type
- Image, animated GIF, WebP, and video entries in one mixed media order
- VLC/libVLC video playback with the bundled `vlc` runtime
- Double-click or Enter to open viewer mode
- Mouse wheel, PageUp/PageDown, Home/End navigation
- Middle mouse or F11 fullscreen toggle
- Single, double, triple, and webtoon viewer modes
- Fit height, fit width, fit window, actual size, manual zoom, and zoom lock
- Shortcut settings saved to `settings.json`
- Rename, new folder, and recycle-bin delete

## Notes

Source code and ready-to-run downloads are handled separately. Source files live
in this repository, while portable builds are attached to GitHub Releases.
