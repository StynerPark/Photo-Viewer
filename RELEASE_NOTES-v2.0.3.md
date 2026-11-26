# Photo Viewer v2.0.3

This network-folder performance update removes avoidable UI stalls when browsing SMB shares through Tailscale or another high-latency connection.

- UNC folders no longer trigger delayed `QFileSystemModel` path selection on the GUI thread.
- Network directory rows reuse one standard folder icon instead of asking the Windows shell about every remote folder.
- Local folder tree selection, local shell icons, UI layout, menus, and shortcuts are unchanged.
- The v2.0.2 installer recovery, webtoon zoom, and FAST triple-GIF fixes remain included.
