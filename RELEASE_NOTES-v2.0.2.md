# Photo Viewer v2.0.2

This installer reliability update fixes reinstalls after the application folder was removed manually.

- A missing registered uninstaller is treated as an orphaned Photo Viewer record instead of a fatal installation error.
- The installer attempts to remove verified orphaned uninstall keys but continues when another install scope cannot be cleaned because of permissions.
- A successful uninstaller run followed by a leftover registry key is also treated as stale metadata.
- Failure to start a real uninstaller or a non-zero uninstall exit code still stops installation to avoid overwriting locked or partially removed files.
- Webtoon view now redraws visible images at the new scale when the `+` or `-` shortcut is used.
- Triple-page mode now grants one playback worker to each visible animated image, so the third GIF also advances under the FAST performance profile.
- The existing UI, menus, and shortcut assignments remain unchanged.
