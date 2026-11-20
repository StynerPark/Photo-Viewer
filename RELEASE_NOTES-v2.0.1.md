# Photo Viewer v2.0.1

This release preserves the existing interface and adds two image file operations to the explorer context menu.

- Convert Format: JPG, PNG, WebP, AVIF, BMP, and TIFF with format-specific quality controls and estimated output size.
- Rotate Image: permanently rotates and overwrites selected still-image files after explicit confirmation.
- Default shortcuts: `Ctrl+Shift+F` and `Ctrl+Shift+R`; both are visible in the context menu and editable in Settings.
- All writes use a temporary file in the destination folder and replace the final file only after a successful encode.
- Animated images and archive-internal virtual items are excluded to prevent unintended frame loss.
- Fixed clean-install startup failures caused by the ImageQt import order and incompatible ICU/MSVC DLLs collected from the build environment.
