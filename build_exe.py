import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
DIST = ROOT / "dist" / "PhotoViewer"
ICON = ROOT / "app.ico"
VERSION_FILE = ROOT / "version_info.txt"


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
            "--onedir",
            "--noconsole",
            "--name",
            "PhotoViewer",
            "--icon",
            str(ICON),
            "--version-file",
            str(VERSION_FILE),
            "--add-data",
            f"{ICON}{';' if sys.platform == 'win32' else ':'}.",
            str(ROOT / "main.py"),
        ], cwd=ROOT)
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
