# Portable Photo Viewer

Portable Photo Viewer is a Windows portable photo-first viewer and folder browser.
It is built for fast local photo browsing, full-screen viewing, webtoon-style
vertical reading, and Japanese manga-style two-page reading. Animated images and
common video files such as MP4 are supported as companion media, but the main
identity of the app is a photo viewer.

Portable Photo Viewer는 사진 감상 중심의 Windows 포터블 뷰어입니다. 빠른 폴더 탐색,
전체화면 감상, 웹툰형 세로 스크롤, 일본 만화식 2페이지 보기를 강점으로 합니다.
GIF/WebP/APNG 움짤과 MP4 같은 영상 파일도 함께 볼 수 있지만, 기본 성격은 사진
뷰어입니다.

## Download

Download the ready-to-run portable build from GitHub Releases:

https://github.com/StynerPark/Portable-image-Viewer/releases

Extract the zip file and run `PortableMediaViewer.exe`.

압축을 풀고 `PortableMediaViewer.exe`를 실행하면 됩니다.

## Supported Formats / 지원 확장자

Photo and image formats:

`jpg`, `jpeg`, `jpe`, `png`, `apng`, `bmp`, `gif`, `webp`, `avif`, `avifs`,
`tif`, `tiff`, `ico`, `jfif`, `ppm`, `pgm`, `pbm`, `pnm`, `jp2`, `j2k`,
`j2c`, `jpc`, `jpf`, `jpx`, `tga`, `icb`, `vda`, `vst`, `dds`, `psd`, `pcx`,
`qoi`, `sgi`, `rgb`, `rgba`, `bw`, `ras`, `xbm`, `xpm`

Animated image formats:

`gif`, `webp`, `apng`

Video formats:

`mp4`, `mkv`, `avi`, `mov`, `webm`, `wmv`, `flv`, `m4v`, `mpeg`, `mpg`, `ts`,
`m2ts`, `3gp`, `ogv`

Archive browsing:

`zip`

Notes:

- HEIC/HEIF is not enabled yet because the current bundled image stack does not
  include a HEIC decoder.
- PDF/SVG/EPS/WMF/EMF are intentionally not listed as photo formats yet because
  their behavior is closer to document/vector viewing than photo viewing.
- PSD support is intended for flattened preview-style viewing, not full layer
  editing.

## Main Features / 주요 기능

- Windows-style folder tree navigation
- Local folders, app-only shortcuts, and tabbed folder browsing
- Thumbnail, list, details, and icon-style explorer views
- Sort by name, size, type, modified date, and image properties
- Direct address input, including local paths and SMB/UNC paths such as `\\server`
- ZIP files open like folders for image viewing
- Viewer mode opens from double-click or `Enter`
- Full-screen photo viewing with mouse wheel/page navigation
- Drag-to-pan viewing when zoomed images are larger than the viewer
- Single, double, triple, and webtoon viewer modes
- Japanese manga-style double page order: `2,1 / 4,3`
- Webtoon mode with vertical continuous scrolling
- Webtoon auto-scroll with slow, normal, fast, and manual speed controls
- Webtoon loading optimized with visible-range priority, fixed target width, 4K
  width cap, scaled decoding, and memory cache
- GIF, animated WebP, and APNG support
- Video playback through VLC/libVLC with play/stop, seek, time, and volume controls
- Copy, paste, rename, delete, and recycle-bin deletion in explorer and viewer modes
- Light/dark theme
- Multi-instance and single-instance launch modes
- Portable settings saved next to the executable in `settings.json`

## Recent Improvements

- Improved double-click startup responsiveness by opening the selected media first
  and expanding the surrounding folder media list immediately after the viewer is shown.
- Kept mixed photo/video viewer stabilization intact while avoiding full folder
  media collection before the first viewer frame.
- Reduced white flashes and transient child-window artifacts during fast viewer navigation.
- Improved MP4 startup responsiveness on low-end PCs by prioritizing active playback before video thumbnail work.
- Delayed non-active split-view video thumbnail generation so playback can begin sooner.
- Skipped video files from adjacent viewer preload queues to reduce CPU and disk pressure while browsing quickly.
- Kept split-view video previews available while avoiding unnecessary first-load thumbnail extraction for the active video slot.

## Viewer Modes / 뷰어 모드

- `single`: one file at a time
- `double page`: `1,2 / 3,4`
- `double manga`: `2,1 / 4,3`
- `double slide`: `1,2 / 2,3 / 3,4`
- `triple page`: `1,2,3 / 4,5,6`
- `triple slide`: `1,2,3 / 2,3,4 / 3,4,5`
- `webtoon`: vertical continuous scrolling with optional auto-scroll

In webtoon mode, move the mouse to show the auto-scroll panel near the right
side of the viewer. The panel hides after a short idle delay. Auto-scroll can
also be toggled with `Ctrl+Space`, and using the mouse wheel stops auto-scroll.

In split modes, video files show a preview/first-frame style tile when they are
not the active playback slot. The active slot can play video while surrounding
items remain as previews.

## Opening Files / 파일 열기

- Launching the app normally opens the default Documents folder.
- Opening an associated image/video file from Windows opens directly in viewer mode.
- Leaving viewer mode returns to the folder that contains the opened file.
- Normal startup does not restore the last private folder, so previous photo
  locations are not exposed automatically.
- In `single` instance mode, opening another file while the app is already open
  reuses the existing window instead of starting another copy.

## Settings / 설정

The settings window is intentionally hidden from the main toolbar. Press `F1` to
open it.

설정창은 기본 화면에 버튼으로 노출하지 않습니다. `F1`을 누르면 열립니다.

You can change:

- Theme: `dark` or `light`
- Instance mode: `multi` or `single`
- Keyboard shortcuts
- Mouse shortcut tokens: `MouseMiddle`, `MouseBack`, `MouseForward`, `WheelUp`, `WheelDown`
- Multiple shortcuts for the same action

Some shortcut changes require restarting the app to rebuild bindings.

## Default Shortcuts / 기본 단축키

| Action | Default shortcut |
| --- | --- |
| Open viewer | `Enter` |
| Toggle fullscreen | `F11`, middle mouse button |
| Next file | mouse wheel down, `PageDown` |
| Previous file | mouse wheel up, `PageUp` |
| First file | `Home` |
| Last file | `End` |
| Next image with wrap | `Space` |
| Toggle webtoon auto-scroll | `Ctrl+Space` |
| Zoom in | `+`, `Ctrl++` |
| Zoom out | `-`, `Ctrl+-` |
| Fit height | `H` |
| Fit width | `W` |
| Actual size | `1` |
| Toggle zoom lock | `L` |
| Rotate right | `R` |
| Rotate left | `Shift+R` |
| Back | `Alt+Left`, mouse back button |
| Forward | `Alt+Right`, mouse forward button |
| Rename | `F2` |
| Copy | `Ctrl+C` |
| Paste | `Ctrl+V` |
| Delete | `Delete` |
| Open settings | `F1` |

In image viewer mode, `Space` moves to the next file and wraps from the last file
back to the first. During video playback, video play/pause behavior can take
priority.

## Portable Files / 포터블 구성

The portable release includes:

- `PortableMediaViewer.exe`
- `_internal`
- `vlc`
- `README.md`
- `settings.json`
- `settings.example.json`

Keep these files together. The VLC runtime is required for broad video playback.

## Run From Source

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Run:

```powershell
python main.py
```

For video playback, place a VLC/libVLC runtime folder named `vlc` next to
`main.py`.

## Build

```powershell
python build_exe.py
```

The build output is created under `dist/PortableMediaViewer`.

## Repository And Releases

Source code is published in this repository. Ready-to-run portable builds are
attached to GitHub Releases.
