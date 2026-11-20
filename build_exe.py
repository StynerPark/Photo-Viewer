import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
DIST = ROOT / "dist" / "PhotoViewer"
SPEC_FILE = ROOT / "PhotoViewer.spec"


def sync_qt_msvc_runtime(dist_dir):
    """Keep Qt's required MSVC runtime ahead of Python's older bundled copy."""
    internal = dist_dir / "_internal"
    pyside = internal / "PySide6"
    names = (
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
        "MSVCP140.dll",
        "MSVCP140_1.dll",
        "MSVCP140_2.dll",
        "msvcp140_atomic_wait.dll",
    )
    copied = []
    for name in names:
        source = pyside / name
        if source.exists():
            target = internal / name
            shutil.copy2(source, target)
            copied.append(target)
    if not copied:
        raise RuntimeError(f"PySide6 MSVC runtime was not found under {pyside}")
    return copied


def remove_foreign_icu_runtime(dist_dir):
    """Do not ship ICU DLLs accidentally collected from tools on build PATH.

    Qt 6 on Windows links against the Windows ICU forwarding DLL. A Poppler
    or other third-party ICU build exports version-suffixed symbols instead
    and causes QtCore to fail with ERROR_PROC_NOT_FOUND on a clean launch.
    """
    internal = dist_dir / "_internal"
    removed = []
    for pattern in ("icuuc.dll", "icudt*.dll", "icuin*.dll"):
        for path in internal.glob(pattern):
            path.unlink()
            removed.append(path)
    return removed


def locate_vlc_source():
    configured = os.environ.get("PHOTO_VIEWER_VLC_SOURCE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.extend([ROOT / "vlc", DIST / "vlc"])
    for candidate in candidates:
        if (candidate / "libvlc.dll").exists() and (candidate / "plugins").is_dir():
            return candidate.resolve()
    return None


def generate_vlc_cache(vlc_dir):
    cache_gen = vlc_dir / "vlc-cache-gen.exe"
    plugins = vlc_dir / "plugins"
    if not cache_gen.exists():
        raise FileNotFoundError(f"Missing VLC cache generator: {cache_gen}")
    env = os.environ.copy()
    env["PATH"] = str(vlc_dir) + os.pathsep + env.get("PATH", "")
    subprocess.check_call([str(cache_gen), str(plugins)], env=env)
    cache = plugins / "plugins.dat"
    if not cache.exists() or cache.stat().st_size <= 0:
        raise RuntimeError(f"VLC plugin cache was not created: {cache}")
    return cache


def main():
    vlc_source = locate_vlc_source()
    if vlc_source is None:
        raise FileNotFoundError(
            "VLC runtime is required for a distributable build. "
            "Set PHOTO_VIEWER_VLC_SOURCE to a folder containing libvlc.dll "
            "and plugins, or place that runtime in dist\\PhotoViewer\\vlc."
        )
    with tempfile.TemporaryDirectory(prefix="photo-viewer-vlc-build-") as tempdir:
        staged_vlc = None
        if vlc_source is not None and DIST in vlc_source.parents:
            staged_vlc = Path(tempdir) / "vlc"
            shutil.copytree(vlc_source, staged_vlc)
            vlc_source = staged_vlc
        subprocess.check_call([
            str(PYTHON),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(SPEC_FILE),
        ], cwd=ROOT)
        for runtime in sync_qt_msvc_runtime(DIST):
            print(runtime)
        for runtime in remove_foreign_icu_runtime(DIST):
            print(f"removed incompatible ICU: {runtime}")
        if vlc_source is not None:
            target = DIST / "vlc"
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(vlc_source, target)
            cache = generate_vlc_cache(target)
            print(cache)
    print(DIST)


if __name__ == "__main__":
    main()
