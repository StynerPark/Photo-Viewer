# Portable Media Viewer

> Built with assistance from OpenAI Codex.  
> OpenAI Codex의 도움을 받아 제작되었습니다.

Windows portable image/video browser.

Windows용 포터블 이미지/비디오 브라우저입니다.

## Screenshots / 스크린샷

![Portable Media Viewer browser](screenshots/browser.png)

Folder and thumbnail browser for quickly navigating local image collections.  
로컬 이미지 폴더를 빠르게 탐색할 수 있는 폴더 트리와 썸네일 브라우저 화면입니다.

![Portable Media Viewer viewing modes](screenshots/viewer-modes.png)

Viewer mode with single-image, two-page comic/book, three-page, and vertical webtoon-style layouts.  
단일 사진 보기, 2분할 만화책 보기, 3분할 보기, 세로 웹툰 스크롤 보기 모드를 지원하는 이미지 보기 화면입니다.

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
- Single-image viewer mode
- Two-page comic/book viewer mode with page and slideshow styles
- Three-page viewer mode with page and slideshow styles
- Vertical webtoon-style scrolling mode
- Fit height, fit width, fit window, actual size, manual zoom, and zoom lock
- Shortcut settings saved to `settings.json`
- Rename, new folder, and recycle-bin delete

## Notes

Source code and ready-to-run downloads are handled separately. Source files live
in this repository, while portable builds are attached to GitHub Releases.
