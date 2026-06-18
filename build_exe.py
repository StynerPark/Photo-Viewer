import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
DIST = ROOT / "dist" / "PortableMediaViewer"
VLC_SRC = ROOT / "vlc"


def main():
    subprocess.check_call([
        str(PYTHON),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--noconsole",
        "--name",
        "PortableMediaViewer",
        str(ROOT / "main.py"),
    ], cwd=ROOT)
    if VLC_SRC.exists():
        target = DIST / "vlc"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(VLC_SRC, target)
    print(DIST)


if __name__ == "__main__":
    main()
