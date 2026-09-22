import json
import math
import os
import queue
import re
import shutil
import stat as stat_module
import subprocess
import sys
import ctypes
import tempfile
import threading
import time
import zipfile
import copy
from collections import deque
import bisect
from io import BytesIO
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

APP_NAME = "Photo Viewer"
APP_VERSION = "2.0.0"
LEGACY_APP_NAME = "Portable Photo Viewer"
INSTANCE_SERVER_NAME = "StynerPark_PhotoViewer_Instance"
DEFAULT_LAST_FOLDER_SETTING = r"%USERPROFILE%\Documents"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUN_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def resolve_settings_path(run_dir=None, local_appdata=None):
    if local_appdata is None:
        local_appdata = os.environ.get("LOCALAPPDATA")
    settings_root = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return settings_root / APP_NAME / APP_VERSION / "settings.json"


def migrate_legacy_settings(settings_path=None, local_appdata=None):
    target = Path(settings_path) if settings_path is not None else resolve_settings_path(
        local_appdata=local_appdata
    )
    if target.exists():
        return False
    if local_appdata is None:
        local_appdata = os.environ.get("LOCALAPPDATA")
    settings_root = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    legacy_candidates = (
        settings_root / APP_NAME / "settings.json",
        settings_root / LEGACY_APP_NAME / "settings.json",
    )
    for legacy in legacy_candidates:
        if not legacy.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        return True
    return False


SETTINGS_PATH = resolve_settings_path()
VLC_DIR = RUN_DIR / "vlc"
if not VLC_DIR.exists():
    VLC_DIR = BASE_DIR / "vlc"

VLC_DLL_DIRECTORY_HANDLE = None
if VLC_DIR.exists():
    os.environ["PATH"] = str(VLC_DIR) + os.pathsep + os.environ.get("PATH", "")
    vlc_plugins = VLC_DIR / "plugins"
    if vlc_plugins.exists():
        os.environ["VLC_PLUGIN_PATH"] = str(vlc_plugins)
    vlc_library = VLC_DIR / "libvlc.dll"
    if vlc_library.exists():
        os.environ["PYTHON_VLC_LIB_PATH"] = str(vlc_library)
    if hasattr(os, "add_dll_directory"):
        VLC_DLL_DIRECTORY_HANDLE = os.add_dll_directory(str(VLC_DIR))

DEFAULT_START_FOLDER = Path.home() / "Documents"
if not DEFAULT_START_FOLDER.exists():
    DEFAULT_START_FOLDER = Path.home()

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QBuffer,
    QByteArray,
    QDir,
    QEvent,
    QFileInfo,
    QFileSystemWatcher,
    QMimeData,
    QObject,
    QPoint,
    QRect,
    QRunnable,
    QSize,
    QThreadPool,
    QThread,
    Qt,
    QTimer,
    QUrl,
    QIODevice,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QFontMetrics, QIcon, QImage, QImageReader, QIntValidator, QKeySequence, QMovie, QPainter, QPalette, QPen, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileIconProvider,
    QFileSystemModel,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

try:
    import vlc
except Exception:
    vlc = None


if vlc is not None:
    class _VlcMediaTrackUnion(ctypes.Union):
        _fields_ = [
            ("audio", ctypes.POINTER(vlc.AudioTrack)),
            ("video", ctypes.POINTER(vlc.VideoTrack)),
            ("subtitle", ctypes.POINTER(vlc.SubtitleTrack)),
        ]


    class _VlcMediaTrack(ctypes.Structure):
        # python-vlc 3.0.21203 models the C union as three consecutive
        # pointers.  VLC 3.x uses a real union, so use the native layout when
        # reading SAR and orientation from libvlc_media_tracks_get().
        _fields_ = [
            ("codec", ctypes.c_uint32),
            ("original_fourcc", ctypes.c_uint32),
            ("id", ctypes.c_int),
            ("type", vlc.TrackType),
            ("profile", ctypes.c_int),
            ("level", ctypes.c_int),
            ("track", _VlcMediaTrackUnion),
            ("bitrate", ctypes.c_uint),
            ("language", ctypes.c_char_p),
            ("description", ctypes.c_char_p),
        ]


IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".apng", ".bmp", ".gif", ".webp",
    ".avif", ".avifs", ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm",
    ".pnm", ".jfif", ".jp2", ".j2k", ".j2c", ".jpc", ".jpf", ".jpx",
    ".tga", ".icb", ".vda", ".vst", ".dds", ".psd", ".pcx", ".qoi",
    ".sgi", ".rgb", ".rgba", ".bw", ".ras", ".xbm", ".xpm",
}
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
    ".mpeg", ".mpg", ".ts", ".m2ts", ".3gp", ".ogv",
}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
ARCHIVE_EXTS = {".zip"}
WEBTOON_MIN_WIDTH = 320
WEBTOON_MAX_WIDTH = 3840
WEBTOON_AUTO_SCROLL_SPEEDS = {
    "slow": 60,
    "normal": 120,
    "fast": 240,
}
WEBTOON_AUTO_SCROLL_MIN_SPEED = 10
WEBTOON_AUTO_SCROLL_MAX_SPEED = 1000

PERFORMANCE_PROFILES = {
    "conservative": {"thumbnail_workers": 1, "thumbnail_start_ms": 150, "thumbnail_gap_ms": 100},
    "balanced": {"thumbnail_workers": 2, "thumbnail_start_ms": 100, "thumbnail_gap_ms": 50},
    "fast": {"thumbnail_workers": 3, "thumbnail_start_ms": 80, "thumbnail_gap_ms": 30},
}


@dataclass(frozen=True)
class PerformancePolicy:
    """Runtime limits used by the existing performance-profile control.

    The visible settings and their labels remain unchanged.  ``balanced`` is
    the normal-user policy (16 GB RAM / 6 cores / 12 threads class hardware),
    while ``conservative`` is the optional low-spec policy.  Keeping these
    values in one immutable object prevents individual workers from silently
    choosing conflicting limits.
    """

    name: str
    low_spec: bool
    thumbnail_workers: int
    thumbnail_start_ms: int
    thumbnail_gap_ms: int
    viewer_decode_workers: int
    animation_workers: int
    viewer_cache_limit_bytes: int
    webtoon_cache_limit_bytes: int
    thumbnail_cache_limit_bytes: int
    max_animated_frame_pixels: int
    video_standby_target: int
    viewer_lookahead: int
    webtoon_lookahead: int
    idle_webtoon_preload: bool
    decode_dimension_limit: int


# Existing PERFORMANCE_PROFILES is intentionally retained for compatibility
# with settings files and integrations.  The richer policy below is internal;
# it does not add or remove a settings-widget row.
PERFORMANCE_POLICIES = {
    "conservative": PerformancePolicy(
        name="conservative",
        low_spec=True,
        thumbnail_workers=1,
        thumbnail_start_ms=150,
        thumbnail_gap_ms=100,
        viewer_decode_workers=1,
        animation_workers=1,
        viewer_cache_limit_bytes=64 * 1024 * 1024,
        webtoon_cache_limit_bytes=96 * 1024 * 1024,
        thumbnail_cache_limit_bytes=64 * 1024 * 1024,
        max_animated_frame_pixels=4 * 1024 * 1024,
        video_standby_target=1,
        viewer_lookahead=0,
        webtoon_lookahead=1,
        idle_webtoon_preload=False,
        decode_dimension_limit=3072,
    ),
    "balanced": PerformancePolicy(
        name="balanced",
        low_spec=False,
        thumbnail_workers=2,
        thumbnail_start_ms=100,
        thumbnail_gap_ms=50,
        viewer_decode_workers=2,
        animation_workers=3,
        viewer_cache_limit_bytes=128 * 1024 * 1024,
        webtoon_cache_limit_bytes=192 * 1024 * 1024,
        thumbnail_cache_limit_bytes=128 * 1024 * 1024,
        max_animated_frame_pixels=16 * 1024 * 1024,
        video_standby_target=3,
        viewer_lookahead=1,
        webtoon_lookahead=2,
        idle_webtoon_preload=True,
        decode_dimension_limit=4096,
    ),
    "fast": PerformancePolicy(
        name="fast",
        low_spec=False,
        thumbnail_workers=3,
        thumbnail_start_ms=80,
        thumbnail_gap_ms=30,
        viewer_decode_workers=3,
        animation_workers=2,
        viewer_cache_limit_bytes=160 * 1024 * 1024,
        webtoon_cache_limit_bytes=256 * 1024 * 1024,
        thumbnail_cache_limit_bytes=160 * 1024 * 1024,
        max_animated_frame_pixels=24 * 1024 * 1024,
        video_standby_target=4,
        viewer_lookahead=2,
        webtoon_lookahead=3,
        idle_webtoon_preload=True,
        decode_dimension_limit=5120,
    ),
}


def performance_policy_for(settings):
    """Return a validated runtime policy without changing the settings UI."""
    profile = str((settings or {}).get("performance_profile", "balanced")).lower()
    if profile not in PERFORMANCE_POLICIES:
        profile = "balanced"
    # ``low_spec_mode`` is intentionally a backwards-compatible, hidden JSON
    # switch.  Existing users keep the same visible controls, while advanced
    # deployments can force the conservative lifecycle limits independently.
    if bool((settings or {}).get("low_spec_mode", False)):
        profile = "conservative"
    return PERFORMANCE_POLICIES[profile]

VIEWER_CACHE_LIMIT_BYTES = 128 * 1024 * 1024
WEBTOON_CACHE_LIMIT_BYTES = 192 * 1024 * 1024
THUMBNAIL_CACHE_LIMIT_BYTES = 128 * 1024 * 1024
MAX_ANIMATED_FRAME_PIXELS = 16 * 1024 * 1024
THUMBNAIL_WHEEL_ROWS = 3
THUMBNAIL_TOUCHPAD_SCALE = 2.0
PLAYBACK_RATE_PRESETS = (0.25, 0.5, 0.75, 1.0, 2.0)
PLAYBACK_RATE_MIN = 0.1
PLAYBACK_RATE_MAX = 4.0
VIDEO_INITIAL_PLAYER_TARGET = 1
VIDEO_STANDBY_TARGET = 6
VIDEO_MAX_FRAMES_PER_SLOT = 3
VIDEO_CLEANUP_IDLE_MS = 15
VIDEO_READY_TIMEOUT_MS = 8000
VIDEO_START_TIMEOUT_MS = 5000
VLC_INSTANCE_ARGS = (
    "--quiet",
)

VIEWER_POPUP_MENU_STYLE = """
    QMenu {
        background: #211e29;
        color: #f5f1fc;
        border: 1px solid #5d5275;
        border-radius: 7px;
        padding: 5px;
    }
    QMenu::item {
        background: transparent;
        color: #f5f1fc;
        min-width: 92px;
        padding: 6px 22px 6px 12px;
        border-radius: 5px;
    }
    QMenu::item:selected { background: #7560b4; color: #ffffff; }
    QMenu::item:disabled { color: #858091; }
    QMenu::separator { height: 1px; background: #4b445d; margin: 4px 7px; }
"""

VIEWER_COMBO_POPUP_STYLE = """
    QAbstractItemView {
        background-color: #211e29;
        color: #f5f1fc;
        border: 1px solid #5d5275;
        border-radius: 7px;
        outline: 0;
        padding: 4px;
        selection-background-color: #7560b4;
        selection-color: #ffffff;
    }
    QAbstractItemView::item {
        background-color: #211e29;
        color: #f5f1fc;
        min-height: 26px;
        padding: 3px 10px;
        border-radius: 5px;
    }
    QAbstractItemView::item:hover,
    QAbstractItemView::item:selected {
        background-color: #7560b4;
        color: #ffffff;
    }
"""


DEFAULT_SETTINGS = {
    "last_folder": DEFAULT_LAST_FOLDER_SETTING,
    "view_mode": "large",
    "sort_mode": "name_asc",
    "viewer_mode": "single",
    "default_viewer_mode": "single",
    "viewer_start_mode": "fullscreen",
    "viewer_step": "page",
    "video_loop_enabled": False,
    "default_fit": "fit_height",
    "zoom_locked": True,
    "theme": "dark",
    "instance_mode": "multi",
    "performance_profile": "balanced",
    # Internal policy switch; no new UI control is introduced so the existing
    # layout/right-click/shortcut surface remains unchanged.
    "low_spec_mode": False,
    "webtoon_auto_scroll_speed_mode": "normal",
    "webtoon_auto_scroll_manual_speed": 120,
    "quick_paths": [],
    "geometry": {},
    "shortcuts": {
        "open_viewer": ["Return"],
        "toggle_fullscreen": ["F11", "MouseMiddle"],
        "next_media": ["PageDown", "WheelDown"],
        "previous_media": ["PageUp", "WheelUp"],
        "first_media": ["Home"],
        "last_media": ["End"],
        "zoom_in": ["+"],
        "zoom_out": ["-"],
        "fit_height": ["N"],
        "fit_width": ["M"],
        "fit_window": [","],
        "actual_size": ["."],
        "toggle_zoom_lock": ["/"],
        "toggle_play": [],
        "viewer_single": ["S"],
        "viewer_double": ["D"],
        "viewer_triple": ["T"],
        "viewer_webtoon": ["W"],
        "rotate_right": ["]"],
        "rotate_left": ["["],
        "reset_rotation": ["\\"],
        "back": ["Alt+Left"],
        "forward": ["Alt+Right"],
        "rename": ["F2"],
        "delete": ["Delete"],
    },
}


def deep_merge(base, loaded):
    result = dict(base)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings():
    if SETTINGS_PATH.exists():
        try:
            return deep_merge(DEFAULT_SETTINGS, json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            return dict(DEFAULT_SETTINGS)
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    """Persist settings atomically so a forced shutdown cannot corrupt JSON."""
    temp_name = None
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(SETTINGS_PATH.parent),
            prefix=f".{SETTINGS_PATH.stem}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, SETTINGS_PATH)
        return True
    except Exception:
        # Settings are best-effort; a read-only profile must not prevent the
        # viewer from starting or closing.  Remove only the temporary file we
        # created, never the user's existing settings.
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass
        return False


def natural_sort_key(value):
    """Return a case-insensitive key that compares digit runs numerically."""
    parts = []
    for token in re.split(r"(\d+)", str(value).casefold()):
        if not token:
            continue
        if token.isdigit():
            # Shorter digit runs win when the numeric value is equal:
            # 1.jpg, 01.jpg, 001.jpg.
            parts.append((0, int(token), len(token)))
        else:
            parts.append((1, token))
    return tuple(parts)


def is_image(path):
    return Path(path).suffix.lower() in IMAGE_EXTS


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


def is_media(path):
    return Path(path).suffix.lower() in MEDIA_EXTS


def is_archive(path):
    return Path(path).suffix.lower() in ARCHIVE_EXTS


def normalize_playback_rate(value):
    try:
        text = str(value).strip().lower()
        if text.endswith("x"):
            text = text[:-1].strip()
        rate = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate) or not PLAYBACK_RATE_MIN <= rate <= PLAYBACK_RATE_MAX:
        return None
    return round(rate, 3)


def format_playback_rate(value):
    rate = normalize_playback_rate(value)
    if rate is None:
        rate = 1.0
    if math.isclose(rate, round(rate), abs_tol=0.0005):
        return f"{rate:.1f}x"
    return f"{rate:.3f}".rstrip("0").rstrip(".") + "x"


def animated_webp_frame_durations(path):
    """Return ANMF frame durations without decoding the complete WebP image."""
    path = Path(path)
    if path.suffix.lower() != ".webp":
        return []
    durations = []
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WEBP":
                return []
            while True:
                chunk_header = handle.read(8)
                if len(chunk_header) < 8:
                    break
                chunk_type = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:8], "little")
                if chunk_type == b"ANMF" and chunk_size >= 16:
                    frame_header = handle.read(16)
                    durations.append(max(10, int.from_bytes(frame_header[12:15], "little") or 80))
                    handle.seek(chunk_size - 16, os.SEEK_CUR)
                else:
                    handle.seek(chunk_size, os.SEEK_CUR)
                if chunk_size & 1:
                    handle.seek(1, os.SEEK_CUR)
    except (OSError, ValueError):
        return []
    return durations


def unc_server_name(text):
    value = str(text).strip().strip('"').replace("/", "\\")
    if not value.startswith("\\\\"):
        return ""
    value = value.rstrip("\\")
    rest = value[2:]
    if not rest or "\\" in rest:
        return ""
    return rest


def unc_share_paths(server):
    class SHARE_INFO_1(ctypes.Structure):
        _fields_ = [
            ("shi1_netname", wintypes.LPWSTR),
            ("shi1_type", wintypes.DWORD),
            ("shi1_remark", wintypes.LPWSTR),
        ]

    netapi32 = ctypes.WinDLL("Netapi32.dll")
    buf = ctypes.c_void_p()
    entries_read = wintypes.DWORD()
    total_entries = wintypes.DWORD()
    resume = wintypes.DWORD(0)
    result = netapi32.NetShareEnum(
        wintypes.LPWSTR(server),
        wintypes.DWORD(1),
        ctypes.byref(buf),
        wintypes.DWORD(-1),
        ctypes.byref(entries_read),
        ctypes.byref(total_entries),
        ctypes.byref(resume),
    )
    if result != 0:
        return []
    shares = []
    try:
        array_type = SHARE_INFO_1 * entries_read.value
        shares_array = ctypes.cast(buf, ctypes.POINTER(array_type)).contents
        for share in shares_array:
            if share.shi1_type == 0 and share.shi1_netname not in ("ADMIN$", "IPC$"):
                shares.append((share.shi1_netname, Path(f"\\\\{server}\\{share.shi1_netname}")))
    finally:
        netapi32.NetApiBufferFree(buf)
    return shares


def file_label(path):
    return Path(path).name


def breadcrumb_text(path):
    path = Path(path)
    parts = list(path.parts)
    if not parts:
        return str(path)
    if parts[0].endswith("\\"):
        drive = parts[0].rstrip("\\")
        label_parts = ["내 PC", f"로컬 디스크 ({drive})"] + [p for p in parts[1:] if p not in ("\\", "")]
    else:
        label_parts = parts
    return "  >  ".join(label_parts)


def image_properties(path):
    if is_video(path):
        return ""
    try:
        with Image.open(path) as img:
            bits = len(img.getbands()) * 8
            return f"{img.width}x{img.height}x{bits}b"
    except Exception:
        return ""


def image_type(path):
    if Path(path).is_dir():
        return "Folder"
    if is_video(path):
        return "Video"
    try:
        with Image.open(path) as img:
            return img.format or Path(path).suffix.upper().strip(".")
    except Exception:
        return Path(path).suffix.upper().strip(".")


TYPE_BADGE_COLORS = {
    "jpeg": "#a2ad45",
    "png": "#b96e63",
    "webp": "#7d9850",
    "gif": "#48a66a",
    "video": "#4e9db1",
    "raster": "#b38a4b",
    "other": "#80788f",
}

TYPE_ROW_COLORS = {
    "light": {
        "jpeg": "#f0f2d8",
        "png": "#f5e2df",
        "webp": "#e7eedb",
        "gif": "#dff1e5",
        "video": "#deedf1",
        "raster": "#f2e8d8",
        "other": "#eeebf1",
    },
    "dark": {
        "jpeg": "#343724",
        "png": "#3a292d",
        "webp": "#2c3528",
        "gif": "#24372c",
        "video": "#26383f",
        "raster": "#3a3127",
        "other": "#302c37",
    },
}


def type_color_key(path, is_dir_entry=False):
    if is_dir_entry or is_archive(path):
        return None
    ext = Path(path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".jpe", ".jfif"}:
        return "jpeg"
    if ext in {".png", ".apng"}:
        return "png"
    if ext == ".webp":
        return "webp"
    if ext == ".gif":
        return "gif"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in {".bmp", ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm", ".pnm"}:
        return "raster"
    return "other"


def type_color(path, is_dir_entry=False, dark_theme=False):
    color_key = type_color_key(path, is_dir_entry)
    if color_key is None:
        return None
    theme = "dark" if dark_theme else "light"
    return QColor(TYPE_ROW_COLORS[theme][color_key])


def type_badge_color(path, is_dir_entry=False):
    color_key = type_color_key(path, is_dir_entry)
    if color_key is None:
        return None
    return QColor(TYPE_BADGE_COLORS[color_key])


def extension_badge_text(path, is_dir_entry=False):
    if is_dir_entry or is_archive(path) or not is_media(path):
        return ""
    return Path(path).suffix.upper().lstrip(".")


def contrasting_text_color(background):
    def linear_channel(value):
        value = value / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = (
        0.2126 * linear_channel(background.red())
        + 0.7152 * linear_channel(background.green())
        + 0.0722 * linear_channel(background.blue())
    )
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return QColor("#17131d" if black_contrast >= white_contrast else "#ffffff")


def fmt_modified(path):
    try:
        from datetime import datetime
        return datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def fmt_timestamp(value):
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def app_icon():
    icon_path = BASE_DIR / "app.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    if getattr(sys, "frozen", False):
        icon = QIcon(str(sys.executable))
        if not icon.isNull():
            return icon
    pix = QPixmap(32, 32)
    pix.fill(QColor("#1f6fd1"))
    painter = QPainter(pix)
    painter.fillRect(5, 5, 22, 22, QColor("#f4f7fb"))
    painter.fillRect(8, 17, 7, 7, QColor("#4aa3ff"))
    painter.fillRect(15, 12, 9, 12, QColor("#5bc878"))
    painter.fillRect(8, 8, 6, 6, QColor("#ffcf4a"))
    painter.end()
    return QIcon(pix)


@dataclass
class MediaItem:
    path: Path
    is_dir: bool = False
    label: str = ""
    size: int = 0
    mtime: float = 0.0
    image_size: tuple = ()

    @property
    def kind(self):
        if self.is_dir:
            return "folder"
        if is_video(self.path):
            return "video"
        if is_image(self.path):
            return "image"
        return "other"

    @property
    def display_name(self):
        return self.label or self.path.name or str(self.path)


@dataclass
class FolderSnapshot:
    path: Path
    entries: list
    signature: tuple


class ArchiveSession:
    """Metadata session for a ZIP with independent member readers.

    ``ZipFile.open`` is not safe to share while several viewer/thumbnail
    workers are active.  Metadata remains on the session handle, but each
    member read opens its own short-lived handle so one slow image cannot
    serialize every other image request.
    """

    def __init__(self, archive_path):
        self.archive_path = str(archive_path)
        self._lock = threading.RLock()
        self._archive = zipfile.ZipFile(self.archive_path)
        self._closed = False

    def image_members(self):
        with self._lock:
            if self._closed:
                return []
            return [
                info
                for info in self._archive.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() in IMAGE_EXTS
            ]

    def read_member(self, member_name, cancel_check=None):
        chunks = []
        with self._lock:
            if self._closed:
                raise RuntimeError("Archive session is closed")
            archive_path = self.archive_path
        # Do not hold the session lock during decompression.  A separate
        # handle gives concurrent decode tasks independent file pointers and
        # also makes cancellation responsive between chunks.
        with zipfile.ZipFile(archive_path, "r") as archive:
            with archive.open(member_name) as source:
                while True:
                    if cancel_check is not None and cancel_check():
                        raise InterruptedError
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
        return b"".join(chunks)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._archive.close()


@dataclass(frozen=True)
class ArchiveMemberSource:
    session: object
    member_name: str

    def read(self, cancel_check=None):
        return self.session.read_member(self.member_name, cancel_check=cancel_check)


class DecodeSignals(QObject):
    finished = Signal(int, str, object, object)


class ImageDecodeTask(QRunnable):
    def __init__(
        self,
        generation,
        path,
        max_size,
        canvas_size=None,
        video_shell=False,
        thread_priority=QThread.LowPriority,
        archive_source=None,
        render_token=0,
        cache_key=None,
    ):
        super().__init__()
        self.generation = int(generation)
        self.path = str(path)
        self.max_size = tuple(max_size)
        self.canvas_size = tuple(canvas_size) if canvas_size else None
        self.video_shell = bool(video_shell)
        self.thread_priority = thread_priority
        self.archive_source = archive_source
        self.render_token = int(render_token)
        self.cache_key = cache_key
        self.cancelled = False
        self.signals = DecodeSignals()

    def cancel(self):
        self.cancelled = True

    def run(self):
        payload = None
        metadata = {"render_token": self.render_token, "cache_key": self.cache_key}
        try:
            if self.cancelled:
                raise InterruptedError
            QThread.currentThread().setPriority(self.thread_priority)
            path = Path(self.path)
            if self.video_shell:
                payload = windows_shell_thumbnail_image(path, max(self.max_size))
            elif self.archive_source is not None:
                source_bytes = self.archive_source.read(cancel_check=lambda: self.cancelled)
                if self.cancelled:
                    raise InterruptedError
                byte_array = QByteArray(source_bytes)
                buffer = QBuffer()
                buffer.setData(byte_array)
                if not buffer.open(QIODevice.ReadOnly):
                    raise OSError("Cannot open archive image buffer")
                reader = QImageReader(buffer)
                source_size = reader.size()
                if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                    metadata.update({
                        "image_size": (source_size.width(), source_size.height()),
                        "image_format": bytes(reader.format()).decode("ascii", errors="ignore").upper(),
                        "animated": bool(reader.supportsAnimation() and reader.imageCount() != 1),
                        "frame_count": max(1, int(reader.imageCount() or 1)),
                    })
                    max_width = max(1, int(self.max_size[0]))
                    max_height = max(1, int(self.max_size[1]))
                    scale = min(1.0, max_width / source_size.width(), max_height / source_size.height())
                    if scale < 1.0:
                        reader.setScaledSize(QSize(
                            max(1, int(source_size.width() * scale)),
                            max(1, int(source_size.height() * scale)),
                        ))
                    image = reader.read()
                    if not image.isNull():
                        if self.canvas_size:
                            canvas = QImage(
                                max(1, int(self.canvas_size[0])),
                                max(1, int(self.canvas_size[1])),
                                QImage.Format_ARGB32,
                            )
                            canvas.fill(QColor("#050505"))
                            scaled = image.scaled(canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            painter = QPainter(canvas)
                            painter.drawImage(
                                (canvas.width() - scaled.width()) // 2,
                                (canvas.height() - scaled.height()) // 2,
                                scaled,
                            )
                            painter.end()
                            payload = canvas
                        else:
                            payload = image
                if payload is None:
                    with Image.open(BytesIO(source_bytes)) as source:
                        frame_count = max(1, int(getattr(source, "n_frames", 1) or 1))
                        metadata.update({
                            "image_size": (int(source.width), int(source.height)),
                            "image_format": str(source.format or path.suffix.upper().strip(".")),
                            "animated": bool(getattr(source, "is_animated", False) and frame_count > 1),
                            "frame_count": frame_count,
                        })
                        if getattr(source, "is_animated", False):
                            source.seek(0)
                        image = source.convert("RGBA")
                        image.thumbnail(self.max_size, Image.Resampling.LANCZOS)
                        if self.canvas_size:
                            canvas = Image.new("RGBA", self.canvas_size, (0, 0, 0, 255))
                            canvas.alpha_composite(
                                image,
                                ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2),
                            )
                            image = canvas
                        data = BytesIO()
                        image.save(data, format="PNG", optimize=False)
                        payload = data.getvalue()
            else:
                reader = QImageReader(str(path))
                source_size = reader.size()
                if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                    metadata.update({
                        "image_size": (source_size.width(), source_size.height()),
                        "image_format": bytes(reader.format()).decode("ascii", errors="ignore").upper(),
                        "animated": bool(reader.supportsAnimation() and reader.imageCount() != 1),
                        "frame_count": max(1, int(reader.imageCount() or 1)),
                    })
                    max_width = max(1, int(self.max_size[0]))
                    max_height = max(1, int(self.max_size[1]))
                    scale = min(1.0, max_width / source_size.width(), max_height / source_size.height())
                    if scale < 1.0:
                        reader.setScaledSize(QSize(
                            max(1, int(source_size.width() * scale)),
                            max(1, int(source_size.height() * scale)),
                        ))
                    if self.cancelled:
                        raise InterruptedError
                    image = reader.read()
                    if not image.isNull():
                        if self.cancelled:
                            raise InterruptedError
                        if self.canvas_size:
                            canvas = QImage(
                                max(1, int(self.canvas_size[0])),
                                max(1, int(self.canvas_size[1])),
                                QImage.Format_ARGB32,
                            )
                            canvas.fill(QColor("#050505"))
                            scaled = image.scaled(
                                canvas.size(),
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation,
                            )
                            painter = QPainter(canvas)
                            painter.drawImage(
                                (canvas.width() - scaled.width()) // 2,
                                (canvas.height() - scaled.height()) // 2,
                                scaled,
                            )
                            painter.end()
                            payload = canvas
                        else:
                            payload = image
                if payload is not None:
                    raise StopIteration
                with Image.open(path) as source:
                    frame_count = max(1, int(getattr(source, "n_frames", 1) or 1))
                    metadata.update({
                        "image_size": (int(source.width), int(source.height)),
                        "image_format": str(source.format or path.suffix.upper().strip(".")),
                        "animated": bool(getattr(source, "is_animated", False) and frame_count > 1),
                        "frame_count": frame_count,
                    })
                    if getattr(source, "is_animated", False):
                        source.seek(0)
                    try:
                        source.draft("RGB", self.max_size)
                    except Exception:
                        pass
                    if self.cancelled:
                        raise InterruptedError
                    image = source.convert("RGBA")
                    image.thumbnail(self.max_size, Image.Resampling.LANCZOS)
                    if self.cancelled:
                        raise InterruptedError
                    if self.canvas_size:
                        canvas = Image.new("RGBA", self.canvas_size, (0, 0, 0, 255))
                        canvas.alpha_composite(
                            image,
                            ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2),
                        )
                        image = canvas
                    data = BytesIO()
                    image.save(data, format="PNG", optimize=False)
                    payload = data.getvalue()
        except StopIteration:
            pass
        except InterruptedError:
            payload = None
        except Exception:
            payload = None
        try:
            self.signals.finished.emit(self.generation, self.path, payload, metadata)
        except RuntimeError:
            # The application can close while a low-priority decode is finishing.
            pass


class AnimatedImageSignals(QObject):
    frameReady = Signal(object)
    finished = Signal(object)


class AnimatedImageTask(QRunnable):
    """Decode and scale one animated image entirely outside the GUI thread."""

    def __init__(
        self,
        generation,
        state_key,
        token,
        path,
        render_token,
        render_spec,
        playback_rate=1.0,
        archive_source=None,
    ):
        super().__init__()
        self.generation = int(generation)
        self.state_key = int(state_key)
        self.token = int(token)
        self.path = str(path)
        self.archive_source = archive_source
        self._render_token = int(render_token)
        self._render_spec = dict(render_spec)
        self._rate_token = 0
        self._playback_rate = normalize_playback_rate(playback_rate) or 1.0
        self._spec_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.ack_event = threading.Event()
        self.refresh_event = threading.Event()
        self.signals = AnimatedImageSignals()

    def cancel(self):
        self.cancel_event.set()
        self.ack_event.set()
        self.refresh_event.set()

    def acknowledge(self):
        self.ack_event.set()

    def update_render_spec(self, render_token, render_spec):
        with self._spec_lock:
            self._render_token = int(render_token)
            self._render_spec = dict(render_spec)
        self.refresh_event.set()

    def set_playback_rate(self, playback_rate):
        rate = normalize_playback_rate(playback_rate)
        if rate is None:
            return False
        with self._spec_lock:
            if math.isclose(rate, self._playback_rate, abs_tol=0.0005):
                return True
            self._playback_rate = rate
            self._rate_token += 1
        self.refresh_event.set()
        return True

    def render_snapshot(self):
        with self._spec_lock:
            return self._render_token, dict(self._render_spec)

    def rate_snapshot(self):
        with self._spec_lock:
            return self._rate_token, self._playback_rate

    @staticmethod
    def target_size(width, height, spec):
        width = max(1, int(width))
        height = max(1, int(height))
        area_width = max(1, int(spec.get("area_width", width)))
        area_height = max(1, int(spec.get("area_height", height)))
        fit_mode = spec.get("fit_mode", "fit_height")
        zoom = max(0.01, float(spec.get("zoom_factor", 1.0)))
        if fit_mode == "fit_width":
            target_width = area_width
            target_height = max(1, int(height * area_width / width))
        elif fit_mode == "fit_window":
            scale = min(area_width / width, area_height / height)
            target_width = max(1, int(width * scale))
            target_height = max(1, int(height * scale))
        elif fit_mode == "manual":
            target_width = max(1, int(width * zoom))
            target_height = max(1, int(height * zoom))
        elif fit_mode == "actual":
            target_width = width
            target_height = height
        else:
            target_width = max(1, int(width * area_height / height))
            target_height = area_height
            target_width = max(1, int(target_width * zoom))
            target_height = max(1, int(target_height * zoom))
        pixels = target_width * target_height
        max_frame_pixels = max(
            1,
            int(spec.get("max_frame_pixels", MAX_ANIMATED_FRAME_PIXELS)),
        )
        if pixels > max_frame_pixels:
            scale = (max_frame_pixels / pixels) ** 0.5
            target_width = max(1, int(target_width * scale))
            target_height = max(1, int(target_height * scale))
        return target_width, target_height

    def run(self):
        error = ""
        delivered = 0
        try:
            QThread.currentThread().setPriority(QThread.LowPriority)
            source_bytes = (
                self.archive_source.read(cancel_check=self.cancel_event.is_set)
                if self.archive_source is not None
                else None
            )
            source_handle = BytesIO(source_bytes) if source_bytes is not None else self.path
            webp_durations = [] if source_bytes is not None else animated_webp_frame_durations(self.path)
            with Image.open(source_handle) as reader:
                frame_count = max(1, int(getattr(reader, "n_frames", 1) or 1))
                animated = bool(getattr(reader, "is_animated", False) and frame_count > 1)
                index = 0
                while not self.cancel_event.is_set():
                    _, cycle_rate = self.rate_snapshot()
                    cycle_started = time.monotonic()
                    reader.seek(index)
                    duration_value = int(reader.info.get("duration", 0) or 0)
                    if duration_value <= 0 and index < len(webp_durations):
                        duration_value = webp_durations[index]
                    duration = max(10, duration_value or 80)
                    render_token, spec = self.render_snapshot()
                    frame = reader.convert("RGBA")
                    rotation = int(spec.get("rotation", 0)) % 360
                    if rotation:
                        frame = frame.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
                    target = self.target_size(frame.width, frame.height, spec)
                    if frame.size != target:
                        frame = frame.resize(target, Image.Resampling.LANCZOS)
                    image = ImageQt(frame).copy()
                    self.ack_event.clear()
                    self.signals.frameReady.emit({
                        "generation": self.generation,
                        "state_key": self.state_key,
                        "token": self.token,
                        "render_token": render_token,
                        "path": self.path,
                        "index": index,
                        "image": image,
                        "duration": duration,
                        "frame_count": frame_count,
                        "animated": animated,
                        "task": self,
                    })
                    delivered += 1
                    while not self.cancel_event.is_set() and not self.ack_event.wait(0.05):
                        pass
                    if self.cancel_event.is_set() or not animated:
                        break
                    source_remaining = max(
                        0.0,
                        float(duration) - (time.monotonic() - cycle_started) * 1000.0 * cycle_rate,
                    )
                    wait_render_token = render_token
                    _, active_rate = self.rate_snapshot()
                    rerender = False
                    last_tick = time.monotonic()
                    while source_remaining > 0 and not self.cancel_event.is_set():
                        woke = self.refresh_event.wait(source_remaining / 1000.0 / active_rate)
                        now = time.monotonic()
                        source_remaining -= max(0.0, now - last_tick) * 1000.0 * active_rate
                        last_tick = now
                        if not woke:
                            break
                        self.refresh_event.clear()
                        current_render_token, _ = self.render_snapshot()
                        _, active_rate = self.rate_snapshot()
                        if current_render_token != wait_render_token:
                            rerender = True
                            break
                    if self.cancel_event.is_set():
                        break
                    if not rerender:
                        index = (index + 1) % frame_count
        except Exception as exc:
            error = str(exc)
        try:
            self.signals.finished.emit({
                "generation": self.generation,
                "state_key": self.state_key,
                "token": self.token,
                "path": self.path,
                "task": self,
                "error": error,
                "delivered": delivered,
            })
        except RuntimeError:
            pass


class ArchiveSignals(QObject):
    finished = Signal(object)


class ArchiveExtractTask(QRunnable):
    def __init__(self, archive_path, add_history=True, navigation=None, request_id=0):
        super().__init__()
        self.archive_path = str(archive_path)
        self.add_history = bool(add_history)
        self.navigation = dict(navigation) if navigation else None
        self.request_id = int(request_id)
        self.signals = ArchiveSignals()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        result = {
            "archive": self.archive_path,
            "add_history": self.add_history,
            "navigation": self.navigation,
            "request_id": self.request_id,
            "tempdir": None,
            "root": None,
            "count": 0,
            "entries": [],
            "snapshots": {},
            "sources": {},
            "session": None,
            "error": "",
            "cancelled": False,
        }
        tempdir = None
        session = None
        try:
            tempdir = tempfile.TemporaryDirectory(prefix="pmv_zip_")
            root = Path(tempdir.name)
            session = ArchiveSession(self.archive_path)
            # Build a virtual directory tree.  Only directory placeholders
            # are materialized; image bytes stay inside the ZIP and are read
            # on demand through ArchiveMemberSource.
            root_entries = []
            snapshots = {}
            used_names = {}

            def safe_parts(member_name):
                parts = []
                for raw in PurePosixPath(str(member_name).replace("\\", "/")).parts:
                    if raw in ("", ".", "/"):
                        continue
                    if raw == "..":
                        continue
                    parts.append(raw)
                return parts

            def snapshot_for(folder):
                key = str(folder)
                if key not in snapshots:
                    snapshots[key] = []
                return snapshots[key]

            def add_dir(parent, name, target):
                entries = snapshot_for(parent)
                if not any(item.is_dir and str(item.path) == str(target) for item in entries):
                    entries.append(MediaItem(target, True, label=name))

            infos = []
            with session._lock:
                if not session._closed:
                    infos = list(session._archive.infolist())
            for info in infos:
                if self.cancelled:
                    raise InterruptedError
                parts = safe_parts(info.filename)
                if not parts:
                    continue
                # Explicit directory records create the same folders as
                # implicit parent paths; no file entry is added for them.
                is_directory = bool(info.is_dir() or str(info.filename).endswith("/"))
                if not is_directory and Path(parts[-1]).suffix.lower() not in MEDIA_EXTS:
                    continue
                parent = root
                for part in parts[:-1]:
                    child = parent / part
                    child.mkdir(parents=False, exist_ok=True)
                    add_dir(parent, part, child)
                    parent = child
                if is_directory:
                    target = parent / parts[-1]
                    target.mkdir(parents=False, exist_ok=True)
                    add_dir(parent, parts[-1], target)
                    snapshot_for(target)
                    continue

                original_name = parts[-1]
                # ZIPs may contain duplicate names.  Keep the hierarchy and
                # make only the conflicting virtual filename deterministic.
                key = (str(parent), original_name.casefold())
                duplicate_index = used_names.get(key, 0)
                used_names[key] = duplicate_index + 1
                display_name = original_name
                if duplicate_index:
                    stem = Path(original_name).stem
                    suffix = Path(original_name).suffix
                    display_name = f"{stem}_{duplicate_index}{suffix}"
                target = parent / display_name
                try:
                    mtime = time.mktime(tuple(info.date_time) + (0, 0, -1))
                except (OverflowError, ValueError):
                    mtime = 0.0
                item = MediaItem(
                    target,
                    False,
                    label=original_name,
                    size=int(info.file_size),
                    mtime=float(mtime),
                )
                snapshot_for(parent).append(item)
                result["sources"][str(target)] = ArchiveMemberSource(session, info.filename)
                result["count"] += 1
            root_entries = snapshot_for(root)
            result["entries"] = root_entries
            result["snapshots"] = snapshots
            result["tempdir"] = tempdir
            result["root"] = root
            result["session"] = session
        except InterruptedError:
            result["cancelled"] = True
            if session is not None:
                session.close()
            if tempdir is not None:
                tempdir.cleanup()
        except Exception as exc:
            result["error"] = str(exc)
            if session is not None:
                session.close()
            if tempdir is not None:
                tempdir.cleanup()
        self.signals.finished.emit(result)


class FolderScanSignals(QObject):
    finished = Signal(int, str, object, object)


class FolderScanTask(QRunnable):
    def __init__(self, generation, folder, signature, scanner):
        super().__init__()
        self.generation = int(generation)
        self.folder = str(folder)
        self.signature = tuple(signature)
        self.scanner = scanner
        self.signals = FolderScanSignals()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def is_cancelled(self):
        return self.cancelled

    def run(self):
        entries = None
        error = ""
        cancelled = False
        signature_after = self.signature
        try:
            if self.cancelled:
                raise InterruptedError
            QThread.currentThread().setPriority(QThread.LowPriority)
            entries = self.scanner(Path(self.folder), cancel_check=self.is_cancelled)
            stat = Path(self.folder).stat()
            signature_after = (int(stat.st_mtime_ns), int(getattr(stat, "st_size", 0)))
        except InterruptedError:
            cancelled = True
        except Exception as exc:
            error = str(exc)
        self.signals.finished.emit(
            self.generation,
            self.folder,
            entries,
            {
                "signature": self.signature,
                "signature_after": signature_after,
                "error": error,
                "cancelled": cancelled,
            },
        )


class UncShareSignals(QObject):
    finished = Signal(int, str, object, object)


class UncShareTask(QRunnable):
    """Run NetShareEnum away from the GUI thread."""

    def __init__(self, generation, server):
        super().__init__()
        self.generation = int(generation)
        self.server = str(server)
        self.cancelled = False
        self.signals = UncShareSignals()

    def cancel(self):
        self.cancelled = True

    def run(self):
        shares = []
        error = ""
        try:
            if self.cancelled:
                raise InterruptedError
            QThread.currentThread().setPriority(QThread.LowPriority)
            shares = unc_share_paths(self.server)
        except InterruptedError:
            return
        except Exception as exc:
            error = str(exc)
        try:
            self.signals.finished.emit(
                self.generation,
                self.server,
                shares,
                {"error": error, "cancelled": self.cancelled},
            )
        except RuntimeError:
            pass


class FileOperationSignals(QObject):
    finished = Signal(object)


class FileOperationTask(QRunnable):
    """Perform potentially slow shell/file operations off the GUI thread."""

    def __init__(self, operation, **kwargs):
        super().__init__()
        self.operation = str(operation)
        self.kwargs = kwargs
        self.signals = FileOperationSignals()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        result = {"operation": self.operation, "copied": [], "errors": [], "cancelled": False}
        if "target_folder" in self.kwargs:
            result["target_folder"] = str(self.kwargs["target_folder"])
        try:
            if self.cancelled:
                result["cancelled"] = True
                return
            if self.operation == "paste":
                target_folder = Path(self.kwargs["target_folder"])
                sources = [Path(path) for path in self.kwargs.get("sources", [])]
                move_mode = bool(self.kwargs.get("move_mode"))
                for source in sources:
                    if self.cancelled:
                        result["cancelled"] = True
                        break
                    if not source.exists():
                        continue
                    try:
                        target = unique_copy_target(target_folder / source.name)
                        if source.is_dir() and path_contains(source, target):
                            raise ValueError(f"Cannot paste a folder into itself: {source}")
                        if move_mode:
                            shutil.move(str(source), str(target))
                        elif source.is_dir():
                            shutil.copytree(source, target)
                        else:
                            shutil.copy2(source, target)
                        result["copied"].append(str(target))
                    except Exception as exc:
                        result["errors"].append(f"{source}\n{exc}")
                        break
            elif self.operation == "delete":
                for source in self.kwargs.get("sources", []):
                    if self.cancelled:
                        result["cancelled"] = True
                        break
                    try:
                        send_to_recycle_bin(Path(source))
                    except Exception as exc:
                        result["errors"].append(f"{source}\n{exc}")
        except Exception as exc:
            result["errors"].append(str(exc))
        finally:
            try:
                self.signals.finished.emit(result)
            except RuntimeError:
                pass


class VlcInitSignals(QObject):
    finished = Signal(object, object, str, object)


class VideoCleanupSignals(QObject):
    finished = Signal(object, object)


class VideoStartSignals(QObject):
    finished = Signal(object)


class VideoPlayerCreateSignals(QObject):
    finished = Signal(object, str, object)


class VideoPlayerCreateTask:
    def __init__(self, instance, count):
        self.instance = instance
        self.count = max(0, int(count))
        self.signals = VideoPlayerCreateSignals()

    def run(self):
        bundles = []
        error = ""
        try:
            if sys.platform == "win32":
                try:
                    ctypes.windll.kernel32.SetThreadPriority(
                        ctypes.windll.kernel32.GetCurrentThread(), -1
                    )
                except Exception:
                    pass
            for _ in range(self.count):
                player = self.instance.media_player_new()
                if player is None:
                    raise RuntimeError("libVLC media player creation returned no player")
                bundles.append((self.instance, player))
        except Exception as exc:
            error = str(exc)
        try:
            self.signals.finished.emit(bundles, error, self)
        except RuntimeError:
            for _instance, player in bundles:
                try:
                    player.release()
                except Exception:
                    pass


class VlcInitTask(QRunnable):
    """Create libVLC away from the GUI thread.

    A first libVLC instance can spend several seconds scanning plugins when a
    bundled runtime has no warm cache.  That native call cannot be cancelled,
    so it lives in its own single-worker pool and only returns plain python-vlc
    handles to the GUI thread.
    """

    def __init__(self, vlc_module):
        super().__init__()
        self.vlc_module = vlc_module
        self.signals = VlcInitSignals()

    def run(self):
        bundles = []
        error = ""
        instance = None
        try:
            if sys.platform == "win32":
                try:
                    ctypes.windll.kernel32.SetThreadPriority(
                        ctypes.windll.kernel32.GetCurrentThread(), -1
                    )
                except Exception:
                    pass
            instance = self.vlc_module.Instance(*VLC_INSTANCE_ARGS)
            if instance is None:
                raise RuntimeError("libVLC instance creation returned no instance")
            # Return one usable player as soon as the cold libVLC instance is
            # ready.  Filling the transition pool here made the first video
            # wait for every standby player even though it only needs one.
            for _ in range(VIDEO_INITIAL_PLAYER_TARGET):
                player = instance.media_player_new()
                if player is None:
                    raise RuntimeError("libVLC media player creation returned no player")
                bundles.append((instance, player))
        except Exception as exc:
            error = str(exc)
            try:
                for instance, player in bundles:
                    player.release()
            except Exception:
                pass
            try:
                if instance is not None:
                    instance.release()
            except Exception:
                pass
            bundles = []
        try:
            sentinel = bundles[0][0] if bundles else None
            self.signals.finished.emit(sentinel, bundles, error, self)
        except RuntimeError:
            pass


class ExtensionBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        view = option.widget
        if not isinstance(view, QListWidget) or view.viewMode() != QListWidget.IconMode:
            return
        path = str(index.data(Qt.UserRole) or "")
        label = extension_badge_text(path)
        background = type_badge_color(path)
        if not label or background is None:
            return

        badge_option = QStyleOptionViewItem(option)
        self.initStyleOption(badge_option, index)
        icon_rect = view.style().subElementRect(QStyle.SE_ItemViewItemDecoration, badge_option, view)
        if not icon_rect.isValid() or icon_rect.width() < 12 or icon_rect.height() < 12:
            icon_size = view.iconSize()
            icon_width = min(icon_size.width(), max(1, option.rect.width() - 8))
            icon_height = min(icon_size.height(), max(1, option.rect.height() - 24))
            icon_rect = QRect(
                option.rect.center().x() - icon_width // 2,
                option.rect.top() + 4,
                icon_width,
                icon_height,
            )

        short_side = min(icon_rect.width(), icon_rect.height())
        pixel_size = max(8, min(14, round(short_side * 0.11)))
        font = QFont(option.font)
        font.setBold(True)
        font.setPixelSize(pixel_size)
        metrics = QFontMetrics(font)
        horizontal_padding = max(4, pixel_size // 2)
        vertical_padding = max(2, pixel_size // 6)
        badge_width = metrics.horizontalAdvance(label) + horizontal_padding * 2
        badge_height = metrics.height() + vertical_padding * 2
        margin = max(2, round(short_side * 0.025))
        badge_rect = QRect(
            icon_rect.right() - badge_width - margin + 1,
            icon_rect.bottom() - badge_height - margin + 1,
            badge_width,
            badge_height,
        )
        radius = max(3, badge_height // 3)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(badge_rect.translated(0, 1), radius, radius)
        painter.setPen(QPen(QColor(255, 255, 255, 115), 1))
        painter.setBrush(background)
        painter.drawRoundedRect(badge_rect, radius, radius)
        painter.setPen(contrasting_text_color(background))
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignCenter, label)
        painter.restore()


class ThumbList(QListWidget):
    openRequested = Signal(str)
    previewRequested = Signal(str)
    copyRequested = Signal()
    deleteRequested = Signal()
    pasteRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("thumbList")
        self._dark_theme = True
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemDoubleClicked.connect(self._open_item)
        self.itemSelectionChanged.connect(self._preview_selected)
        self.icon_provider = QFileIconProvider()
        self.setItemDelegate(ExtensionBadgeDelegate(self))
        self.setSpacing(8)

    def set_view_mode_name(self, mode):
        previously_showed_row_colors = self.viewMode() == QListWidget.ListMode
        if mode == "list":
            self.setViewMode(QListWidget.ListMode)
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
            self.setIconSize(QSize(32, 32))
            self.setGridSize(QSize())
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "details":
            self.setViewMode(QListWidget.ListMode)
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
            self.setIconSize(QSize(48, 48))
            self.setGridSize(QSize())
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "small":
            self.setViewMode(QListWidget.IconMode)
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.setIconSize(QSize(72, 72))
            self.setGridSize(QSize(116, 116))
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "medium":
            self.setViewMode(QListWidget.IconMode)
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.setIconSize(QSize(120, 120))
            self.setGridSize(QSize(168, 160))
            self.setResizeMode(QListWidget.Adjust)
        else:
            self.setViewMode(QListWidget.IconMode)
            self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.setIconSize(QSize(168, 168))
            self.setGridSize(QSize(224, 216))
            self.setResizeMode(QListWidget.Adjust)
        if previously_showed_row_colors != (self.viewMode() == QListWidget.ListMode):
            self.refresh_type_colors()

    def set_dark_theme(self, dark_theme):
        self._dark_theme = bool(dark_theme)
        self.refresh_type_colors()
        self.viewport().update()

    def refresh_type_colors(self):
        show_row_colors = self.viewMode() == QListWidget.ListMode
        for row in range(self.count()):
            item = self.item(row)
            path = str(item.data(Qt.UserRole) or "")
            item.setData(
                Qt.BackgroundRole,
                type_color(path, dark_theme=self._dark_theme) if show_row_colors else None,
            )

    def _open_item(self, item):
        self.openRequested.emit(item.data(Qt.UserRole))

    def _preview_selected(self):
        items = self.selectedItems()
        if items:
            self.previewRequested.emit(items[0].data(Qt.UserRole))

    def startDrag(self, supported_actions):
        super().startDrag(supported_actions)

    def wheelEvent(self, event):
        if self.viewMode() != QListWidget.IconMode or event.modifiers() != Qt.NoModifier:
            super().wheelEvent(event)
            return
        angle_delta = event.angleDelta().y()
        pixel_delta = event.pixelDelta().y()
        if angle_delta:
            row_height = max(1, self.gridSize().height())
            distance = round(-angle_delta / 120.0 * row_height * THUMBNAIL_WHEEL_ROWS)
        elif pixel_delta:
            distance = round(-pixel_delta * THUMBNAIL_TOUCHPAD_SCALE)
        else:
            super().wheelEvent(event)
            return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + distance)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Home:
            if self.count():
                self.setCurrentRow(0)
                self.scrollToTop()
            return
        if event.key() == Qt.Key_End:
            if self.count():
                self.setCurrentRow(self.count() - 1)
                self.scrollToBottom()
            return
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            return
        if event.key() == Qt.Key_Delete:
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)


class SortableTableItem(QTableWidgetItem):
    def __lt__(self, other):
        own_group = int(self.data(Qt.UserRole + 2) or 0)
        other_group = int(other.data(Qt.UserRole + 2) or 0)
        if own_group != other_group:
            table = self.tableWidget()
            descending = bool(
                table
                and table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
            )
            return own_group > other_group if descending else own_group < other_group
        own_value = self.data(Qt.UserRole + 1)
        other_value = other.data(Qt.UserRole + 1)
        try:
            return own_value < other_value
        except TypeError:
            return str(own_value) < str(other_value)


class DetailsTable(QTableWidget):
    openRequested = Signal(str)
    previewRequested = Signal(str)
    sortedRequested = Signal(str, bool)
    copyRequested = Signal()
    deleteRequested = Signal()
    pasteRequested = Signal()

    HEADERS = [
        "Filename",
        "Size (KB)",
        "Image Type",
        "Modified Date",
        "Image Properties",
    ]

    SORT_KEYS = {
        0: "name",
        1: "size",
        2: "type",
        3: "modified",
        4: "properties",
    }

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setObjectName("detailsTable")
        self._load_generation = 0
        self._pending_entries = []
        self._load_index = 0
        self._make_icon = None
        self._lightweight_load = True
        self._row_ready_callback = None
        self._dark_theme = True
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.setColumnWidth(0, 320)
        for col in range(1, len(self.HEADERS)):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
        self.setColumnWidth(1, 105)
        self.setColumnWidth(2, 110)
        self.setColumnWidth(3, 175)
        self.setColumnWidth(4, 150)
        self.cellDoubleClicked.connect(self._open_row)
        self.itemSelectionChanged.connect(self._preview_selected)
        self.horizontalHeader().sectionClicked.connect(self._sort_clicked)
        self.sort_column = 0
        self.sort_ascending = True

    def load_entries(self, entries, icon_provider, make_icon, lightweight=False, row_ready=None):
        self._load_generation += 1
        generation = self._load_generation
        self._pending_entries = list(entries)
        self._load_index = 0
        self._make_icon = make_icon
        self._lightweight_load = lightweight
        self._row_ready_callback = row_ready
        self.setRowCount(len(self._pending_entries))
        self._append_entry_chunk(generation, 16)
        if self._load_index < len(self._pending_entries):
            QTimer.singleShot(1, lambda g=generation: self._continue_entry_load(g))

    def clear_entries(self):
        self._load_generation += 1
        self._pending_entries = []
        self._load_index = 0
        self._row_ready_callback = None
        self.setRowCount(0)

    def _continue_entry_load(self, generation):
        if generation != self._load_generation:
            return
        self._append_entry_chunk(generation, 16)
        if self._load_index < len(self._pending_entries):
            QTimer.singleShot(1, lambda g=generation: self._continue_entry_load(g))

    def _append_entry_chunk(self, generation, count):
        if generation != self._load_generation:
            return
        stop = min(len(self._pending_entries), self._load_index + int(count))
        while self._load_index < stop:
            row = self._load_index
            entry = self._pending_entries[row]
            values = self.row_values(entry, lightweight=self._lightweight_load)
            for col, value in enumerate(values):
                item = SortableTableItem(value)
                item.setData(Qt.UserRole, str(entry.path))
                item.setData(Qt.UserRole + 2, 0 if entry.is_dir else 1)
                sort_values = [
                    natural_sort_key(entry.display_name),
                    entry.size,
                    entry.kind,
                    entry.mtime,
                    entry.image_size or (0, 0),
                ]
                item.setData(Qt.UserRole + 1, sort_values[col])
                if col == 0:
                    item.setIcon(self._make_icon(entry))
                if col == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                color = type_color(entry.path, entry.is_dir, dark_theme=self._dark_theme)
                if color is not None:
                    item.setBackground(color)
                self.setItem(row, col, item)
            if self._row_ready_callback is not None:
                self._row_ready_callback(entry, self.item(row, 0))
            self._load_index += 1

    def row_values(self, entry, lightweight=False):
        if entry.is_dir:
            return [entry.display_name, "", "Folder", fmt_timestamp(entry.mtime), ""]
        size_kb = entry.size // 1024
        if lightweight:
            kind = "Video" if is_video(entry.path) else entry.path.suffix.upper().strip(".")
            return [
                entry.display_name,
                f"{size_kb:,}",
                kind,
                fmt_timestamp(entry.mtime),
                f"{entry.image_size[0]}x{entry.image_size[1]}" if entry.image_size else "",
            ]
        return [
            entry.display_name,
            f"{size_kb:,}",
            image_type(entry.path),
            fmt_timestamp(entry.mtime),
            image_properties(entry.path),
        ]

    def selected_paths(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        paths = []
        for row in rows:
            item = self.item(row, 0)
            if item:
                paths.append(Path(item.data(Qt.UserRole)))
        return paths

    def _open_row(self, row, _col):
        item = self.item(row, 0)
        if item:
            self.openRequested.emit(item.data(Qt.UserRole))

    def _preview_selected(self):
        paths = self.selected_paths()
        if paths:
            self.previewRequested.emit(str(paths[0]))

    def _sort_clicked(self, column):
        if self.sort_column == column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column
            self.sort_ascending = True
        self.horizontalHeader().setSortIndicator(column, Qt.AscendingOrder if self.sort_ascending else Qt.DescendingOrder)
        self.horizontalHeader().setSortIndicatorShown(True)
        self.sortedRequested.emit(self.SORT_KEYS.get(column, "name"), self.sort_ascending)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Home:
            if self.rowCount():
                self.selectRow(0)
                self.scrollToTop()
            return
        if event.key() == Qt.Key_End:
            if self.rowCount():
                self.selectRow(self.rowCount() - 1)
                self.scrollToBottom()
            return
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            return
        if event.key() == Qt.Key_Delete:
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)


class PreviewPanel(QLabel):
    def __init__(self):
        super().__init__("Preview")
        self.setObjectName("previewPanel")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setFrameShape(QFrame.StyledPanel)
        self.movie = None
        self._source_pixmap = QPixmap()
        self._current_path = None
        self._decoded_pixel_size = QSize()
        self._generation = 0
        self._suspended = False
        self._task_refs = set()
        self.source_resolver = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._resize_decode_timer = QTimer(self)
        self._resize_decode_timer.setSingleShot(True)
        self._resize_decode_timer.setInterval(140)
        self._resize_decode_timer.timeout.connect(self._reload_for_current_size)

    def sizeHint(self):
        return QSize(320, 220)

    def minimumSizeHint(self):
        return QSize(120, 160)

    def show_path(self, path):
        self._generation += 1
        generation = self._generation
        for task in list(self._task_refs):
            try:
                task.cancel()
            except Exception:
                pass
        self._pool.clear()
        if self.movie is not None:
            try:
                self.movie.stop()
            except RuntimeError:
                pass
        self.movie = None
        self._source_pixmap = QPixmap()
        self._decoded_pixel_size = QSize()
        self._current_path = str(path) if path else None
        if self._suspended:
            return
        archive_source = self.source_resolver(str(path)) if path and self.source_resolver else None
        if not path or (not Path(path).exists() and archive_source is None):
            self.setText("Preview")
            self.setPixmap(QPixmap())
            return
        if is_video(path):
            self.setText("Video\n" + file_label(path))
            self.setPixmap(self.style().standardIcon(QStyle.SP_MediaPlay).pixmap(96, 96))
            return
        if archive_source is None and Path(path).suffix.lower() == ".gif":
            movie = QMovie(path)
            if movie.isValid():
                self.movie = movie
                self.setMovie(movie)
                movie.start()
                return
        self.setText("Loading…")
        self.setPixmap(QPixmap())
        self._queue_decode(generation, str(path), archive_source=archive_source)

    def suspend(self):
        self._suspended = True
        self._generation += 1
        self._resize_decode_timer.stop()
        for task in list(self._task_refs):
            try:
                task.cancel()
            except Exception:
                pass
        self._pool.clear()
        if self.movie is not None:
            try:
                self.movie.stop()
            except RuntimeError:
                pass
        self.setPixmap(QPixmap())
        self.movie = None

    def resume(self):
        if not self._suspended:
            return
        self._suspended = False
        path = self._current_path
        if path:
            self.show_path(path)

    def _decode_target(self):
        dpr = max(1.0, float(self.devicePixelRatioF()))
        oversample = 1.5
        width = max(480, int(self.width() * dpr * oversample))
        height = max(360, int(self.height() * dpr * oversample))
        scale = min(1.0, 2048.0 / max(width, height))
        return QSize(max(1, int(width * scale)), max(1, int(height * scale)))

    def _queue_decode(self, generation, path, archive_source=None):
        target = self._decode_target()
        task = ImageDecodeTask(
            generation,
            path,
            (target.width(), target.height()),
            archive_source=archive_source,
        )
        self._task_refs.add(task)
        task.signals.finished.connect(
            lambda result_generation, result_path, payload, metadata, ref=task: self._preview_ready(
                result_generation, result_path, payload, ref
            )
        )
        self._pool.start(task)

    def _reload_for_current_size(self):
        path = self._current_path
        archive_source = self.source_resolver(str(path)) if path and self.source_resolver else None
        if (
            not path
            or (not Path(path).exists() and archive_source is None)
            or is_video(path)
            or (archive_source is None and Path(path).suffix.lower() == ".gif")
        ):
            return
        target = self._decode_target()
        if (
            self._decoded_pixel_size.isValid()
            and self._decoded_pixel_size.width() >= int(target.width() * 0.9)
            and self._decoded_pixel_size.height() >= int(target.height() * 0.9)
        ):
            return
        self._generation += 1
        self._pool.clear()
        self.setText("Loading…")
        self._queue_decode(self._generation, path, archive_source=archive_source)

    def _preview_ready(self, generation, path, payload, task):
        self._task_refs.discard(task)
        if generation != self._generation:
            return
        pix = QPixmap()
        if isinstance(payload, QImage):
            pix = QPixmap.fromImage(payload)
        elif isinstance(payload, (bytes, bytearray)):
            pix.loadFromData(bytes(payload), "PNG")
        if pix.isNull():
            self.setText(file_label(path))
            self.setPixmap(QPixmap())
        else:
            self._source_pixmap = pix
            self._decoded_pixel_size = pix.size()
            self.setText("")
            self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        if not self._source_pixmap.isNull():
            self.setPixmap(self._source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled_pixmap()
        if self._current_path and not self._source_pixmap.isNull():
            self._resize_decode_timer.start()


class PannableImageLabel(QLabel):
    regionZoomRequested = Signal(object)

    def __init__(self):
        super().__init__()
        self._viewer_pixmap = QPixmap()
        self._pan_offset = QPoint(0, 0)
        self._dragging = False
        self._drag_start_pos = QPoint(0, 0)
        self._drag_start_offset = QPoint(0, 0)
        self._selecting = False
        self._selection_origin = QPoint(0, 0)
        self._selection_rect = QRect()
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

    def setText(self, text):
        if text:
            self._viewer_pixmap = QPixmap()
            self._pan_offset = QPoint(0, 0)
            self._selection_rect = QRect()
            self.unsetCursor()
        super().setText(text)

    def setPixmap(self, pixmap):
        self._viewer_pixmap = QPixmap(pixmap) if pixmap is not None and not pixmap.isNull() else QPixmap()
        super().setPixmap(QPixmap())
        self._selection_rect = QRect()
        self._pan_offset = self.clamped_pan_offset(self._pan_offset)
        self.update_pan_cursor()
        self.update()

    def can_pan(self):
        if self._viewer_pixmap.isNull():
            return False
        return self._viewer_pixmap.width() > self.width() or self._viewer_pixmap.height() > self.height()

    def clamped_pan_offset(self, offset):
        if self._viewer_pixmap.isNull():
            return QPoint(0, 0)
        max_x = max(0, (self._viewer_pixmap.width() - self.width()) // 2)
        max_y = max(0, (self._viewer_pixmap.height() - self.height()) // 2)
        return QPoint(
            max(-max_x, min(max_x, offset.x())),
            max(-max_y, min(max_y, offset.y())),
        )

    def update_pan_cursor(self):
        if self._selecting:
            self.setCursor(Qt.CrossCursor)
        elif self._dragging:
            self.setCursor(Qt.ClosedHandCursor)
        elif self.can_pan():
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def paintEvent(self, event):
        if self._viewer_pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        offset = self.clamped_pan_offset(self._pan_offset)
        if offset != self._pan_offset:
            self._pan_offset = offset
        x = (self.width() - self._viewer_pixmap.width()) // 2 + self._pan_offset.x()
        y = (self.height() - self._viewer_pixmap.height()) // 2 + self._pan_offset.y()
        painter.drawPixmap(x, y, self._viewer_pixmap)
        if not self._selection_rect.isNull():
            pen = QPen(QColor("#59a8ff"), 1, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor(70, 145, 230, 38))
            painter.drawRect(self._selection_rect)

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        if event.button() == Qt.RightButton and not self._selection_rect.isNull():
            self._selection_rect = QRect()
            self.update()
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and not self._selection_rect.isNull()
            and self._selection_rect.contains(point)
            and not (event.modifiers() & Qt.ControlModifier)
        ):
            selection = QRect(self._selection_rect)
            self._selection_rect = QRect()
            self.update()
            self.regionZoomRequested.emit(selection)
            event.accept()
            return
        if event.button() == Qt.LeftButton and (not self.can_pan() or event.modifiers() & Qt.ControlModifier):
            self._selecting = True
            self._selection_origin = point
            self._selection_rect = QRect(point, point)
            self.update_pan_cursor()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.can_pan():
            self._dragging = True
            self._drag_start_pos = point
            self._drag_start_offset = QPoint(self._pan_offset)
            self.update_pan_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._selecting:
            self._selection_rect = QRect(self._selection_origin, event.position().toPoint()).normalized()
            self.update()
            event.accept()
            return
        if self._dragging:
            delta = event.position().toPoint() - self._drag_start_pos
            self._pan_offset = self.clamped_pan_offset(self._drag_start_offset + delta)
            self.update()
            event.accept()
            return
        self.update_pan_cursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            if self._selection_rect.width() < 6 or self._selection_rect.height() < 6:
                self._selection_rect = QRect()
            self.update_pan_cursor()
            self.update()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.update_pan_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._pan_offset = self.clamped_pan_offset(self._pan_offset)
        self.update_pan_cursor()

    def set_pan_offset(self, offset):
        self._pan_offset = self.clamped_pan_offset(offset)
        self.update()


class ViewerNativeInputFilter(QAbstractNativeEventFilter):
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_MOUSEWHEEL = 0x020A
    WM_MBUTTONDOWN = 0x0207
    WM_XBUTTONDOWN = 0x020B
    VK_PRIOR = 0x21
    VK_NEXT = 0x22
    VK_END = 0x23
    VK_HOME = 0x24
    VK_DELETE = 0x2E

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("message", ctypes.c_uint),
            ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_ssize_t),
            ("time", ctypes.c_uint),
            ("pt_x", ctypes.c_long),
            ("pt_y", ctypes.c_long),
        ]

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

    def nativeEventFilter(self, event_type, message):
        viewer = getattr(self.main_window, "viewer", None)
        if not viewer:
            return False, 0
        if hasattr(self.main_window, "main_stack") and self.main_window.main_stack.currentWidget() is not viewer:
            return False, 0
        try:
            msg = self.MSG.from_address(int(message))
        except Exception:
            return False, 0

        if msg.message in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            key = int(msg.wParam)
            if key == self.VK_NEXT:
                QTimer.singleShot(0, viewer.next_media)
                return True, 0
            if key == self.VK_PRIOR:
                QTimer.singleShot(0, viewer.previous_media)
                return True, 0
            if key == self.VK_HOME:
                QTimer.singleShot(0, viewer.first_media)
                return True, 0
            if key == self.VK_END:
                QTimer.singleShot(0, viewer.last_media)
                return True, 0
            if key == self.VK_DELETE:
                QTimer.singleShot(0, self.main_window.handle_delete_shortcut)
                return True, 0

        if msg.message == self.WM_MOUSEWHEEL:
            delta = ctypes.c_short((int(msg.wParam) >> 16) & 0xFFFF).value
            QTimer.singleShot(0, lambda d=delta: viewer.handle_wheel_delta(d))
            return True, 0

        if msg.message == self.WM_MBUTTONDOWN:
            QTimer.singleShot(0, viewer.toggle_fullscreen)
            return True, 0

        if msg.message == self.WM_XBUTTONDOWN:
            xbutton = (int(msg.wParam) >> 16) & 0xFFFF
            QTimer.singleShot(0, viewer.previous_media if xbutton == 1 else viewer.next_media)
            return True, 0

        return False, 0


class ViewerMouseWheelHook:
    WH_MOUSE_LL = 14
    WM_MOUSEWHEEL = 0x020A
    HC_ACTION = 0

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    def __init__(self, main_window):
        self.main_window = main_window
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.hook = None
        self.proc_type = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        self.proc = self.proc_type(self._callback)
        self.user32.SetWindowsHookExW.argtypes = [ctypes.c_int, self.proc_type, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallNextHookEx.restype = ctypes.c_long
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    def install(self):
        if self.hook:
            return
        module = self.kernel32.GetModuleHandleW(None)
        self.hook = self.user32.SetWindowsHookExW(self.WH_MOUSE_LL, self.proc, module, 0)

    def uninstall(self):
        if self.hook:
            self.user32.UnhookWindowsHookEx(self.hook)
            self.hook = None

    def _callback(self, code, wparam, lparam):
        if code == self.HC_ACTION and int(wparam) == self.WM_MOUSEWHEEL:
            viewer = getattr(self.main_window, "viewer", None)
            # WH_MOUSE_LL receives wheel messages for every process.  Only
            # consume them when this viewer's process is the foreground
            # process; otherwise a window placed in front (e.g. Explorer)
            # would still rotate the hidden viewer behind it.
            if (
                viewer
                and viewer.is_active_viewer()
                and self._viewer_process_is_foreground()
                and self._point_in_window(lparam)
            ):
                info = self.MSLLHOOKSTRUCT.from_address(int(lparam))
                delta = ctypes.c_short((int(info.mouseData) >> 16) & 0xFFFF).value
                QTimer.singleShot(0, lambda d=delta: viewer.handle_wheel_delta(d))
                return 1
        return self.user32.CallNextHookEx(self.hook, code, wparam, lparam)

    def _viewer_process_is_foreground(self):
        try:
            foreground = int(self.user32.GetForegroundWindow() or 0)
            if not foreground:
                return False
            process_id = wintypes.DWORD()
            if not self.user32.GetWindowThreadProcessId(
                foreground,
                ctypes.byref(process_id),
            ):
                return False
            return int(process_id.value) == os.getpid()
        except Exception:
            return False

    def _point_in_window(self, lparam):
        info = self.MSLLHOOKSTRUCT.from_address(int(lparam))
        geo = self.main_window.frameGeometry()
        return geo.contains(info.pt.x, info.pt.y)


class ViewerWindow(QMainWindow):
    closed = Signal()
    exitRequested = Signal()
    deleteRequested = Signal(str)
    copyRequested = Signal(str)
    cutRequested = Signal(str)
    pasteRequested = Signal()
    propertiesRequested = Signal(str)
    videoEnded = Signal(int)
    videoOutputReady = Signal(int, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.performance_policy = performance_policy_for(settings)
        self.app_closing = False
        self.items = []
        self.item_signatures = {}
        self.archive_sources = {}
        self.archive_image_sizes = {}
        self.index = 0
        self.zoom_factor = 1.0
        self.fit_mode = settings.get("default_fit", "fit_height")
        self.zoom_locked = settings.get("zoom_locked", True)
        # The configured default applies once, when a new application session
        # creates its viewer.  Mode changes after that are session state: going
        # back to the explorer and reopening media must not reset them.
        self.viewer_mode = settings.get("default_viewer_mode", "single")
        if self.viewer_mode == "webtoon" or str(self.viewer_mode).startswith("webtoon_") and self.viewer_mode != "webtoon_vertical":
            self.viewer_mode = "webtoon_vertical"
        self.step_mode = settings.get("viewer_step", "page")
        self.rotation = 0
        self.media_player = None
        self.vlc_instance = None
        self.extra_media_players = []
        self.video_standby_players = []
        self.vlc_init_task_refs = set()
        self.vlc_init_thread = None
        self.vlc_init_inflight = False
        self.vlc_init_error = ""
        self.video_player_create_task_refs = set()
        self.video_player_create_thread = None
        self.video_player_create_inflight = False
        self.pending_video_requests = []
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        self.video_playback_token = 0
        self._video_end_callback = None
        self.video_slot_states = {}
        self.video_end_callbacks = {}
        self.video_ready_callbacks = {}
        self.video_loop_enabled = bool(settings.get("video_loop_enabled", False))
        self.playback_rate = 1.0
        self.current_has_animation = False
        self.video_cleanup_queue = queue.Queue()
        self.video_cleanup_closed = False
        self.video_cleanup_signals = VideoCleanupSignals()
        self.video_cleanup_signals.accept_results = True
        self.video_cleanup_signals.finished.connect(
            self._video_cleanup_finished,
            Qt.QueuedConnection,
        )
        self.video_player_frames = {}
        self.video_player_instances = {}
        self.video_retired_callback_refs = {}
        self.video_frame_busy = set()
        self.video_retired_players = []
        self.video_cleanup_flush_pending = False
        self.video_cleanup_inflight = 0
        self.video_cleanup_thread = threading.Thread(
            target=self._video_cleanup_worker,
            args=(self.video_cleanup_queue, self.video_cleanup_signals),
            name="PhotoViewer-VLC-Cleanup",
            daemon=True,
        )
        self.video_cleanup_thread.start()
        self.video_start_queue = queue.Queue()
        self.video_start_closed = False
        self.video_start_inflight = 0
        self.video_start_players = {}
        self.video_start_started = {}
        self.video_player_locks = {}
        self.video_retired_instances = []
        self.video_start_signals = VideoStartSignals()
        self.video_start_signals.accept_results = True
        self.video_start_signals.finished.connect(
            self._video_start_finished,
            Qt.QueuedConnection,
        )
        self.video_start_thread = threading.Thread(
            target=self._video_start_worker,
            args=(self.video_start_queue, self.video_start_signals),
            name="PhotoViewer-VLC-Start",
            daemon=True,
        )
        self.video_start_thread.start()
        self.movie = None
        self._app_filter_installed = False
        self._seeking_video = False
        self.video_path = None
        self.video_finished = False
        self.video_stopped_by_user = False
        self.webtoon_scroll = None
        self.webtoon_container = None
        self.webtoon_loaded = set()
        self.webtoon_label_indices = {}
        self.webtoon_label_tops = []
        self.webtoon_idle_index = 0
        self.webtoon_target_width = None
        self.webtoon_pixmap_cache = {}
        self.webtoon_pixmap_cache_order = []
        self.webtoon_pixmap_cache_bytes = 0
        self.webtoon_auto_scroll_active = False
        self.webtoon_auto_scroll_remainder = 0.0
        self.webtoon_auto_scroll_last_tick = 0.0
        self.webtoon_auto_scroll_speed_mode = settings.get("webtoon_auto_scroll_speed_mode", "normal")
        if self.webtoon_auto_scroll_speed_mode not in (*WEBTOON_AUTO_SCROLL_SPEEDS.keys(), "manual"):
            self.webtoon_auto_scroll_speed_mode = "normal"
        self.webtoon_auto_scroll_manual_speed = int(settings.get("webtoon_auto_scroll_manual_speed", 120) or 120)
        self.webtoon_auto_scroll_manual_speed = max(
            WEBTOON_AUTO_SCROLL_MIN_SPEED,
            min(WEBTOON_AUTO_SCROLL_MAX_SPEED, self.webtoon_auto_scroll_manual_speed),
        )
        self.viewer_pixmap_cache = {}
        self.viewer_pixmap_cache_order = []
        self.viewer_pixmap_cache_bytes = 0
        self.decode_pool = QThreadPool(self)
        self.decode_pool.setMaxThreadCount(max(1, int(self.performance_policy.viewer_decode_workers)))
        self.decode_pool.setThreadPriority(QThread.LowPriority)
        self.preload_decode_pool = QThreadPool(self)
        self.preload_decode_pool.setMaxThreadCount(1)
        self.preload_decode_pool.setThreadPriority(QThread.IdlePriority)
        self.decode_inflight = set()
        self.decode_task_refs = set()
        self.opening_placeholder = QPixmap()
        self.viewer_preload_queue = []
        self.viewer_preload_queued = set()
        self.render_generation = 0
        self.active_display_path = None
        self.video_thumbnail_cache = {}
        self.animated_image_reader = None
        self.animated_image_frame_count = 0
        self.animated_image_index = 0
        self.animated_image_label = None
        self.animated_image_path = None
        self.animated_image_states = {}
        self.animated_image_pool = QThreadPool(self)
        self.animated_image_pool.setMaxThreadCount(max(1, int(self.performance_policy.animation_workers)))
        self.animated_image_pool.setThreadPriority(QThread.LowPriority)
        self.animated_image_task_refs = set()
        self.animated_image_token = 0
        self.animated_render_token = 0
        self.animated_image_classifications = {}

        self.setWindowTitle(APP_NAME + " - Viewer")
        self.setMinimumSize(900, 640)
        self._build_ui()
        self._build_shortcuts()
        self.videoEnded.connect(self._mark_video_ended, Qt.QueuedConnection)
        self.videoOutputReady.connect(self._mark_video_output_ready, Qt.QueuedConnection)

    def _build_ui(self):
        self.setStyleSheet("QMainWindow { background: #050505; }")
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#050505"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.central = QWidget()
        self.central.setObjectName("viewerCentral")
        self.central.setMouseTracking(True)
        self.central.setAttribute(Qt.WA_StyledBackground, True)
        self.central.setAutoFillBackground(True)
        central_palette = self.central.palette()
        central_palette.setColor(QPalette.Window, QColor("#050505"))
        self.central.setPalette(central_palette)
        self.central.setStyleSheet("#viewerCentral { background: #050505; }")
        self.grid = QGridLayout(self.central)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.setCentralWidget(self.central)
        self.labels = []
        self.video_frame = QFrame(self.central)
        self.video_frame.setObjectName("videoFrame")
        self.video_frame.setAttribute(Qt.WA_StyledBackground, True)
        self.video_frame.setStyleSheet("background: #000;")
        self.video_frame.setAutoFillBackground(True)
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.setMouseTracking(True)
        self.video_frame.setAttribute(Qt.WA_NativeWindow, True)
        self.video_frame.setProperty("videoPoolSlot", 0)
        self.central.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.installEventFilter(self)
        # Keep the HWND alive until its libVLC player has been released.  VLC
        # may otherwise create a visible fallback Direct3D top-level window.
        self.video_frames = [self.video_frame]
        self.video_frame_pools = {0: [self.video_frame]}
        self.central.installEventFilter(self)
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self.delete_shortcut.setContext(Qt.ApplicationShortcut)
        self.delete_shortcut.activated.connect(self.request_delete_current)

        self.overlay_timer = QTimer(self)
        self.overlay_timer.setSingleShot(True)
        self.overlay_timer.timeout.connect(self.hide_overlays)

        self.viewer_overlay = QFrame(self.central)
        self.viewer_overlay.setObjectName("viewerOverlay")
        self.viewer_overlay.setStyleSheet("""
            #viewerOverlay { background: rgba(28,25,36,235); border: 1px solid rgba(151,126,218,145); border-radius: 10px; color: white; }
            #viewerOverlay QLabel { background: transparent; color: #f5f1fc; }
            QPushButton, QComboBox, QToolButton, QLineEdit { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 9px; }
            QPushButton:hover, QComboBox:hover, QToolButton:hover { background: #3b3549; border-color: #927bd8; }
            QPushButton:checked { background: #927bd8; border-color: #ad99e8; color: white; font-weight: 700; }
        """)
        overlay_layout = QHBoxLayout(self.viewer_overlay)
        overlay_layout.setContentsMargins(8, 6, 8, 6)
        overlay_layout.setSpacing(6)
        self.top_filename_label = QLabel("")
        self.top_filename_label.setMinimumWidth(180)
        overlay_layout.addWidget(self.top_filename_label)
        overlay_layout.addWidget(QLabel("Mode"))
        self.mode_btn = QToolButton()
        self.mode_btn.setPopupMode(QToolButton.InstantPopup)
        self.mode_btn.setMenu(self.build_mode_menu())
        overlay_layout.addWidget(self.mode_btn)
        self.fit_combo = QComboBox()
        self.fit_combo.addItems(["manual", "actual", "fit_height", "fit_width", "fit_window"])
        self.fit_combo.setCurrentText(self.fit_mode)
        popup_palette = self.fit_combo.view().palette()
        popup_palette.setColor(QPalette.Window, QColor("#211e29"))
        popup_palette.setColor(QPalette.Base, QColor("#211e29"))
        popup_palette.setColor(QPalette.Text, QColor("#f5f1fc"))
        popup_palette.setColor(QPalette.Highlight, QColor("#7560b4"))
        popup_palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        self.fit_combo.view().setPalette(popup_palette)
        self.fit_combo.view().viewport().setPalette(popup_palette)
        self.fit_combo.view().setStyleSheet(VIEWER_COMBO_POPUP_STYLE)
        self.fit_combo.view().viewport().setAutoFillBackground(True)
        self.fit_combo.currentTextChanged.connect(self.set_fit_mode)
        overlay_layout.addWidget(QLabel("Fit"))
        overlay_layout.addWidget(self.fit_combo)
        self.manual_zoom_edit = QLineEdit()
        self.manual_zoom_edit.setFixedWidth(72)
        self.manual_zoom_edit.setAlignment(Qt.AlignCenter)
        self.manual_zoom_edit.editingFinished.connect(self.apply_manual_zoom_text)
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setFixedWidth(34)
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedWidth(34)
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        overlay_layout.addWidget(self.manual_zoom_edit)
        overlay_layout.addWidget(self.zoom_out_btn)
        overlay_layout.addWidget(self.zoom_in_btn)
        self.lock_btn = QPushButton("Lock")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setChecked(self.zoom_locked)
        self.lock_btn.clicked.connect(self.toggle_zoom_lock)
        overlay_layout.addWidget(self.lock_btn)
        self.update_mode_button()
        self.update_manual_zoom_controls()
        self.viewer_overlay.hide()

        self.rotation_overlay = QFrame(self.central)
        self.rotation_overlay.setObjectName("rotationOverlay")
        self.rotation_overlay.setStyleSheet("""
            #rotationOverlay { background: rgba(28,25,36,235); border: 1px solid rgba(151,126,218,145); border-radius: 10px; color: white; }
            #rotationOverlay QLabel { background: transparent; color: #f5f1fc; }
            QPushButton { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 11px; }
            QPushButton:hover { background: #3b3549; border-color: #927bd8; }
            QPushButton::menu-indicator { image: none; width: 0px; }
        """)
        rotate_layout = QHBoxLayout(self.rotation_overlay)
        rotate_layout.setContentsMargins(8, 6, 8, 6)
        rotate_layout.setSpacing(6)
        self.rotation_filename_label = QLabel("")
        self.rotation_filename_label.setMinimumWidth(180)
        rotate_layout.addWidget(self.rotation_filename_label)
        self.rotate_left_btn = QPushButton("↶")
        self.rotate_left_btn.setToolTip("Rotate left 90 degrees")
        self.rotate_left_btn.clicked.connect(self.rotate_left)
        self.rotate_reset_btn = QPushButton("0")
        self.rotate_reset_btn.setToolTip("Reset rotation")
        self.rotate_reset_btn.clicked.connect(self.reset_rotation)
        self.rotate_right_btn = QPushButton("↷")
        self.rotate_right_btn.setToolTip("Rotate right 90 degrees")
        self.rotate_right_btn.clicked.connect(self.rotate_right)
        rotate_layout.addWidget(self.rotate_left_btn)
        rotate_layout.addWidget(self.rotate_reset_btn)
        rotate_layout.addWidget(self.rotate_right_btn)
        self.animated_rate_btn = self.create_playback_rate_button("animatedRateButton")
        self.animated_rate_btn.setToolTip("Animated image playback speed")
        self.animated_rate_btn.setAccessibleName("Animated image playback speed")
        self.animated_rate_btn.hide()
        rotate_layout.addWidget(self.animated_rate_btn)
        self.rotation_overlay.hide()

        self.video_overlay = QFrame(self.central)
        self.video_overlay.setObjectName("videoOverlay")
        self.video_overlay.setStyleSheet("""
            #videoOverlay { background: rgba(28,25,36,238); border: 1px solid rgba(151,126,218,150); border-radius: 10px; color: white; }
            #videoOverlay QLabel { background: transparent; color: #f5f1fc; }
            QPushButton { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 9px; }
            QPushButton:hover { background: #3b3549; border-color: #927bd8; }
            QPushButton:checked { background: #927bd8; border-color: #ad99e8; color: white; font-weight: 700; }
            QPushButton#videoLoopButton { padding: 0; font-size: 15px; font-weight: 700; }
            QPushButton::menu-indicator { image: none; width: 0px; }
            QSlider::groove:horizontal { height: 5px; background: #4b4559; border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #a991e8; }
        """)
        video_layout = QHBoxLayout(self.video_overlay)
        video_layout.setContentsMargins(8, 6, 8, 6)
        video_layout.setSpacing(6)
        self.video_filename_label = QLabel("")
        self.video_filename_label.setMinimumWidth(180)
        self.play_btn = QPushButton("Play/Pause")
        self.play_btn.clicked.connect(self.toggle_play)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_media)
        self.video_rate_btn = self.create_playback_rate_button("videoRateButton")
        self.video_rate_btn.setToolTip("Video playback speed")
        self.video_rate_btn.setAccessibleName("Video playback speed")
        self.video_loop_btn = QPushButton("∞")
        self.video_loop_btn.setObjectName("videoLoopButton")
        self.video_loop_btn.setCheckable(True)
        self.video_loop_btn.setChecked(self.video_loop_enabled)
        self.video_loop_btn.setFixedSize(34, 28)
        self.video_loop_btn.setToolTip("Loop all visible videos")
        self.video_loop_btn.setAccessibleName("Loop videos")
        self.video_loop_btn.toggled.connect(self.set_video_loop_enabled)
        self.time_label = QLabel("00:00 / 00:00")
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderPressed.connect(self.begin_video_seek)
        self.seek_slider.sliderReleased.connect(self.finish_video_seek)
        self.seek_slider.sliderMoved.connect(self.preview_video_seek)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.valueChanged.connect(self.set_video_volume)
        video_layout.addWidget(self.video_filename_label)
        video_layout.addWidget(self.play_btn)
        video_layout.addWidget(self.stop_btn)
        video_layout.addWidget(self.video_rate_btn)
        video_layout.addWidget(self.video_loop_btn)
        video_layout.addWidget(self.time_label)
        video_layout.addWidget(self.seek_slider, 1)
        video_layout.addWidget(QLabel("Vol"))
        video_layout.addWidget(self.volume_slider)
        self.video_overlay.hide()

        self.webtoon_auto_scroll_overlay = QFrame(self.central)
        self.webtoon_auto_scroll_overlay.setObjectName("webtoonAutoScrollOverlay")
        self.webtoon_auto_scroll_overlay.setStyleSheet("""
            #webtoonAutoScrollOverlay { background: rgba(28,25,36,238); border: 1px solid rgba(151,126,218,150); border-radius: 10px; color: white; }
            QPushButton, QLineEdit { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 8px; }
            QPushButton:hover { background: #3b3549; border-color: #927bd8; }
            QPushButton:checked { background: #927bd8; border-color: #ad99e8; color: white; font-weight: 700; }
            QLineEdit { min-width: 54px; }
        """)
        auto_scroll_layout = QVBoxLayout(self.webtoon_auto_scroll_overlay)
        auto_scroll_layout.setContentsMargins(8, 8, 8, 8)
        auto_scroll_layout.setSpacing(6)
        self.webtoon_auto_scroll_toggle_btn = QPushButton("ON")
        self.webtoon_auto_scroll_toggle_btn.setCheckable(True)
        self.webtoon_auto_scroll_toggle_btn.setToolTip("Ctrl+Space")
        self.webtoon_auto_scroll_toggle_btn.clicked.connect(self.toggle_webtoon_auto_scroll)
        auto_scroll_layout.addWidget(self.webtoon_auto_scroll_toggle_btn)
        self.webtoon_auto_scroll_speed_buttons = {}
        for mode, label in [
            ("slow", f"느림 ({WEBTOON_AUTO_SCROLL_SPEEDS['slow']})"),
            ("normal", f"보통 ({WEBTOON_AUTO_SCROLL_SPEEDS['normal']})"),
            ("fast", f"빠름 ({WEBTOON_AUTO_SCROLL_SPEEDS['fast']})"),
        ]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, value=mode: self.set_webtoon_auto_scroll_speed_mode(value))
            auto_scroll_layout.addWidget(button)
            self.webtoon_auto_scroll_speed_buttons[mode] = button
        manual_row = QHBoxLayout()
        manual_row.setContentsMargins(0, 0, 0, 0)
        manual_row.setSpacing(4)
        self.webtoon_auto_scroll_manual_btn = QPushButton("매뉴얼")
        self.webtoon_auto_scroll_manual_btn.setCheckable(True)
        self.webtoon_auto_scroll_manual_btn.clicked.connect(lambda: self.set_webtoon_auto_scroll_speed_mode("manual"))
        self.webtoon_auto_scroll_manual_edit = QLineEdit(str(self.webtoon_auto_scroll_manual_speed))
        self.webtoon_auto_scroll_manual_edit.setAlignment(Qt.AlignCenter)
        self.webtoon_auto_scroll_manual_edit.setValidator(QIntValidator(WEBTOON_AUTO_SCROLL_MIN_SPEED, WEBTOON_AUTO_SCROLL_MAX_SPEED, self))
        self.webtoon_auto_scroll_manual_edit.editingFinished.connect(self.apply_webtoon_auto_scroll_manual_speed)
        manual_row.addWidget(self.webtoon_auto_scroll_manual_btn)
        manual_row.addWidget(self.webtoon_auto_scroll_manual_edit)
        auto_scroll_layout.addLayout(manual_row)
        self.webtoon_auto_scroll_overlay.hide()

        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update_video_controls)
        self.video_ready_timer = QTimer(self)
        self.video_ready_timer.setInterval(30)
        self.video_ready_timer.timeout.connect(self.poll_video_output_ready)
        # A single coalescing timer prevents a resize/zoom gesture from
        # launching two full image decodes for every intermediate geometry.
        self.image_update_timer = QTimer(self)
        self.image_update_timer.setSingleShot(True)
        self.image_update_timer.setInterval(60)
        self.image_update_timer.timeout.connect(self._apply_scheduled_image_update)
        self.image_update_pending_generation = None
        self.image_update_token = 0
        self.video_cleanup_idle_timer = QTimer(self)
        self.video_cleanup_idle_timer.setSingleShot(True)
        self.video_cleanup_idle_timer.setInterval(VIDEO_CLEANUP_IDLE_MS)
        self.video_cleanup_idle_timer.timeout.connect(self._flush_deferred_video_cleanup)
        self.vlc_prewarm_timer = QTimer(self)
        self.vlc_prewarm_timer.setSingleShot(True)
        self.vlc_prewarm_timer.setInterval(450)
        self.vlc_prewarm_timer.timeout.connect(self._init_vlc_async)
        self.animated_image_timer = QTimer(self)
        self.animated_image_timer.timeout.connect(self.advance_animated_image)
        self.webtoon_idle_timer = QTimer(self)
        self.webtoon_idle_timer.setInterval(120)
        self.webtoon_idle_timer.timeout.connect(self.load_next_webtoon_idle_image)
        self.webtoon_build_timer = QTimer(self)
        self.webtoon_build_timer.setInterval(4)
        self.webtoon_build_timer.timeout.connect(self.append_webtoon_labels)
        self.webtoon_pending_paths = []
        self.webtoon_container_layout = None
        self.webtoon_build_generation = 0
        self.webtoon_auto_scroll_timer = QTimer(self)
        self.webtoon_auto_scroll_timer.setInterval(16)
        self.webtoon_auto_scroll_timer.timeout.connect(self.advance_webtoon_auto_scroll)
        self.webtoon_auto_scroll_hide_timer = QTimer(self)
        self.webtoon_auto_scroll_hide_timer.setSingleShot(True)
        self.webtoon_auto_scroll_hide_timer.timeout.connect(self.hide_webtoon_auto_scroll_overlay)
        self.viewer_preload_timer = QTimer(self)
        self.viewer_preload_timer.setInterval(55)
        self.viewer_preload_timer.timeout.connect(self.process_next_viewer_preload)
        self.input_layer = QWidget(self.central)
        self.input_layer.setObjectName("viewerInputLayer")
        self.input_layer.setMouseTracking(True)
        self.input_layer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.input_layer.setStyleSheet("background: transparent;")
        self.input_layer.installEventFilter(self)
        self.input_layer.hide()
        self.update_webtoon_auto_scroll_controls()

    def apply_performance_policy(self, policy=None):
        """Refresh worker limits after the existing settings dialog saves."""
        self.performance_policy = policy or performance_policy_for(self.settings)
        if hasattr(self, "decode_pool"):
            self.decode_pool.setMaxThreadCount(max(1, int(self.performance_policy.viewer_decode_workers)))
        if hasattr(self, "animated_image_pool"):
            self.animated_image_pool.setMaxThreadCount(max(1, int(self.performance_policy.animation_workers)))

    def create_playback_rate_button(self, object_name):
        button = QPushButton(format_playback_rate(self.playback_rate))
        button.setObjectName(object_name)
        button.setFixedSize(58, 28)
        menu = QMenu(button)
        menu.setObjectName("playbackRateMenu")
        menu.setStyleSheet("""
            QMenu#playbackRateMenu { background: #211e29; color: #f5f1fc; border: 1px solid #5d5275; border-radius: 7px; padding: 5px; }
            QMenu#playbackRateMenu::item { min-width: 76px; padding: 6px 12px; border-radius: 5px; }
            QMenu#playbackRateMenu::item:selected { background: #7560b4; color: white; }
            QMenu#playbackRateMenu::item:checked { background: #927bd8; color: white; }
            QLineEdit { min-width: 82px; background: #302c3b; color: #f5f1fc; border: 1px solid #5d5275; border-radius: 5px; padding: 5px 7px; }
        """)
        custom_edit = QLineEdit(menu)
        custom_edit.setPlaceholderText("Input...")
        custom_edit.setToolTip(f"{PLAYBACK_RATE_MIN:g}x - {PLAYBACK_RATE_MAX:g}x")
        input_action = QWidgetAction(menu)
        input_action.setDefaultWidget(custom_edit)
        menu.addAction(input_action)
        menu.addSeparator()
        rate_actions = {}
        for rate in PLAYBACK_RATE_PRESETS:
            action = menu.addAction(format_playback_rate(rate))
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, value=rate: self.set_playback_rate(value))
            rate_actions[rate] = action
        custom_edit.returnPressed.connect(
            lambda edit=custom_edit, popup=menu: self.apply_custom_playback_rate(edit, popup)
        )
        menu.aboutToShow.connect(lambda edit=custom_edit: self.prepare_playback_rate_input(edit))
        button.setMenu(menu)
        button.playback_rate_menu = menu
        button.playback_rate_edit = custom_edit
        button.playback_rate_actions = rate_actions
        return button

    def prepare_playback_rate_input(self, edit):
        edit.setText("")
        edit.setStyleSheet("")

    def apply_custom_playback_rate(self, edit, menu):
        if self.set_playback_rate(edit.text()):
            edit.setStyleSheet("")
            menu.close()
            return
        edit.setStyleSheet("border: 1px solid #d56f7b;")
        edit.selectAll()

    def sync_playback_rate_controls(self):
        label = format_playback_rate(self.playback_rate)
        for button_name in ("video_rate_btn", "animated_rate_btn"):
            button = getattr(self, button_name, None)
            if button is None:
                continue
            button.setText(label)
            for rate, action in getattr(button, "playback_rate_actions", {}).items():
                action.setChecked(math.isclose(rate, self.playback_rate, abs_tol=0.0005))

    def set_playback_rate(self, value):
        rate = normalize_playback_rate(value)
        if rate is None:
            return False
        self.playback_rate = rate
        self.sync_playback_rate_controls()
        for state in list(self.animated_image_states.values()):
            task = state.get("task")
            if task is not None:
                task.set_playback_rate(rate)
        players = [self.media_player, *self.extra_media_players]
        players.extend(state.get("player") for state in self.video_slot_states.values())
        seen = set()
        for player in players:
            if player is None or id(player) in seen:
                continue
            seen.add(id(player))
            self.apply_video_playback_rate(player)
        return True

    def apply_video_playback_rate(self, player):
        if player is None:
            return False
        try:
            result = player.set_rate(float(self.playback_rate))
            return result is None or int(result) == 0
        except Exception:
            return False

    def build_mode_menu(self):
        menu = QMenu(self.mode_btn)
        menu.setStyleSheet(VIEWER_POPUP_MENU_STYLE)
        menu.addAction("single", lambda: self.set_viewer_mode("single"))
        double_menu = menu.addMenu("double")
        double_menu.addAction("1,2 / 3,4", lambda: self.set_viewer_mode("double", "page"))
        double_menu.addAction("2,1 / 4,3", lambda: self.set_viewer_mode("double", "manga_page"))
        double_menu.addAction("slide", lambda: self.set_viewer_mode("double", "slide"))
        triple_menu = menu.addMenu("triple")
        triple_menu.addAction("page", lambda: self.set_viewer_mode("triple", "page"))
        triple_menu.addAction("slide", lambda: self.set_viewer_mode("triple", "slide"))
        menu.addAction("webtoon", lambda: self.set_viewer_mode("webtoon_vertical"))
        return menu

    def update_mode_button(self):
        if self.viewer_mode == "double" and self.step_mode == "manga_page":
            self.mode_btn.setText("double 2,1")
        elif self.viewer_mode in ("double", "triple"):
            self.mode_btn.setText(f"{self.viewer_mode} {self.step_mode}")
        elif self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.mode_btn.setText("webtoon")
        else:
            self.mode_btn.setText("single")

    def update_manual_zoom_controls(self):
        is_manual = self.fit_mode == "manual"
        for widget in (self.manual_zoom_edit, self.zoom_out_btn, self.zoom_in_btn):
            widget.setVisible(is_manual)
        self.update_manual_zoom_text()
        if hasattr(self, "rotation_overlay") and hasattr(self, "video_overlay"):
            self.position_overlays()

    def update_manual_zoom_text(self):
        if hasattr(self, "manual_zoom_edit"):
            self.manual_zoom_edit.setText(f"{round(self.zoom_factor * 100)}%")

    def apply_manual_zoom_text(self):
        text = self.manual_zoom_edit.text().strip().replace("%", "")
        try:
            percent = float(text)
        except ValueError:
            self.update_manual_zoom_text()
            return
        percent = max(5.0, min(1000.0, percent))
        self.zoom_factor = percent / 100.0
        if self.fit_mode != "manual":
            self.fit_mode = "manual"
            self.fit_combo.blockSignals(True)
            self.fit_combo.setCurrentText("manual")
            self.fit_combo.blockSignals(False)
            self.settings["default_fit"] = "manual"
            save_settings(self.settings)
        self.update_manual_zoom_text()
        self.update_manual_zoom_controls()
        self.schedule_image_update()

    def is_webtoon_viewer_mode(self):
        return self.viewer_mode in ("webtoon", "webtoon_vertical")

    def webtoon_auto_scroll_speed(self):
        if self.webtoon_auto_scroll_speed_mode == "manual":
            return max(
                WEBTOON_AUTO_SCROLL_MIN_SPEED,
                min(WEBTOON_AUTO_SCROLL_MAX_SPEED, int(self.webtoon_auto_scroll_manual_speed)),
            )
        return WEBTOON_AUTO_SCROLL_SPEEDS.get(self.webtoon_auto_scroll_speed_mode, WEBTOON_AUTO_SCROLL_SPEEDS["normal"])

    def set_webtoon_auto_scroll_speed_mode(self, mode):
        if mode not in (*WEBTOON_AUTO_SCROLL_SPEEDS.keys(), "manual"):
            mode = "normal"
        self.webtoon_auto_scroll_speed_mode = mode
        self.settings["webtoon_auto_scroll_speed_mode"] = mode
        save_settings(self.settings)
        self.update_webtoon_auto_scroll_controls()

    def apply_webtoon_auto_scroll_manual_speed(self):
        text = self.webtoon_auto_scroll_manual_edit.text().strip()
        try:
            speed = int(text)
        except ValueError:
            speed = self.webtoon_auto_scroll_manual_speed
        speed = max(WEBTOON_AUTO_SCROLL_MIN_SPEED, min(WEBTOON_AUTO_SCROLL_MAX_SPEED, speed))
        self.webtoon_auto_scroll_manual_speed = speed
        self.webtoon_auto_scroll_manual_edit.setText(str(speed))
        self.settings["webtoon_auto_scroll_manual_speed"] = speed
        save_settings(self.settings)
        self.set_webtoon_auto_scroll_speed_mode("manual")

    def update_webtoon_auto_scroll_controls(self):
        if not hasattr(self, "webtoon_auto_scroll_toggle_btn"):
            return
        self.webtoon_auto_scroll_toggle_btn.setText("OFF" if self.webtoon_auto_scroll_active else "ON")
        self.webtoon_auto_scroll_toggle_btn.setChecked(self.webtoon_auto_scroll_active)
        for mode, button in self.webtoon_auto_scroll_speed_buttons.items():
            button.setChecked(self.webtoon_auto_scroll_speed_mode == mode)
        self.webtoon_auto_scroll_manual_btn.setChecked(self.webtoon_auto_scroll_speed_mode == "manual")
        if not self.webtoon_auto_scroll_manual_edit.hasFocus():
            self.webtoon_auto_scroll_manual_edit.setText(str(self.webtoon_auto_scroll_manual_speed))

    def toggle_webtoon_auto_scroll(self):
        if not self.is_webtoon_viewer_mode() or not self.webtoon_scroll:
            return
        if self.webtoon_auto_scroll_active:
            self.stop_webtoon_auto_scroll()
        else:
            self.start_webtoon_auto_scroll()
        self.show_webtoon_auto_scroll_overlay()

    def start_webtoon_auto_scroll(self):
        if not self.is_webtoon_viewer_mode() or not self.webtoon_scroll:
            return
        self.webtoon_auto_scroll_active = True
        self.webtoon_auto_scroll_remainder = 0.0
        self.webtoon_auto_scroll_last_tick = time.monotonic()
        self.webtoon_auto_scroll_timer.start()
        self.update_webtoon_auto_scroll_controls()

    def stop_webtoon_auto_scroll(self):
        self.webtoon_auto_scroll_active = False
        self.webtoon_auto_scroll_remainder = 0.0
        if hasattr(self, "webtoon_auto_scroll_timer"):
            self.webtoon_auto_scroll_timer.stop()
        self.update_webtoon_auto_scroll_controls()

    def advance_webtoon_auto_scroll(self):
        if not self.webtoon_auto_scroll_active or not self.is_webtoon_viewer_mode() or not self.webtoon_scroll:
            self.stop_webtoon_auto_scroll()
            return
        now = time.monotonic()
        elapsed = max(0.0, min(0.25, now - self.webtoon_auto_scroll_last_tick))
        self.webtoon_auto_scroll_last_tick = now
        self.webtoon_auto_scroll_remainder += self.webtoon_auto_scroll_speed() * elapsed
        pixels = int(self.webtoon_auto_scroll_remainder)
        if pixels <= 0:
            return
        self.webtoon_auto_scroll_remainder -= pixels
        bar = self.webtoon_scroll.verticalScrollBar()
        old_value = bar.value()
        bar.setValue(min(bar.maximum(), old_value + pixels))
        if bar.value() >= bar.maximum() and bar.value() == old_value:
            self.stop_webtoon_auto_scroll()

    def show_webtoon_auto_scroll_overlay(self):
        if not self.is_webtoon_viewer_mode():
            self.webtoon_auto_scroll_overlay.hide()
            return
        self.update_webtoon_auto_scroll_controls()
        self.position_overlays()
        self.webtoon_auto_scroll_overlay.show()
        self.webtoon_auto_scroll_overlay.raise_()
        self.webtoon_auto_scroll_hide_timer.start(5000)

    def hide_webtoon_auto_scroll_overlay(self):
        if self.webtoon_auto_scroll_manual_edit.hasFocus():
            self.webtoon_auto_scroll_hide_timer.start(5000)
            return
        self.webtoon_auto_scroll_overlay.hide()

    def _build_shortcuts(self):
        mapping = {
            "next_media": self.next_media,
            "previous_media": self.previous_media,
            "first_media": self.first_media,
            "last_media": self.last_media,
            "zoom_in": self.zoom_in,
            "zoom_out": self.zoom_out,
            "fit_height": lambda: self.set_fit_mode("fit_height"),
            "fit_width": lambda: self.set_fit_mode("fit_width"),
            "fit_window": lambda: self.set_fit_mode("fit_window"),
            "actual_size": lambda: self.set_fit_mode("actual"),
            "toggle_zoom_lock": self.toggle_zoom_lock,
            "toggle_play": self.toggle_play,
            "toggle_fullscreen": self.toggle_fullscreen,
            "rotate_right": self.rotate_right,
            "rotate_left": self.rotate_left,
            "reset_rotation": self.reset_rotation,
            "viewer_single": lambda: self.set_viewer_mode("single"),
            "viewer_double": lambda: self.set_viewer_mode("double", "page"),
            "viewer_triple": lambda: self.set_viewer_mode("triple", "page"),
            "viewer_webtoon": lambda: self.set_viewer_mode("webtoon_vertical"),
        }
        for action, callback in mapping.items():
            for seq in self.settings.get("shortcuts", {}).get(action, []):
                if action in ("zoom_in", "zoom_out") and seq.strip() in ("+", "-"):
                    # Plain +/- are handled from the actual key event below so
                    # the main keyboard row and numeric keypad behave equally.
                    continue
                if action == "toggle_play" and seq == "Space":
                    continue
                if seq.startswith("Mouse") or seq.startswith("Wheel"):
                    continue
                shortcut = QShortcut(QKeySequence(seq), self)
                shortcut.setContext(Qt.ApplicationShortcut)
                shortcut.activated.connect(callback)
        self.webtoon_auto_scroll_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.webtoon_auto_scroll_shortcut.setContext(Qt.ApplicationShortcut)
        self.webtoon_auto_scroll_shortcut.activated.connect(self.toggle_webtoon_auto_scroll)

    def _init_vlc_async(self):
        if self.vlc_instance is not None or self.vlc_init_inflight or vlc is None:
            return
        self.vlc_init_inflight = True
        self.vlc_init_error = ""
        task = VlcInitTask(vlc)
        self.vlc_init_task_refs.add(task)
        task.signals.finished.connect(
            self._vlc_init_finished,
            Qt.QueuedConnection,
        )
        self.vlc_init_thread = threading.Thread(
            target=task.run,
            name="PhotoViewer-VLC-Init",
            daemon=True,
        )
        self.vlc_init_thread.start()

    def _configure_media_player(self, player):
        if player is None:
            return
        try:
            player.video_set_mouse_input(False)
            player.video_set_key_input(False)
        except Exception:
            pass
        # A libVLC player can retain vout geometry overrides across media.
        # Always start a new slot from VLC's native automatic layout, then
        # apply the selected viewer fit mode after the vout reports its source
        # size.  Resetting aspect/crop here is especially important for mixed
        # SAR, rotated, MP4 and MKV sequences.
        for method_name, value in (
            ("video_set_scale", 0.0),
            ("video_set_aspect_ratio", None),
            ("video_set_crop_geometry", None),
        ):
            try:
                getattr(player, method_name)(value)
            except Exception:
                pass

    def _vlc_init_finished(self, instance, bundles, error, task):
        self.vlc_init_task_refs.discard(task)
        self.vlc_init_inflight = False
        self.vlc_init_error = error or ""
        if self.app_closing:
            for _player_instance, player in list(bundles or []):
                try:
                    player.release()
                except Exception:
                    pass
            try:
                if instance is not None:
                    instance.release()
            except Exception:
                pass
            return
        pending = list(self.pending_video_requests)
        self.pending_video_requests = []
        bundles = list(bundles or [])
        players = [player for _player_instance, player in bundles]
        if instance is None or not players:
            self.vlc_instance = None
            self.media_player = None
            for request in pending:
                if request["generation"] == self.render_generation:
                    self._show_video_status(
                        request["frame"],
                        "VLC runtime not available\n" + request["path"].name,
                    )
            return
        self.vlc_instance = instance
        self.media_player = None
        for player_instance, player in bundles:
            self.video_player_instances[id(player)] = player_instance
            self._configure_media_player(player)
        if not pending and not self.is_active_viewer():
            self._queue_video_cleanup(players)
            return
        self.video_standby_players.extend(players)
        for request in pending:
            if request["generation"] != self.render_generation or not self.is_active_viewer():
                continue
            frame = request["frame"]
            try:
                if (
                    frame is None
                    or frame.parent() is None
                    or self.grid.indexOf(frame) < 0
                    or frame.property("videoGeneration") != request["generation"]
                    or frame.property("videoPath") != str(request["path"])
                    or frame.property("videoSlot") != request["slot"]
                ):
                    continue
            except RuntimeError:
                continue
            self._start_video_playback(
                request["path"],
                frame,
                primary=request["primary"],
            )

    def _ensure_video_standby_players(self):
        if (
            self.vlc_instance is None
            or self.video_player_create_inflight
            or self.video_cleanup_closed
            or self.video_cleanup_inflight
            or self.video_retired_players
        ):
            return
        missing = max(0, int(self.performance_policy.video_standby_target) - len(self.video_standby_players))
        if missing <= 0:
            return
        self.video_player_create_inflight = True
        task = VideoPlayerCreateTask(self.vlc_instance, missing)
        self.video_player_create_task_refs.add(task)
        task.signals.finished.connect(
            self._video_player_fill_finished,
            Qt.QueuedConnection,
        )
        self.video_player_create_thread = threading.Thread(
            target=task.run,
            name="PhotoViewer-VLC-PlayerFill",
            daemon=True,
        )
        self.video_player_create_thread.start()

    def _video_player_fill_finished(self, bundles, error, task):
        self.video_player_create_task_refs.discard(task)
        self.video_player_create_inflight = False
        bundles = list(bundles or [])
        players = [player for _player_instance, player in bundles]
        for player_instance, player in bundles:
            self.video_player_instances[id(player)] = player_instance
            self._configure_media_player(player)
        if self.video_cleanup_closed or self.vlc_instance is None or not self.is_active_viewer():
            self._queue_video_cleanup(players)
            return
        self.video_standby_players.extend(players)
        self._dispatch_pending_video_requests()
        if self.pending_video_requests:
            QTimer.singleShot(0, self._ensure_video_standby_players)
        self._resume_pending_navigation()

    def _dispatch_pending_video_requests(self):
        pending = list(self.pending_video_requests)
        self.pending_video_requests = []
        for request in pending:
            if request["generation"] != self.render_generation:
                continue
            frame = request["frame"]
            try:
                if (
                    frame is None
                    or frame.parent() is None
                    or self.grid.indexOf(frame) < 0
                    or frame.property("videoGeneration") != request["generation"]
                    or frame.property("videoPath") != str(request["path"])
                    or frame.property("videoSlot") != request["slot"]
                ):
                    continue
            except RuntimeError:
                continue
            self._start_video_playback(
                request["path"],
                frame,
                primary=request["primary"],
            )

    def _mark_video_ended(self, token):
        token = int(token)
        state = self.video_slot_states.get(token)
        if state is None or state.get("generation") != self.render_generation:
            return
        state["ended"] = True
        if state.get("primary") and self.video_path is not None:
            self.video_finished = True
        if self.video_loop_enabled:
            QTimer.singleShot(0, lambda current=token: self._restart_video_slot(current))

    def _video_event_type(self, name):
        if vlc is None:
            return None
        return getattr(getattr(vlc, "EventType", None), name, None)

    def _attach_video_ready_events(self, token, state):
        # Do not bridge libVLC Vout/TimeChanged callbacks into Qt.  Apart from
        # arriving for an obsolete vout, python-vlc can invoke them on a native
        # callback thread where PySide signal overload resolution is unsafe.
        # The active 30 ms timer performs the authoritative readiness checks.
        state["ready_callbacks"] = []
        self.video_ready_callbacks[int(token)] = []

    def _begin_video_surface_wait(self, token):
        state = self.video_slot_states.get(int(token))
        if state is None:
            return None
        state["playback_serial"] = int(state.get("playback_serial", 0)) + 1
        state["revealed"] = False
        state["ready_started"] = time.monotonic()
        state["ready_event_seen"] = False
        state["ready_samples"] = 0
        state["last_ready_time"] = -1
        state["media_committed"] = False
        # A new Direct3D vout does not inherit all geometry overrides applied
        # to the previous vout.  Never let the fit cache survive this boundary.
        state["fit_signature"] = None
        serial = state["playback_serial"]
        frame = state.get("frame")
        path = Path(state.get("path"))
        if frame is not None:
            self._show_video_status(frame, "Loading…\n" + path.name)
        self._attach_video_ready_events(int(token), state)
        if not self.video_ready_timer.isActive():
            self.video_ready_timer.start()
        return serial

    def _mark_video_output_ready(self, token, serial):
        token = int(token)
        serial = int(serial)
        state = self.video_slot_states.get(token)
        if (
            state is None
            or state.get("generation") != self.render_generation
            or int(state.get("playback_serial", -1)) != serial
            or state.get("revealed")
        ):
            return
        # VLC events are only wake-up hints.  Vout/TimeChanged can be emitted by
        # the previous Direct3D output while its final frame is still resident.
        # The polling gate below validates the current media and real progress.
        state["ready_event_seen"] = True
        QTimer.singleShot(0, self.poll_video_output_ready)

    @staticmethod
    def _media_identity(media):
        if media is None:
            return ""
        try:
            mrl = media.get_mrl()
            if mrl:
                return str(mrl)
        except Exception:
            pass
        return str(media)

    def _video_slot_is_ready(self, state):
        player = state.get("player")
        if player is None or not state.get("media_committed"):
            return False
        try:
            current_media = player.get_media()
        except Exception:
            current_media = getattr(player, "media", None)
        expected = str(state.get("expected_media_identity") or "")
        if expected and self._media_identity(current_media) != expected:
            return False
        try:
            media_time = int(player.get_time())
        except Exception:
            media_time = -1
        try:
            has_vout = int(player.has_vout())
        except Exception:
            has_vout = -1
        try:
            player_state = player.get_state()
        except Exception:
            player_state = None
        playable_states = {
            getattr(getattr(vlc, "State", None), "Playing", None),
            getattr(getattr(vlc, "State", None), "Paused", None),
        }
        valid = media_time > 0 and has_vout > 0 and player_state in playable_states
        if not valid:
            state["ready_samples"] = 0
            state["last_ready_time"] = media_time
            return False
        last_time = int(state.get("last_ready_time", -1))
        state["last_ready_time"] = media_time
        if last_time >= 0 and media_time >= last_time:
            state["ready_samples"] = int(state.get("ready_samples", 0)) + 1
        else:
            state["ready_samples"] = 1
        return int(state.get("ready_samples", 0)) >= 2

    @staticmethod
    def _native_video_frame_size(frame):
        """Return the VLC HWND client size in physical pixels.

        Qt widget sizes are logical pixels.  libVLC video_set_scale operates
        on the native Direct3D surface, so using frame.width()/height() on a
        125-200% DPI display under-scales the video and leaves a black strip.
        """
        if frame is None:
            return QSize()
        if sys.platform == "win32":
            try:
                rect = wintypes.RECT()
                if ctypes.windll.user32.GetClientRect(
                    wintypes.HWND(int(frame.winId())), ctypes.byref(rect)
                ):
                    width = int(rect.right - rect.left)
                    height = int(rect.bottom - rect.top)
                    if width > 0 and height > 0:
                        return QSize(width, height)
            except Exception:
                pass
        try:
            dpr = max(1.0, float(frame.devicePixelRatioF()))
        except Exception:
            dpr = 1.0
        return QSize(
            max(1, round(frame.width() * dpr)),
            max(1, round(frame.height() * dpr)),
        )

    @staticmethod
    def _ratio_text(numerator, denominator):
        numerator = max(1, int(numerator))
        denominator = max(1, int(denominator))
        divisor = math.gcd(numerator, denominator)
        return f"{numerator // divisor}:{denominator // divisor}"

    @staticmethod
    def _vlc_video_track_geometry(player):
        """Read coded size, SAR and orientation from the current VLC media.

        Do not infer source geometry from VLC's output child HWND: that child
        can still carry the preceding media's vout state during a transition.
        python-vlc 3.0.21203 also declares libvlc_media_track_t's C union as
        three sequential pointers, so use the native VLC 3.x layout above.
        """
        if player is None or vlc is None or "_VlcMediaTrack" not in globals():
            return None
        try:
            media = player.get_media()
        except Exception:
            return None
        if media is None:
            return None
        tracks = ctypes.POINTER(ctypes.POINTER(_VlcMediaTrack))()
        count = 0
        try:
            tracks_get = vlc.dll.libvlc_media_tracks_get
            tracks_get.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_VlcMediaTrack))),
            ]
            tracks_get.restype = ctypes.c_uint
            count = int(tracks_get(media, ctypes.byref(tracks)))
            video_type = int(vlc.TrackType.video.value)
            for index in range(count):
                track = tracks[index].contents
                track_type = getattr(track.type, "value", track.type)
                if int(track_type) != video_type or not track.track.video:
                    continue
                video = track.track.video.contents
                width = int(video.width)
                height = int(video.height)
                sar_num = int(video.sar_num) or 1
                sar_den = int(video.sar_den) or 1
                orientation = int(getattr(video.orientation, "value", video.orientation))
                if width <= 0 or height <= 0 or sar_num <= 0 or sar_den <= 0:
                    continue
                swapped = orientation in (4, 5, 6, 7)
                if swapped:
                    display_num = height * sar_den
                    display_den = width * sar_num
                    display_width = height
                    display_height = width * sar_num / sar_den
                else:
                    display_num = width * sar_num
                    display_den = height * sar_den
                    display_width = width * sar_num / sar_den
                    display_height = height
                return {
                    "width": width,
                    "height": height,
                    "sar_num": sar_num,
                    "sar_den": sar_den,
                    "orientation": orientation,
                    "swapped": swapped,
                    "display_num": int(display_num),
                    "display_den": int(display_den),
                    "display_width": float(display_width),
                    "display_height": float(display_height),
                }
        except Exception:
            return None
        finally:
            if count > 0 and bool(tracks):
                try:
                    tracks_release = vlc.dll.libvlc_media_tracks_release
                    tracks_release.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    tracks_release.restype = None
                    tracks_release(ctypes.cast(tracks, ctypes.c_void_p), count)
                except Exception:
                    pass
        return None

    def _video_fit_config(self, player, frame, state=None):
        if player is None or frame is None:
            return None
        geometry = state.get("track_geometry") if state is not None else None
        if geometry is None:
            geometry = self._vlc_video_track_geometry(player)
            if geometry is not None and state is not None:
                state["track_geometry"] = geometry
        if geometry is None:
            try:
                source_width, source_height = player.video_get_size(0)
                source_width = int(source_width)
                source_height = int(source_height)
            except Exception:
                return None
            geometry = {
                "width": source_width,
                "height": source_height,
                "sar_num": 1,
                "sar_den": 1,
                "orientation": 0,
                "swapped": False,
                "display_num": source_width,
                "display_den": source_height,
                "display_width": float(source_width),
                "display_height": float(source_height),
            }
        native = self._native_video_frame_size(frame)
        if (
            geometry["width"] <= 0
            or geometry["height"] <= 0
            or native.width() <= 0
            or native.height() <= 0
        ):
            return None
        display_num = int(geometry["display_num"])
        display_den = int(geometry["display_den"])
        display_width = float(geometry["display_width"])
        display_height = float(geometry["display_height"])
        source_aspect = display_num / display_den
        frame_aspect = native.width() / native.height()
        # VLC already applies SAR and rotation while decoding.  Supplying the
        # computed display ratio again double-applies rotation for videos with
        # a 90/270-degree display matrix.  Keep VLC's native aspect here and use
        # parsed geometry only to decide whether an axis-specific crop is needed.
        aspect_ratio = None
        crop_geometry = None
        zoom = max(0.01, float(self.zoom_factor))
        if self.fit_mode == "manual":
            scale = zoom
        elif self.fit_mode == "actual":
            scale = 1.0
        else:
            # VLC's zero scale lets its vout fill the assigned HWND without
            # leaving the stale Direct3D picture rectangle produced by a
            # positive scale.  Crop only when the selected axis cannot fill the
            # frame; the crop ratio is always derived from the current HWND.
            scale = 0.0
            if self.fit_mode == "fit_height" and source_aspect > frame_aspect:
                crop_geometry = self._ratio_text(native.width(), native.height())
            elif self.fit_mode == "fit_width" and source_aspect < frame_aspect:
                crop_geometry = self._ratio_text(native.width(), native.height())
            if not math.isclose(zoom, 1.0, rel_tol=0.0, abs_tol=1e-6):
                if self.fit_mode == "fit_width":
                    scale = native.width() / display_width
                elif self.fit_mode == "fit_window":
                    scale = min(
                        native.width() / display_width,
                        native.height() / display_height,
                    )
                else:
                    scale = native.height() / display_height
                scale *= zoom
        signature = (
            self.fit_mode,
            round(zoom, 6),
            native.width(),
            native.height(),
            geometry["width"],
            geometry["height"],
            geometry["sar_num"],
            geometry["sar_den"],
            geometry["orientation"],
            aspect_ratio,
            crop_geometry,
        )
        if scale != 0.0:
            scale = max(0.01, min(100.0, float(scale)))
        return {
            "scale": float(scale),
            "aspect_ratio": aspect_ratio,
            "crop_geometry": crop_geometry,
            "signature": signature,
        }

    def apply_video_fit(self, state):
        if state is None or state.get("generation") != self.render_generation:
            return False
        player = state.get("player")
        frame = state.get("frame")
        config = self._video_fit_config(player, frame, state)
        if config is None:
            return False
        signature = config["signature"]
        if state.get("fit_signature") == signature:
            return True
        try:
            player.video_set_aspect_ratio(config["aspect_ratio"])
            player.video_set_crop_geometry(config["crop_geometry"])
            player.video_set_scale(config["scale"])
        except Exception:
            return False
        state["fit_scale"] = config["scale"]
        state["fit_aspect_ratio"] = config["aspect_ratio"]
        state["fit_crop_geometry"] = config["crop_geometry"]
        state["fit_signature"] = signature
        return True

    def apply_video_fit_to_active_slots(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        for state in list(self.video_slot_states.values()):
            self.apply_video_fit(state)

    def _reveal_video_slot(self, token, serial):
        token = int(token)
        serial = int(serial)
        state = self.video_slot_states.get(token)
        if (
            state is None
            or state.get("generation") != self.render_generation
            or int(state.get("playback_serial", -1)) != serial
            or state.get("revealed")
            or not self.is_active_viewer()
        ):
            return False
        frame = state.get("frame")
        path = Path(state.get("path"))
        player = state.get("player")
        if frame is None or player is None:
            return False
        try:
            if (
                frame.parent() is None
                or frame.property("videoGeneration") != state["generation"]
                or frame.property("videoPath") != str(path)
            ):
                return False
        except RuntimeError:
            return False
        if state.get("primary"):
            if player is not self.media_player:
                return False
        elif player not in self.extra_media_players:
            return False
        if not self._video_slot_is_ready(state):
            return False
        # schedule_image_update() can run before VLC finishes replacing the
        # old vout.  Its geometry call must not suppress the authoritative
        # application to the newly-ready output.
        state["fit_signature"] = None
        self.apply_video_fit(state)
        state["revealed"] = True
        self._hide_video_status(frame)
        if not any(not item.get("revealed") for item in self.video_slot_states.values()):
            self.video_ready_timer.stop()
        return True

    def poll_video_output_ready(self):
        if self._video_lifecycle_busy():
            return
        waiting = False
        now = time.monotonic()
        error_states = set()
        if vlc is not None:
            error_states = {
                getattr(vlc.State, "Error", None),
                getattr(vlc.State, "Stopped", None),
                getattr(vlc.State, "Ended", None),
            }
            error_states.discard(None)
        for token, state in list(self.video_slot_states.items()):
            if state.get("revealed") or state.get("generation") != self.render_generation:
                continue
            waiting = True
            if now - float(state.get("ready_started", now)) > VIDEO_READY_TIMEOUT_MS / 1000.0:
                self._fail_video_slot(token, "Video output timeout")
                continue
            frame = state.get("frame")
            player = state.get("player")
            if frame is None or player is None:
                continue
            # A media can be accepted by ``play()`` and still fail
            # asynchronously (missing codec, broken file, or a vout that
            # immediately stops).  Waiting for the full output timeout leaves
            # a black surface in front of the viewer and used to make the
            # following image look unreachable.  Retire it as soon as VLC
            # reports a terminal state; navigation remains independent of
            # this cleanup worker.
            try:
                player_state = player.get_state()
            except Exception:
                player_state = None
            if player_state in error_states:
                self._fail_video_slot(token, "Could not play video")
                continue
            try:
                label = frame.findChild(QLabel, "videoStatusLabel")
                if label is not None:
                    label.setGeometry(frame.rect())
                    label.raise_()
            except RuntimeError:
                continue
            if self._video_slot_is_ready(state):
                self._reveal_video_slot(token, int(state.get("playback_serial", 0)))
        if not waiting:
            self.video_ready_timer.stop()
            if self.video_retired_players:
                self.video_cleanup_idle_timer.start()

    def _fail_video_slot(self, token, reason="Video playback failed"):
        """Retire a slot whose vout never became usable, without freezing UI."""
        state = self.video_slot_states.pop(int(token), None)
        if state is None:
            return
        self.video_end_callbacks.pop(int(token), None)
        self.video_ready_callbacks.pop(int(token), None)
        player = state.get("player")
        frame = state.get("frame")
        if frame is not None:
            self._show_video_status(frame, reason + "\n" + Path(state.get("path", "")).name)
            self._hide_video_frame(frame)
        if player is not None:
            cancel_event = self.video_start_players.get(id(player))
            if cancel_event is not None:
                cancel_event.set()
            if state.get("primary"):
                if self.media_player is player:
                    self.media_player = None
                self.video_path = None
            else:
                self.extra_media_players = [item for item in self.extra_media_players if item is not player]
            self._quiesce_video_player(player)
            self._defer_video_cleanup([player])
        # A slot can fail after a frame-pool shortage queued a render retry.
        # Do not leave that retry dependent on an unrelated later input event.
        if self.pending_navigation_index is not None:
            QTimer.singleShot(0, self._resume_pending_navigation)

    def _attach_video_end_event(self, player, path, frame, primary):
        self.video_playback_token += 1
        token = self.video_playback_token
        # python-vlc invokes EndReached on a native callback thread.  Calling a
        # typed PySide signal there is not reliable on Windows and can raise or
        # race a player replacement.  The Qt-owned video timer polls all active
        # slot states instead, keeping every lifecycle decision on the GUI
        # thread.
        callback = None
        self.video_end_callbacks[token] = None
        self.video_slot_states[token] = {
            "player": player,
            "path": Path(path),
            "frame": frame,
            "primary": bool(primary),
            "generation": self.render_generation,
            "ended": False,
            "restarting": False,
            "playback_serial": 0,
            "revealed": False,
            "ready_callbacks": [],
            "media_committed": False,
            "expected_media_identity": "",
            "ready_samples": 0,
            "last_ready_time": -1,
            "fit_scale": None,
            "fit_signature": None,
        }
        if primary:
            self._video_end_callback = callback
        self._begin_video_surface_wait(token)
        return token

    @staticmethod
    def _profile_video_step(scope, label, profile):
        if profile is None:
            return
        now = time.perf_counter()
        print(
            f"PROFILE_STEP MainThread {scope}.{label} "
            f"delta={(now - profile[1]) * 1000:.3f}ms total={(now - profile[0]) * 1000:.3f}ms",
            flush=True,
        )
        profile[1] = now

    def _restart_video_slot(self, token, force=False):
        now = time.perf_counter()
        profile = [now, now] if os.environ.get("PHOTO_VIEWER_VERIFY_PROFILE") == "1" else None
        token = int(token)
        if self._video_lifecycle_busy():
            QTimer.singleShot(50, lambda current=token, forced=force: self._restart_video_slot(current, forced))
            return True
        state = self.video_slot_states.get(token)
        if (
            (not self.video_loop_enabled and not force)
            or state is None
            or state.get("generation") != self.render_generation
            or state.get("restarting")
            or not self.is_active_viewer()
        ):
            return False
        player = state.get("player")
        frame = state.get("frame")
        path = Path(state.get("path"))
        primary = bool(state.get("primary"))
        if player is None or frame is None or not path.exists():
            return False
        if primary:
            if player is not self.media_player:
                return False
        elif player not in self.extra_media_players:
            return False
        try:
            if (
                frame.parent() is None
                or frame.property("videoGeneration") != state["generation"]
                or frame.property("videoPath") != str(path)
            ):
                return False
        except RuntimeError:
            return False
        state["restarting"] = True
        layout_index = self.grid.indexOf(frame)
        if layout_index < 0:
            return False
        row, column, row_span, column_span = self.grid.getItemPosition(layout_index)
        logical_slot = int(frame.property("videoSlot") or 0)
        pool_slot = int(frame.property("videoPoolSlot") or 0)

        self.video_retired_callback_refs[id(player)] = state
        self.video_slot_states.pop(token, None)
        self.video_end_callbacks.pop(token, None)
        self.video_ready_callbacks.pop(token, None)
        if primary:
            if self.media_player is player:
                self.media_player = None
        else:
            try:
                self.extra_media_players.remove(player)
            except ValueError:
                pass
        self.grid.removeWidget(frame)
        self._profile_video_step("restart", "remove_widget", profile)
        self._profile_video_step("restart", "hide_old_frame", profile)
        self._defer_video_cleanup([player])
        self._profile_video_step("restart", "defer_cleanup", profile)

        new_frame = self.video_frame_for_index(pool_slot)
        self._profile_video_step("restart", "acquire_frame", profile)
        if new_frame is None:
            self.pending_navigation_index = self.index
            self.pending_render_requested = True
            return True
        new_frame.setProperty("videoPoolSlot", pool_slot)
        self.grid.addWidget(new_frame, row, column, row_span, column_span)
        self._profile_video_step("restart", "add_widget", profile)
        self.play_video(path, frame=new_frame, primary=primary, slot=logical_slot)
        self._profile_video_step("restart", "play_video", profile)
        return True

    def set_video_loop_enabled(self, enabled):
        self.video_loop_enabled = bool(enabled)
        if hasattr(self, "video_loop_btn") and self.video_loop_btn.isChecked() != self.video_loop_enabled:
            self.video_loop_btn.blockSignals(True)
            self.video_loop_btn.setChecked(self.video_loop_enabled)
            self.video_loop_btn.blockSignals(False)
        self.settings["video_loop_enabled"] = self.video_loop_enabled
        save_settings(self.settings)
        if self.video_loop_enabled:
            for token, state in list(self.video_slot_states.items()):
                if state.get("ended"):
                    QTimer.singleShot(0, lambda current=token: self._restart_video_slot(current))

    def load(self, items, index):
        self.items = [Path(p) for p in items if is_media(p)]
        self.index = max(0, min(index, len(self.items) - 1))
        self.vlc_prewarm_timer.stop()
        if vlc is not None and any(is_video(path) for path in self.items):
            if any(is_video(path) for path in self.current_group()):
                self._init_vlc_async()
            else:
                # Let the selected image paint first.  Cold VLC plugin scanning
                # otherwise contends with its first decode and feels like an
                # intermittent whole-viewer stall in mixed folders.
                self.vlc_prewarm_timer.start()
        if not self._app_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._app_filter_installed = True
        self.show_current(reset=not self.zoom_locked)

    def current_group(self):
        if not self.items:
            return []
        if self.viewer_mode == "double":
            size = 2
        elif self.viewer_mode == "triple":
            size = 3
        elif self.viewer_mode in ("webtoon", "webtoon_vertical"):
            return [p for p in self.items if is_image(p)]
        else:
            size = 1
        group = self.items[self.index:self.index + size]
        if self.viewer_mode == "double" and self.step_mode == "manga_page":
            return list(reversed(group))
        return group

    def clear_grid(self):
        self.retire_media_for_transition()
        self.stop_webtoon_auto_scroll()
        self.webtoon_scroll = None
        self.webtoon_container = None
        self.webtoon_loaded = set()
        self.webtoon_label_indices = {}
        self.webtoon_label_tops = []
        self.webtoon_idle_index = 0
        if hasattr(self, "webtoon_idle_timer"):
            self.webtoon_idle_timer.stop()
        if hasattr(self, "webtoon_build_timer"):
            self.webtoon_build_timer.stop()
        self.webtoon_pending_paths = []
        self.webtoon_container_layout = None
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                if widget in self.video_frames:
                    # Hiding a child window does not destroy its HWND.  Keep the
                    # drawable alive for libVLC cleanup, but never leave a stale
                    # native surface visible above the next image.
                    self._hide_video_frame(widget)
                else:
                    widget.hide()
                    widget.deleteLater()
        self.labels = []

    def is_animated_image_path(self, path):
        path = Path(path)
        if path.suffix.lower() not in (".gif", ".webp", ".apng"):
            return False
        path_text = str(path)
        signature = self.item_signatures.get(path_text)
        if signature is None and path.exists():
            try:
                stat = path.stat()
                signature = (int(stat.st_size), float(stat.st_mtime_ns))
            except OSError:
                signature = None
        cached = self.animated_image_classifications.get(path_text)
        if cached is not None and cached[0] == signature:
            return bool(cached[1])
        # Archive members do not have a directly readable local path.  Their
        # first ordinary decode reports the real frame count and starts the
        # animation only when more than one frame actually exists.
        if path_text in self.archive_sources and not path.exists():
            return False
        reader = QImageReader(path_text)
        try:
            animated = bool(
                reader.canRead()
                and reader.supportsAnimation()
                and reader.imageCount() != 1
            )
        finally:
            del reader
        self.animated_image_classifications[path_text] = (signature, animated)
        return animated

    def remember_animation_classification(self, path, animated):
        path = Path(path)
        path_text = str(path)
        signature = self.item_signatures.get(path_text)
        if signature is None and path.exists():
            try:
                stat = path.stat()
                signature = (int(stat.st_size), float(stat.st_mtime_ns))
            except OSError:
                signature = None
        self.animated_image_classifications[path_text] = (signature, bool(animated))

    def viewer_pixmap_cache_key(self, path):
        path = Path(path)
        signature = self.item_signatures.get(str(path), (0, 0.0))
        mtime = signature[1]
        area = self.viewer_area()
        return (
            str(path),
            mtime,
            self.viewer_mode,
            self.step_mode,
            self.fit_mode,
            round(float(self.zoom_factor), 4),
            int(self.rotation),
            area.width(),
            area.height(),
        )

    def first_animated_frame_pixmap(self, path):
        reader = None
        try:
            reader = Image.open(path)
            reader.seek(0)
            return QPixmap.fromImage(ImageQt(reader.convert("RGBA")))
        except Exception:
            return QPixmap()
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass

    def render_viewer_preview_pixmap(self, path, *, fast_video=False):
        path = Path(path)
        if is_video(path):
            return self.video_preview_pixmap(path, allow_shell=not fast_video)
        if self.is_animated_image_path(path):
            pix = self.first_animated_frame_pixmap(path)
            if pix.isNull():
                pix = QPixmap(str(path))
        else:
            pix = QPixmap(str(path))
        if pix.isNull():
            return pix
        if self.rotation:
            from PySide6.QtGui import QTransform
            pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
        target = self.target_size(None, pix)
        return pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def cached_viewer_preview_pixmap(self, path):
        key = self.viewer_pixmap_cache_key(path)
        cached = self.viewer_pixmap_cache.get(key)
        if cached is not None:
            return cached
        pix = self.render_viewer_preview_pixmap(path)
        if pix.isNull():
            return pix
        self.store_viewer_pixmap(key, pix)
        return pix

    @staticmethod
    def pixmap_memory_cost(pixmap):
        if pixmap is None or pixmap.isNull():
            return 0
        return max(0, int(pixmap.width()) * int(pixmap.height()) * 4)

    def store_viewer_pixmap(self, key, pixmap):
        old = self.viewer_pixmap_cache.pop(key, None)
        if old is not None:
            self.viewer_pixmap_cache_bytes = max(
                0,
                self.viewer_pixmap_cache_bytes - self.pixmap_memory_cost(old),
            )
        if key in self.viewer_pixmap_cache_order:
            self.viewer_pixmap_cache_order.remove(key)
        cost = self.pixmap_memory_cost(pixmap)
        limit = (
            min(self.performance_policy.webtoon_cache_limit_bytes, WEBTOON_CACHE_LIMIT_BYTES)
            if self.is_webtoon_viewer_mode()
            else min(self.performance_policy.viewer_cache_limit_bytes, VIEWER_CACHE_LIMIT_BYTES)
        )
        if cost <= 0 or cost > limit:
            return
        self.viewer_pixmap_cache[key] = pixmap
        self.viewer_pixmap_cache_order.append(key)
        self.viewer_pixmap_cache_bytes += cost
        while self.viewer_pixmap_cache_order and (
            len(self.viewer_pixmap_cache_order) > 64
            or self.viewer_pixmap_cache_bytes > limit
        ):
            old_key = self.viewer_pixmap_cache_order.pop(0)
            old_pixmap = self.viewer_pixmap_cache.pop(old_key, None)
            self.viewer_pixmap_cache_bytes = max(
                0,
                self.viewer_pixmap_cache_bytes - self.pixmap_memory_cost(old_pixmap),
            )

    def store_webtoon_pixmap(self, key, pixmap):
        old = self.webtoon_pixmap_cache.pop(key, None)
        if old is not None:
            self.webtoon_pixmap_cache_bytes = max(
                0,
                self.webtoon_pixmap_cache_bytes - self.pixmap_memory_cost(old),
            )
        if key in self.webtoon_pixmap_cache_order:
            self.webtoon_pixmap_cache_order.remove(key)
        cost = self.pixmap_memory_cost(pixmap)
        limit = min(self.performance_policy.webtoon_cache_limit_bytes, WEBTOON_CACHE_LIMIT_BYTES)
        if cost <= 0 or cost > limit:
            return
        self.webtoon_pixmap_cache[key] = pixmap
        self.webtoon_pixmap_cache_order.append(key)
        self.webtoon_pixmap_cache_bytes += cost
        while self.webtoon_pixmap_cache_order and (
            len(self.webtoon_pixmap_cache_order) > 48
            or self.webtoon_pixmap_cache_bytes > limit
        ):
            old_key = self.webtoon_pixmap_cache_order.pop(0)
            old_pixmap = self.webtoon_pixmap_cache.pop(old_key, None)
            self.webtoon_pixmap_cache_bytes = max(
                0,
                self.webtoon_pixmap_cache_bytes - self.pixmap_memory_cost(old_pixmap),
            )

    def build_prepared_viewer_items(self, group, active_video_slots):
        prepared = []
        for col, path in enumerate(group):
            if col in active_video_slots:
                pix = QPixmap()
            elif is_video(path):
                pix = QPixmap()
            elif is_image(path):
                pix = self.viewer_pixmap_cache.get(self.viewer_pixmap_cache_key(path), QPixmap())
            else:
                pix = QPixmap()
            prepared.append({
                "col": col,
                "path": path,
                "pix": pix,
                "active_video": col in active_video_slots,
                "video": is_video(path),
                "animated": is_image(path) and self.is_animated_image_path(path),
            })
        return prepared

    def cancel_pending_decodes(self):
        for task in list(self.decode_task_refs):
            if hasattr(task, "cancel"):
                task.cancel()
        self.decode_pool.clear()
        self.preload_decode_pool.clear()
        self.viewer_preload_queue = []
        self.viewer_preload_queued = set()
        if hasattr(self, "viewer_preload_timer"):
            self.viewer_preload_timer.stop()
        self.decode_inflight.clear()

    def transition_pixmaps(self):
        pixmaps = []
        for label, _ in self.labels:
            pixmap = getattr(label, "_viewer_pixmap", QPixmap())
            if pixmap is not None and not pixmap.isNull():
                pixmaps.append(QPixmap(pixmap))
        if not pixmaps and not self.opening_placeholder.isNull():
            pixmaps.append(QPixmap(self.opening_placeholder))
        return pixmaps

    def queue_viewer_decode(self, label, path, generation, priority=20, preload=False, render_token=None):
        path = Path(path)
        if render_token is None:
            render_token = self.image_update_token
        key = self.viewer_pixmap_cache_key(path)
        cached = self.viewer_pixmap_cache.get(key)
        if cached is not None and not cached.isNull():
            if label is not None:
                label.setText("")
                label.setPixmap(cached)
            return
        inflight_key = (generation, str(path), key)
        if inflight_key in self.decode_inflight:
            return
        area = self.viewer_area()
        dimension_limit = max(512, int(self.performance_policy.decode_dimension_limit))
        decode_zoom = max(0.05, min(10.0, float(self.zoom_factor))) if self.fit_mode == "manual" else max(1.0, self.zoom_factor)
        width_floor = 64 if self.fit_mode == "manual" else 320
        height_floor = 64 if self.fit_mode == "manual" else 240
        width = max(width_floor, min(dimension_limit, int(area.width() * decode_zoom)))
        height = max(height_floor, min(dimension_limit, int(area.height() * decode_zoom)))
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            width = max(WEBTOON_MIN_WIDTH, min(WEBTOON_MAX_WIDTH, int(self.webtoon_target_width or width)))
            height = 4096
        task = ImageDecodeTask(
            generation,
            path,
            (width, height),
            thread_priority=QThread.IdlePriority if preload else QThread.LowPriority,
            archive_source=self.archive_sources.get(str(path)),
            render_token=render_token,
            cache_key=key,
        )
        self.decode_inflight.add(inflight_key)
        self.decode_task_refs.add(task)
        task.signals.finished.connect(
            lambda result_generation, result_path, payload, metadata, ref=task, target_label=label, cache_key=key, token=inflight_key: self.viewer_decode_ready(
                result_generation, result_path, payload, metadata, ref, target_label, cache_key, token
            )
        )
        pool = self.preload_decode_pool if preload else self.decode_pool
        pool.start(task, int(priority))

    def viewer_decode_ready(self, generation, path, payload, metadata, task, label, cache_key, inflight_key):
        self.decode_task_refs.discard(task)
        self.decode_inflight.discard(inflight_key)
        if generation != self.render_generation:
            return
        metadata = metadata or {}
        if "animated" in metadata:
            self.remember_animation_classification(path, metadata.get("animated"))
        result_render_token = int(metadata.get("render_token", 0) or 0)
        if result_render_token and result_render_token != self.image_update_token:
            return
        result_cache_key = metadata.get("cache_key")
        if result_cache_key is not None and result_cache_key != self.viewer_pixmap_cache_key(Path(path)):
            return
        image_size = tuple(metadata.get("image_size") or ())
        if len(image_size) == 2:
            self.archive_image_sizes[str(path)] = image_size
        pixmap = QPixmap()
        if isinstance(payload, QImage):
            pixmap = QPixmap.fromImage(payload)
        elif isinstance(payload, (bytes, bytearray)):
            pixmap.loadFromData(bytes(payload), "PNG")
        if pixmap.isNull():
            if label is not None and label.parent() is not None:
                label.setText(Path(path).name)
            return
        if self.rotation:
            from PySide6.QtGui import QTransform
            pixmap = pixmap.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
        target = self.target_size(label, pixmap)
        scaled = pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.store_viewer_pixmap(cache_key, scaled)
        if label is not None and label.parent() is not None:
            if self.viewer_mode in ("webtoon", "webtoon_vertical"):
                label_index = self.webtoon_label_indices.get(id(label))
                visible_indices = set(
                    self.visible_webtoon_indices(
                        margin=max(2, int(self.performance_policy.webtoon_lookahead) + 1)
                    )
                )
                # A decode can finish after the user has scrolled away.  Keep
                # the bounded cache entry, but do not attach a large QPixmap
                # to an off-screen label (QLabel ownership otherwise defeats
                # the cache cap).
                if label_index is not None and label_index not in visible_indices:
                    label.setPixmap(QPixmap())
                    label.setText(Path(path).name)
                    self.webtoon_loaded.discard(label_index)
                    return
                label.setFixedSize(scaled.size())
            else:
                label.setMinimumHeight(0)
            label.setProperty("loadingPlaceholder", False)
            label.setText("")
            label.setPixmap(scaled)
            self.opening_placeholder = QPixmap()
            if metadata.get("animated"):
                self.try_start_animated_image(label, Path(path))
            if self.viewer_mode in ("webtoon", "webtoon_vertical"):
                for idx, (candidate, _) in enumerate(self.labels):
                    if candidate is label:
                        self.webtoon_loaded.add(idx)
                        break
                QTimer.singleShot(0, self.update_webtoon_container_extent)

    def queue_viewer_preloads(self):
        self.viewer_preload_queue = []
        self.viewer_preload_queued = set()
        self.viewer_preload_timer.stop()
        lookahead = max(0, int(self.performance_policy.viewer_lookahead))
        if lookahead <= 0 or not self.items or self.viewer_mode in ("webtoon", "webtoon_vertical"):
            return

        group_size = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        step = group_size if self.step_mode in ("page", "manga_page") else 1
        current_paths = {str(path) for path in self.current_group()}
        queued = []
        for distance in range(1, lookahead + 1):
            start = self.index + step * distance
            if start >= len(self.items):
                break
            for path in self.items[start:start + group_size]:
                path_text = str(path)
                if (
                    path_text in current_paths
                    or path_text in self.viewer_preload_queued
                    or not is_image(path)
                    or self.is_animated_image_path(path)
                ):
                    continue
                key = self.viewer_pixmap_cache_key(path)
                if key in self.viewer_pixmap_cache:
                    continue
                self.viewer_preload_queued.add(path_text)
                queued.append(path)
        self.viewer_preload_queue = queued
        if self.viewer_preload_queue:
            # Preloading starts only after the current image has had a chance
            # to paint.  One idle worker and the bounded viewer cache prevent
            # a large folder from turning this into a bulk decode operation.
            self.viewer_preload_timer.start(self.performance_policy.thumbnail_gap_ms)

    def process_next_viewer_preload(self):
        if not self.viewer_preload_queue:
            self.viewer_preload_timer.stop()
            return
        path = self.viewer_preload_queue.pop(0)
        self.viewer_preload_queued.discard(str(path))
        self.queue_viewer_decode(None, path, self.render_generation, priority=-10, preload=True)
        if self.viewer_preload_queue:
            self.viewer_preload_timer.start(self.performance_policy.thumbnail_gap_ms)

    def reuse_static_image_grid(self, prepared_items, generation):
        """Retarget existing image labels without exposing an empty frame."""
        if not prepared_items or len(self.labels) != len(prepared_items):
            return False
        if any(item["video"] or item["animated"] for item in prepared_items):
            return False
        if any(
            not isinstance(label, PannableImageLabel)
            or not is_image(old_path)
            or self.is_animated_image_path(old_path)
            for label, old_path in self.labels
        ):
            return False

        rebound = []
        for (label, _old_path), item in zip(self.labels, prepared_items):
            path = item["path"]
            label._pan_offset = QPoint(0, 0)
            label._selection_rect = QRect()
            display_pixmap = item["pix"]
            if not display_pixmap.isNull():
                label.setProperty("loadingPlaceholder", False)
                label.setText("")
                label.setPixmap(display_pixmap)
            else:
                # Keep the preceding frame visible until this decode is ready.
                # Replacing the QLabel here caused Windows to briefly expose
                # the backing surface between every pair of images.
                label.setProperty("loadingPlaceholder", True)
                if getattr(label, "_viewer_pixmap", QPixmap()).isNull():
                    label.setText("Loading…")
                self.queue_viewer_decode(label, path, generation, priority=20)
            rebound.append((label, path))
        self.labels = rebound
        return True

    def show_current(self, reset=False):
        # A VLC start may still be inside a native call (notably on the first
        # file after a cold install).  Rendering the next item must not wait
        # for that call: ``clear_grid`` marks the old player cancelled and the
        # worker retires it on its own thread.  The old implementation treated
        # every in-flight start as a global navigation lock, so a decoder that
        # stayed black also prevented the following image from ever appearing.
        transition_pixmaps = self.transition_pixmaps()
        self.cancel_pending_decodes()
        self.render_generation += 1
        self.image_update_token += 1
        generation = self.render_generation
        self.current_has_animation = False
        if hasattr(self, "animated_rate_btn"):
            self.animated_rate_btn.hide()
        if reset:
            self.fit_mode = self.settings.get("default_fit", "fit_height")
            self.fit_combo.setCurrentText(self.fit_mode)
            self.zoom_factor = 1.0
            self.update_manual_zoom_controls()
        group = self.current_group()
        active_video_slots = self.active_video_slots_for_group(group)
        prepared_items = None
        if group and self.viewer_mode not in ("webtoon", "webtoon_vertical"):
            prepared_items = self.build_prepared_viewer_items(group, active_video_slots)

        self.active_display_path = self.focus_path_for_group(group)
        if (
            group
            and not active_video_slots
            and self.reuse_static_image_grid(prepared_items, generation)
        ):
            self.current_is_video = False
            self.queue_viewer_preloads()
            title_name = self.active_display_path.name if self.active_display_path else self.items[self.index].name
            self.setWindowTitle(f"{APP_NAME} - {self.index + 1}/{len(self.items)} - {title_name}")
            self.update_filename_labels()
            self.position_overlays()
            return

        self.central.setUpdatesEnabled(False)
        self.clear_grid()
        if not group:
            label = QLabel("No media")
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_StyledBackground, True)
            label.setStyleSheet("background: #050505; color: #f0f0f0;")
            self.grid.addWidget(label, 0, 0)
            self.central.setUpdatesEnabled(True)
            self.central.update()
            return

        self.current_is_video = bool(active_video_slots)
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            reference = self.items[self.index] if self.items and is_image(self.items[self.index]) else (group[0] if group else None)
            self.reset_webtoon_target_width(reference)
            container = QWidget()
            container.setAttribute(Qt.WA_StyledBackground, True)
            container.setAutoFillBackground(True)
            container_palette = container.palette()
            container_palette.setColor(QPalette.Window, QColor("#050505"))
            container.setPalette(container_palette)
            container.setStyleSheet("background: #050505;")
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.webtoon_container_layout = layout
            self.webtoon_container = container
            self.webtoon_pending_paths = [path for path in group if is_image(path)]
            self.webtoon_build_generation = generation
            self.append_webtoon_labels(count=8)
            scroll = QScrollArea()
            scroll.setAttribute(Qt.WA_StyledBackground, True)
            scroll.setWidgetResizable(True)
            scroll.setWidget(container)
            scroll.setAutoFillBackground(True)
            scroll.setStyleSheet("background: #050505;")
            scroll.viewport().setAutoFillBackground(True)
            scroll.viewport().setAttribute(Qt.WA_StyledBackground, True)
            scroll.viewport().setStyleSheet("background: #050505;")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.verticalScrollBar().valueChanged.connect(self.schedule_webtoon_visible_update)
            self.webtoon_scroll = scroll
            self.grid.addWidget(scroll, 0, 0)
            self.schedule_webtoon_visible_update(generation)
            self.webtoon_idle_timer.start()
            if self.webtoon_pending_paths:
                self.webtoon_build_timer.start()
        else:
            primary_video_assigned = False
            active_video_frame_index = 0
            for item in prepared_items or []:
                col = item["col"]
                path = item["path"]
                if item["active_video"]:
                    primary = not primary_video_assigned
                    frame = self.video_frame_for_index(active_video_frame_index)
                    active_video_frame_index += 1
                    if frame is None:
                        label = QLabel("Preparing video surface…")
                        label.setAlignment(Qt.AlignCenter)
                        label.setAttribute(Qt.WA_StyledBackground, True)
                        label.setStyleSheet("background: #050505; color: #f0f0f0;")
                        self.grid.addWidget(label, 0, col)
                        self.pending_navigation_index = self.index
                        self.pending_render_requested = True
                        continue
                    primary_video_assigned = True
                    self.grid.addWidget(frame, 0, col)
                    self.play_video(path, frame=frame, primary=primary, slot=col)
                elif item["video"]:
                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    label.setAttribute(Qt.WA_StyledBackground, True)
                    label.setAutoFillBackground(True)
                    label.setStyleSheet("background: #050505;")
                    label.setText("Loading…")
                    label.setToolTip(Path(path).name)
                    self.grid.addWidget(label, 0, col)
                    task = ImageDecodeTask(
                        generation,
                        path,
                        (512, 512),
                        video_shell=True,
                        render_token=self.image_update_token,
                        cache_key=self.viewer_pixmap_cache_key(Path(path)),
                    )
                    self.decode_task_refs.add(task)
                    task.signals.finished.connect(
                        lambda result_generation, result_path, payload, metadata, ref=task, target=label: self.viewer_decode_ready(
                            result_generation,
                            result_path,
                            payload,
                            metadata,
                            ref,
                            target,
                            self.viewer_pixmap_cache_key(Path(result_path)),
                            (result_generation, result_path, "video"),
                        )
                    )
                    self.decode_pool.start(task, 5)
                else:
                    label = PannableImageLabel()
                    label.regionZoomRequested.connect(
                        lambda rect, target_label=label: self.zoom_to_region(target_label, rect)
                    )
                    label.setAttribute(Qt.WA_StyledBackground, True)
                    label.setAutoFillBackground(True)
                    label.setStyleSheet("background: #050505;")
                    display_pixmap = item["pix"]
                    if display_pixmap.isNull() and transition_pixmaps:
                        display_pixmap = transition_pixmaps[col % len(transition_pixmaps)]
                        label.setProperty("loadingPlaceholder", True)
                    if not display_pixmap.isNull():
                        label.setPixmap(display_pixmap)
                    else:
                        label.setText("Loading…")
                    self.grid.addWidget(label, 0, col)
                    self.labels.append((label, path))
                    if item["animated"]:
                        if display_pixmap.isNull():
                            label.setText("Loading...")
                    elif item["pix"].isNull():
                        self.queue_viewer_decode(label, path, generation, priority=20)
            QTimer.singleShot(0, lambda g=generation: self.start_visible_animations(g))
            self.queue_viewer_preloads()
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            title_name = "webtoon"
        else:
            title_name = self.active_display_path.name if self.active_display_path else self.items[self.index].name
        self.setWindowTitle(f"{APP_NAME} - {self.index + 1}/{len(self.items)} - {title_name}")
        self.update_filename_labels()
        self.position_overlays()
        self.central.setUpdatesEnabled(True)
        self.central.update()

    def active_video_slots_for_group(self, group):
        if not group:
            return set()
        if len(group) == 1:
            return {0} if is_video(group[0]) else set()
        if self.step_mode == "page":
            return {idx for idx, path in enumerate(group) if is_video(path)}
        if self.viewer_mode == "triple":
            return {1} if len(group) > 1 and is_video(group[1]) else set()
        if self.viewer_mode == "double":
            return {0} if is_video(group[0]) else set()
        return set()

    def focus_path_for_group(self, group):
        if not group:
            return None
        if self.step_mode == "slide" and self.viewer_mode == "triple" and len(group) > 1:
            return group[1]
        return group[0]

    def current_file_name(self):
        if not self.items:
            return ""
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            return f"webtoon ({len([p for p in self.items if is_image(p)])} images)"
        path = getattr(self, "active_display_path", None)
        return (path or self.items[self.index]).name

    def update_filename_labels(self):
        name = self.current_file_name()
        for label in (
            self.top_filename_label,
            self.rotation_filename_label,
            self.video_filename_label,
        ):
            label.setText(name)
            label.setToolTip(name)

    def schedule_image_update(self, generation=None):
        if not self.is_active_viewer() or self.app_closing:
            return
        generation = self.render_generation if generation is None else generation
        self.image_update_pending_generation = generation
        self.image_update_timer.start()

    def _apply_scheduled_image_update(self):
        generation = self.image_update_pending_generation
        self.image_update_pending_generation = None
        if self.app_closing or generation != self.render_generation or not self.is_active_viewer():
            return
        self.image_update_token += 1
        self.apply_video_fit_to_active_slots(generation)
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.reset_webtoon_target_width()
            self.update_webtoon_visible_images(generation)
        else:
            self.update_image_labels(generation)
        # One delayed geometry pass is retained for VLC's vout, whose native
        # size can become available just after the Qt resize event.
        QTimer.singleShot(40, lambda g=generation, token=self.image_update_token: (
            self.apply_video_fit_to_active_slots(g)
            if not self.app_closing and g == self.render_generation and token == self.image_update_token
            else None
        ))

    def schedule_webtoon_visible_update(self, generation=None):
        generation = self.render_generation if generation is None else generation
        QTimer.singleShot(0, lambda g=generation: self.update_webtoon_visible_images(g))
        QTimer.singleShot(60, lambda g=generation: self.update_webtoon_visible_images(g))

    def image_pixel_size(self, path):
        archive_size = self.archive_image_sizes.get(str(path))
        if archive_size:
            return QSize(int(archive_size[0]), int(archive_size[1]))
        reader = QImageReader(str(path))
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            return size
        pix = QPixmap(str(path))
        return pix.size()

    def reference_webtoon_path(self):
        if not self.labels:
            return self.items[self.index] if self.items else None
        indices = self.visible_webtoon_indices(margin=0)
        if indices:
            return self.labels[indices[0]][1]
        for _, path in self.labels:
            if path == self.items[self.index]:
                return path
        return self.labels[0][1]

    def compute_webtoon_target_width(self, reference_path=None):
        reference_path = reference_path or self.reference_webtoon_path()
        area_width = max(1, self.viewer_area().width())
        if reference_path and self.fit_mode in ("actual", "manual"):
            size = self.image_pixel_size(reference_path)
            if size.isValid() and size.width() > 0:
                width = size.width()
                if self.fit_mode == "manual":
                    width = int(width * self.zoom_factor)
            else:
                width = area_width
        else:
            width = area_width
        return max(WEBTOON_MIN_WIDTH, min(WEBTOON_MAX_WIDTH, int(width)))

    def reset_webtoon_target_width(self, reference_path=None):
        self.webtoon_target_width = self.compute_webtoon_target_width(reference_path)
        self.webtoon_loaded = set()

    def scaled_static_pixmap(self, path, target_width):
        path = Path(path)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        key = (str(path), int(target_width), int(self.rotation), mtime)
        cached = self.webtoon_pixmap_cache.get(key)
        if cached is not None:
            return cached
        reader = QImageReader(str(path))
        source_size = reader.size()
        if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
            target_height = max(1, int(source_size.height() * target_width / source_size.width()))
            reader.setScaledSize(QSize(max(1, int(target_width)), target_height))
            image = reader.read()
            pix = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        else:
            pix = QPixmap(str(path))
            if not pix.isNull() and pix.width() > 0:
                target_height = max(1, int(pix.height() * target_width / pix.width()))
                pix = pix.scaled(max(1, int(target_width)), target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if pix.isNull():
            return pix
        if self.rotation:
            from PySide6.QtGui import QTransform
            pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
        self.store_webtoon_pixmap(key, pix)
        return pix

    def create_video_frame(self):
        frame = QFrame(self.central)
        frame.setObjectName("videoFrame")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setAttribute(Qt.WA_NativeWindow, True)
        frame.setStyleSheet("background: #000;")
        frame.setAutoFillBackground(True)
        frame.setFocusPolicy(Qt.StrongFocus)
        frame.setMouseTracking(True)
        frame.installEventFilter(self)
        return frame

    def video_frame_for_index(self, index):
        index = max(0, int(index))
        pool = self.video_frame_pools.setdefault(index, [])
        active_frame_ids = {
            id(state.get("frame"))
            for state in self.video_slot_states.values()
            if state.get("frame") is not None
        }
        for frame in pool:
            if id(frame) not in self.video_frame_busy and id(frame) not in active_frame_ids:
                return frame
        if len(pool) >= VIDEO_MAX_FRAMES_PER_SLOT:
            return None
        frame = self.create_video_frame()
        frame.setProperty("videoPoolSlot", index)
        pool.append(frame)
        self.video_frames.append(frame)
        return frame

    @staticmethod
    def _hide_video_frame(frame):
        if frame is None:
            return
        try:
            frame.lower()
            frame.hide()
        except RuntimeError:
            pass

    @staticmethod
    def _native_video_handle(frame):
        if frame is None:
            return 0
        try:
            frame.setAttribute(Qt.WA_NativeWindow, True)
            hwnd = int(frame.winId())
        except (RuntimeError, TypeError, ValueError):
            return 0
        if hwnd <= 0:
            return 0
        if (
            sys.platform == "win32"
            and os.environ.get("QT_QPA_PLATFORM", "").lower() not in ("offscreen", "minimal")
        ):
            try:
                if not ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
                    return 0
            except Exception:
                return 0
        return hwnd

    def prime_video_frame_geometry(self, frame):
        """Size a fresh native video surface before libVLC binds its HWND.

        Retired VLC surfaces must stay alive until their players are released,
        so navigation can legitimately allocate a brand-new QFrame.  A new
        QFrame starts at Qt's 640x480 default and the grid layout is applied on
        a later event-loop pass.  Binding libVLC before that pass makes the
        first frames render at 640x480 and then visibly jump to the viewer size.
        Prime only the transient geometry here; the grid remains responsible
        for the final position and size.
        """
        target = self.viewer_area()
        if target.width() > 0 and target.height() > 0 and frame.size() != target:
            frame.resize(target)
        frame.updateGeometry()

    def _show_video_status(self, frame, text):
        try:
            label = frame.findChild(QLabel, "videoStatusLabel")
            if label is None:
                label = QLabel(frame)
                label.setObjectName("videoStatusLabel")
                label.setAlignment(Qt.AlignCenter)
                label.setAttribute(Qt.WA_StyledBackground, True)
                label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                label.setAttribute(Qt.WA_NativeWindow, True)
                label.setStyleSheet("background: #050505; color: #f0f0f0; font-size: 10pt;")
            label.setText(text)
            label.setGeometry(frame.rect())
            label.show()
            label.raise_()
        except RuntimeError:
            pass

    def _hide_video_status(self, frame):
        try:
            label = frame.findChild(QLabel, "videoStatusLabel")
            if label is not None:
                label.hide()
        except RuntimeError:
            pass

    def play_video(self, path, frame=None, primary=True, slot=0):
        path = Path(path)
        frame = frame or self.video_frame
        self.prime_video_frame_geometry(frame)
        frame.setProperty("videoGeneration", self.render_generation)
        frame.setProperty("videoPath", str(path))
        frame.setProperty("videoSlot", int(slot))
        if self.vlc_instance is None:
            if vlc is None:
                self._show_video_status(frame, "VLC runtime not available\n" + path.name)
                return
            self._show_video_status(frame, "Initializing video player...\n" + path.name)
            request = {
                "generation": self.render_generation,
                "path": path,
                "frame": frame,
                "primary": bool(primary),
                "slot": int(slot),
            }
            self.pending_video_requests = [
                item for item in self.pending_video_requests
                if not (
                    item["generation"] == request["generation"]
                    and item["slot"] == request["slot"]
                )
            ]
            self.pending_video_requests.append(request)
            self._init_vlc_async()
            return
        self._start_video_playback(path, frame, primary=primary)

    def _start_video_playback(self, path, frame, primary=True):
        now = time.perf_counter()
        profile = [now, now] if os.environ.get("PHOTO_VIEWER_VERIFY_PROFILE") == "1" else None
        if primary and self.media_player is None and self.vlc_instance is not None:
            try:
                self.media_player = self._acquire_video_player()
            except Exception:
                self.media_player = None
        player = self.media_player if primary else self._acquire_video_player()
        self._profile_video_step("start", "acquire_player", profile)
        if not player:
            self._show_video_status(frame, "Preparing video player…\n" + Path(path).name)
            request = {
                "generation": self.render_generation,
                "path": Path(path),
                "frame": frame,
                "primary": bool(primary),
                "slot": int(frame.property("videoSlot") or 0),
            }
            self.pending_video_requests = [
                item for item in self.pending_video_requests
                if not (
                    item["generation"] == request["generation"]
                    and item["slot"] == request["slot"]
                )
            ]
            self.pending_video_requests.append(request)
            self._ensure_video_standby_players()
            return
        token = None
        try:
            if primary:
                self.video_path = Path(path)
                self.video_finished = False
                self.video_stopped_by_user = False
            else:
                self.extra_media_players.append(player)
            frame.setVisible(True)
            frame.show()
            self._profile_video_step("start", "set_visible", profile)
            frame.raise_()
            self._profile_video_step("start", "raise_frame", profile)
            frame.repaint()
            self._show_video_status(frame, "Loading…\n" + Path(path).name)
            self._profile_video_step("start", "show_status", profile)
            previous_frame = self.video_player_frames.get(id(player))
            previous_frame_id = id(previous_frame) if previous_frame is not None else 0
            self.video_player_frames[id(player)] = frame
            self.video_frame_busy.add(id(frame))
            player_instance = self.video_player_instances.get(id(player))
            if player_instance is None:
                raise RuntimeError("Video player instance is unavailable")
            hwnd = self._native_video_handle(frame)
            if hwnd <= 0:
                raise RuntimeError("Native video surface is unavailable")
            self._configure_media_player(player)
            token = self._attach_video_end_event(player, path, frame, primary)
            self._profile_video_step("start", "attach_state", profile)
            cancel_event = threading.Event()
            self.video_start_players[id(player)] = cancel_event
            self.video_start_started[id(player)] = time.monotonic()
            player_lock = self.video_player_locks.setdefault(id(player), threading.RLock())
            self.video_start_inflight += 1
            self.video_start_queue.put({
                "player": player,
                "instance": player_instance,
                "path": str(path),
                "hwnd": hwnd,
                "rate": float(self.playback_rate),
                "volume": int(self.volume_slider.value()),
                "primary": bool(primary),
                "token": int(token),
                "generation": int(self.render_generation),
                "previous_frame_id": int(previous_frame_id),
                "cancel_event": cancel_event,
                "lock": player_lock,
            })
            self._profile_video_step("start", "queue_play", profile)
        except Exception:
            if primary:
                self.video_path = None
                if self.media_player is player:
                    self.media_player = None
            else:
                try:
                    self.extra_media_players.remove(player)
                except ValueError:
                    pass
            self.video_start_players.pop(id(player), None)
            self.video_start_started.pop(id(player), None)
            if token is not None:
                self.video_slot_states.pop(token, None)
                self.video_end_callbacks.pop(token, None)
                self.video_ready_callbacks.pop(token, None)
            self._quiesce_video_player(player)
            self._queue_video_cleanup([player])
            self._show_video_status(frame, "Could not play video\n" + Path(path).name)

    @staticmethod
    def _video_start_worker(work_queue, signals):
        if sys.platform == "win32":
            try:
                ctypes.windll.kernel32.SetThreadPriority(
                    ctypes.windll.kernel32.GetCurrentThread(), -1
                )
            except Exception:
                pass
        while True:
            item = work_queue.get()
            if item is None:
                work_queue.task_done()
                return
            error = ""
            media_identity = ""
            released = False
            player_lock = item.get("lock")
            lock_acquired = False
            try:
                player = item["player"]
                if player_lock is not None:
                    player_lock.acquire()
                    lock_acquired = True
                cancel_event = item["cancel_event"]
                if cancel_event.is_set():
                    raise RuntimeError("Video start cancelled")
                media = item["instance"].media_new(item["path"])
                player.set_media(media)
                player.set_hwnd(int(item["hwnd"]))
                try:
                    player.video_set_mouse_input(False)
                    player.video_set_key_input(False)
                except Exception:
                    pass
                for method_name, value in (
                    ("video_set_scale", 0.0),
                    ("video_set_aspect_ratio", None),
                    ("video_set_crop_geometry", None),
                ):
                    try:
                        getattr(player, method_name)(value)
                    except Exception:
                        pass
                try:
                    media_identity = str(media.get_mrl() or "")
                except Exception:
                    media_identity = str(media)
                if cancel_event.is_set():
                    raise RuntimeError("Video start cancelled")
                result = player.play()
                if result is not None and int(result) < 0:
                    raise RuntimeError("libVLC rejected playback")
                try:
                    player.set_rate(float(item["rate"]))
                except Exception:
                    pass
                try:
                    player.audio_set_mute(not bool(item.get("primary", True)))
                except Exception:
                    pass
                try:
                    player.audio_set_volume(int(item["volume"]))
                except Exception:
                    pass
                if cancel_event.is_set():
                    try:
                        player.audio_set_mute(True)
                    except Exception:
                        pass
                    try:
                        player.audio_set_volume(0)
                    except Exception:
                        pass
                    try:
                        player.set_pause(1)
                    except Exception:
                        pass
                    try:
                        player.stop()
                    except Exception:
                        pass
                    try:
                        player.release()
                    except Exception:
                        pass
                    released = True
                    raise RuntimeError("Video start cancelled")
            except Exception as exc:
                error = str(exc)
                if item.get("cancel_event") is not None and item["cancel_event"].is_set() and not released:
                    try:
                        item["player"].audio_set_mute(True)
                    except Exception:
                        pass
                    try:
                        item["player"].audio_set_volume(0)
                    except Exception:
                        pass
                    try:
                        item["player"].stop()
                    except Exception:
                        pass
                    try:
                        item["player"].release()
                    except Exception:
                        pass
                    released = True
            payload = dict(item)
            payload["media_identity"] = media_identity
            payload["error"] = error
            payload["released"] = released
            try:
                if getattr(signals, "accept_results", True):
                    signals.finished.emit(payload)
            except RuntimeError:
                pass
            finally:
                if lock_acquired:
                    try:
                        player_lock.release()
                    except Exception:
                        pass
                work_queue.task_done()

    def _video_start_finished(self, payload):
        self.video_start_inflight = max(0, int(self.video_start_inflight) - 1)
        player = payload.get("player")
        if player is not None:
            self.video_start_players.pop(id(player), None)
            self.video_start_started.pop(id(player), None)
        previous_frame_id = int(payload.get("previous_frame_id") or 0)
        if previous_frame_id:
            self.video_frame_busy.discard(previous_frame_id)
        token = int(payload.get("token", 0))
        state = self.video_slot_states.get(token)
        active = (
            state is not None
            and state.get("generation") == payload.get("generation")
            and state.get("player") is player
        )
        if active:
            error = str(payload.get("error") or "")
            if error:
                self._show_video_status(state.get("frame"), "Could not play video\n" + Path(state["path"]).name)
                self.video_slot_states.pop(token, None)
                self.video_end_callbacks.pop(token, None)
                self.video_ready_callbacks.pop(token, None)
                if state.get("primary"):
                    if self.media_player is player:
                        self.media_player = None
                    self.video_path = None
                else:
                    try:
                        self.extra_media_players.remove(player)
                    except ValueError:
                        pass
                if not payload.get("released"):
                    self._quiesce_video_player(player)
                    self._queue_video_cleanup([player])
            else:
                state["expected_media_identity"] = str(payload.get("media_identity") or "")
                state["media_committed"] = True
                if state.get("primary"):
                    self.video_timer.start(250)
                    try:
                        state["frame"].setFocus()
                    except RuntimeError:
                        pass
        else:
            frame = self.video_player_frames.get(id(player)) if player is not None else None
            self._hide_video_frame(frame)
            if payload.get("released"):
                self.video_player_frames.pop(id(player), None)
                self.video_player_instances.pop(id(player), None)
                self.video_retired_callback_refs.pop(id(player), None)
                if frame is not None:
                    self.video_frame_busy.discard(id(frame))
            elif player is not None:
                self._quiesce_video_player(player)
                self._defer_video_cleanup([player])
        if self.video_start_inflight == 0:
            self._resume_pending_navigation()

    def _acquire_video_player(self):
        if self.video_standby_players:
            player = self.video_standby_players.pop(0)
        else:
            self._ensure_video_standby_players()
            return None
        self._configure_media_player(player)
        try:
            player.audio_set_mute(True)
            player.audio_set_volume(0)
        except Exception:
            pass
        return player

    def make_video_preview_label(self, path):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setAttribute(Qt.WA_StyledBackground, True)
        label.setAutoFillBackground(True)
        label.setStyleSheet("background: #050505;")
        label.setPixmap(self.video_preview_pixmap(Path(path)))
        label.setToolTip(Path(path).name)
        return label

    def update_video_preview_label(self, label, path, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        if label is None or label.parent() is None:
            return
        label.setPixmap(self.video_preview_pixmap(Path(path), allow_shell=True))

    def video_preview_pixmap(self, path, allow_shell=True):
        size = self.viewer_area()
        width = max(220, size.width())
        height = max(220, size.height())
        pix = QPixmap(width, height)
        pix.fill(QColor("#050505"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(0, 0, width, height, QColor("#050505"))
        painter.setPen(QColor("#2a2f38"))
        painter.drawRect(0, 0, width - 1, height - 1)

        thumb = self.video_thumbnail_cache.get(str(path))
        if thumb is None and allow_shell:
            thumb = windows_shell_thumbnail(path, max(256, min(512, max(width, height))))
            self.video_thumbnail_cache[str(path)] = thumb if thumb is not None else False
        if thumb is False or thumb is None:
            thumb = None
        if thumb is not None and not thumb.isNull():
            scaled = thumb.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap((width - scaled.width()) // 2, (height - scaled.height()) // 2, scaled)
            painter.fillRect(0, 0, width, height, QColor(0, 0, 0, 55))

        play_font = QFont()
        play_font.setPointSize(max(28, min(width, height) // 10))
        play_font.setBold(True)
        painter.setFont(play_font)
        painter.setPen(QColor("#e8eef8"))
        painter.drawText(0, max(0, height // 2 - 88), width, 96, Qt.AlignCenter, "▶")

        name_font = QFont()
        name_font.setPointSize(11)
        painter.setFont(name_font)
        painter.setPen(QColor("#f2f6ff"))
        painter.drawText(24, max(0, height // 2 + 18), max(1, width - 48), 72, Qt.AlignCenter | Qt.TextWordWrap, path.name)
        painter.end()
        return pix

    @staticmethod
    def _video_cleanup_worker(work_queue, signals):
        """Stop retired players off the GUI thread while their HWNDs stay valid."""
        if sys.platform == "win32":
            try:
                ctypes.windll.kernel32.SetThreadPriority(
                    ctypes.windll.kernel32.GetCurrentThread(), -2
                )
            except Exception:
                pass
        while True:
            item = work_queue.get()
            if item is None:
                work_queue.task_done()
                return
            player, frame_id, player_instance, player_lock = item
            lock_acquired = False
            try:
                if player_lock is not None:
                    player_lock.acquire()
                    lock_acquired = True
                try:
                    player.audio_set_mute(True)
                except Exception:
                    pass
                try:
                    player.audio_set_volume(0)
                except Exception:
                    pass
                try:
                    player.set_pause(1)
                except Exception:
                    pass
                try:
                    player.stop()
                except Exception:
                    pass
                try:
                    player.release()
                except Exception:
                    pass
            finally:
                if lock_acquired:
                    try:
                        player_lock.release()
                    except Exception:
                        pass
                try:
                    if getattr(signals, "accept_results", True):
                        signals.finished.emit(int(id(player)), int(frame_id or 0))
                except RuntimeError:
                    pass
                work_queue.task_done()

    @staticmethod
    def _unique_video_players(players):
        unique = []
        seen = set()
        for player in players:
            if player is None or id(player) in seen:
                continue
            seen.add(id(player))
            unique.append(player)
        return unique

    def _quiesce_video_player(self, player):
        """Immediately mute and pause while preserving the attached HWND."""
        if player is None:
            return False
        lock = self.video_player_locks.setdefault(id(player), threading.RLock())
        acquired = lock.acquire(timeout=0.02)
        if not acquired:
            # The start/cleanup worker owns the player.  Its cancel flag is
            # checked before and after native calls, so blocking the GUI here
            # would only turn a quick navigation into a freeze.
            return False
        try:
            try:
                player.audio_set_mute(True)
            except Exception:
                pass
            try:
                player.audio_set_volume(0)
            except Exception:
                pass
            try:
                player.set_pause(1)
            except Exception:
                pass
        finally:
            lock.release()
        return True

    def _take_active_video_players(self):
        now = time.perf_counter()
        profile = [now, now] if os.environ.get("PHOTO_VIEWER_VERIFY_PROFILE") == "1" else None
        self.movie = None
        self.stop_animated_image()
        self._profile_video_step("take", "stop_animation", profile)
        self.pending_video_requests = []
        self.video_playback_token += 1
        self._video_end_callback = None
        for _token, state in list(getattr(self, "video_slot_states", {}).items()):
            player = state.get("player")
            if player is not None:
                self.video_retired_callback_refs[id(player)] = state
        self.video_slot_states = {}
        self.video_end_callbacks = {}
        self.video_ready_callbacks = {}
        self.video_stopped_by_user = True
        self.video_finished = False
        if hasattr(self, "video_timer"):
            self.video_timer.stop()
        if hasattr(self, "video_ready_timer"):
            self.video_ready_timer.stop()
        self._profile_video_step("take", "clear_state", profile)
        players = self._unique_video_players(
            [self.media_player, *getattr(self, "extra_media_players", [])]
        )
        ready_for_cleanup = []
        for player in players:
            cancel_event = self.video_start_players.get(id(player))
            if cancel_event is not None:
                cancel_event.set()
            self._quiesce_video_player(player)
            frame = self.video_player_frames.get(id(player))
            self._hide_video_frame(frame)
            if cancel_event is None:
                ready_for_cleanup.append(player)
        self._profile_video_step("take", "quiesce_players", profile)
        self.extra_media_players = []
        self.media_player = None
        self._profile_video_step("take", "hide_frames", profile)
        self.video_path = None
        if hasattr(self, "seek_slider"):
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)
            self.time_label.setText("00:00 / 00:00")
        self._profile_video_step("take", "reset_controls", profile)
        return ready_for_cleanup

    def _video_cleanup_finished(self, player_id, frame_id):
        frame = self.video_player_frames.pop(int(player_id), None)
        self.video_player_instances.pop(int(player_id), None)
        self.video_player_locks.pop(int(player_id), None)
        self.video_retired_callback_refs.pop(int(player_id), None)
        if frame_id:
            self.video_frame_busy.discard(int(frame_id))
        if frame is not None:
            self._hide_video_frame(frame)
        self.video_cleanup_inflight = max(0, int(self.video_cleanup_inflight) - 1)
        if self.video_cleanup_inflight == 0 and not self.video_retired_players:
            self._release_retired_vlc_instances()
            if self.pending_navigation_index is not None and self.video_standby_players:
                QTimer.singleShot(0, self._resume_pending_navigation)
            else:
                if self.pending_video_requests and self.video_standby_players:
                    QTimer.singleShot(0, self._dispatch_pending_video_requests)
                QTimer.singleShot(0, self._ensure_video_standby_players)

    def _queue_video_cleanup(self, players):
        players = self._unique_video_players(players)
        self.video_cleanup_inflight += len(players)
        if players and not self.video_cleanup_closed and not self.video_cleanup_thread.is_alive():
            # A native VLC exception must not permanently disable cleanup for
            # the rest of the session.  Recreate the single worker before
            # enqueueing the next retired player.
            self.video_cleanup_thread = threading.Thread(
                target=self._video_cleanup_worker,
                args=(self.video_cleanup_queue, self.video_cleanup_signals),
                name="PhotoViewer-VLC-Cleanup",
                daemon=True,
            )
            self.video_cleanup_thread.start()
        for player in players:
            frame = self.video_player_frames.get(id(player))
            player_instance = self.video_player_instances.get(id(player))
            frame_id = id(frame) if frame is not None else 0
            if frame_id:
                self.video_frame_busy.add(frame_id)
            if self.video_cleanup_closed:
                self._quiesce_video_player(player)
                try:
                    player.stop()
                except Exception:
                    pass
                try:
                    player.release()
                except Exception:
                    pass
                self._video_cleanup_finished(id(player), frame_id)
                continue
            player_lock = self.video_player_locks.setdefault(id(player), threading.RLock())
            self.video_cleanup_queue.put((player, frame_id, player_instance, player_lock))

    def _reserve_video_cleanup_frames(self, players):
        for player in self._unique_video_players(players):
            frame = self.video_player_frames.get(id(player))
            if frame is not None:
                self.video_frame_busy.add(id(frame))

    def _defer_video_cleanup(self, players):
        players = self._unique_video_players(players)
        if not players:
            return
        self._reserve_video_cleanup_frames(players)
        self.video_retired_players = self._unique_video_players(
            [*self.video_retired_players, *players]
        )
        # The native stop/release work is already off the GUI thread.  Queue it
        # immediately instead of waiting for the idle timer: under heavy Qt
        # event traffic a delayed timer could leave a retired player out of the
        # cleanup queue long enough for a later transition to reuse its frame.
        # Keeping the queue bounded (one worker, one item per retired player)
        # preserves the old coalescing/lifecycle guarantees without a visible
        # transition stall.
        self.video_cleanup_flush_pending = False
        self.video_cleanup_idle_timer.stop()
        self._flush_deferred_video_cleanup()

    def _flush_deferred_video_cleanup(self):
        self.video_cleanup_flush_pending = False
        players = self.video_retired_players
        self.video_retired_players = []
        self._queue_video_cleanup(players)

    def retire_media_for_transition(self):
        """Hide and retire active players without blocking the GUI thread.

        The old surface is hidden immediately while its HWND remains attached
        until the cleanup worker has completed stop.  This prevents stale native
        frames and blocks libVLC from creating a fallback top-level window.
        """
        players = self._take_active_video_players()
        self._defer_video_cleanup(players)

    def stop_media(self):
        """Mute immediately, then stop asynchronously with valid hidden HWNDs."""
        players = self._take_active_video_players()
        players.extend(self.video_standby_players)
        players.extend(self.video_retired_players)
        self.video_standby_players = []
        self.video_retired_players = []
        if self.vlc_instance is not None and self.vlc_instance not in self.video_retired_instances:
            self.video_retired_instances.append(self.vlc_instance)
        self.vlc_instance = None
        self._queue_video_cleanup(players)
        if not players and self.video_cleanup_inflight == 0:
            self._release_retired_vlc_instances()

    def _release_retired_vlc_instances(self):
        instances = self.video_retired_instances
        self.video_retired_instances = []
        for instance in instances:
            try:
                instance.release()
            except Exception:
                pass

    def shutdown_video_cleanup(self):
        # Once shutdown begins, native workers can finish in the background
        # but their bookkeeping signals must not flood a closing Qt event loop.
        # ``shutdown_for_close`` releases retired VLC instances after joining
        # the workers, so no completion callback is needed on this path.
        self.video_cleanup_signals.accept_results = False
        self.video_start_signals.accept_results = False
        if not self.video_start_closed:
            self.video_start_closed = True
            self.video_start_queue.put(None)
        if self.video_cleanup_closed:
            return
        self.video_cleanup_closed = True
        self.video_cleanup_queue.put(None)

    def shutdown_for_close(self, timeout=1.5):
        """Stop every native/Qt worker before the window is destroyed."""
        if self.app_closing:
            return
        self.app_closing = True
        for timer_name in (
            "image_update_timer",
            "video_timer",
            "video_ready_timer",
            "vlc_prewarm_timer",
            "video_cleanup_idle_timer",
            "viewer_preload_timer",
            "webtoon_idle_timer",
            "webtoon_build_timer",
            "animated_image_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self.stop_webtoon_auto_scroll()
        self.stop_media()
        self.shutdown_video_cleanup()
        for pool in (
            getattr(self, "decode_pool", None),
            getattr(self, "preload_decode_pool", None),
            getattr(self, "animated_image_pool", None),
        ):
            if pool is not None:
                pool.clear()
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            unfinished = getattr(self.video_cleanup_queue, "unfinished_tasks", 0)
            if unfinished <= 0 and not self.video_start_inflight:
                break
            time.sleep(0.01)
        for pool in (
            getattr(self, "decode_pool", None),
            getattr(self, "preload_decode_pool", None),
            getattr(self, "animated_image_pool", None),
        ):
            if pool is not None:
                pool.waitForDone(max(0, int((deadline - time.monotonic()) * 1000)))
        for thread in (
            getattr(self, "video_start_thread", None),
            getattr(self, "video_cleanup_thread", None),
            getattr(self, "vlc_init_thread", None),
            getattr(self, "video_player_create_thread", None),
        ):
            if thread is not None and thread.is_alive():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        self._release_retired_vlc_instances()

    def deactivate(self):
        self.cancel_pending_decodes()
        self.render_generation += 1
        self.decode_pool.clear()
        self.preload_decode_pool.clear()
        self.decode_inflight.clear()
        self.stop_webtoon_auto_scroll()
        if hasattr(self, "vlc_prewarm_timer"):
            self.vlc_prewarm_timer.stop()
        # Returning to the explorer releases standby players and the VLC
        # instance too; keeping them attached to a hidden viewer wastes native
        # memory and can leave an audio callback alive.
        self.stop_media()
        self.viewer_preload_queue = []
        self.viewer_preload_queued = set()
        if hasattr(self, "viewer_preload_timer"):
            self.viewer_preload_timer.stop()
        if hasattr(self, "webtoon_idle_timer"):
            self.webtoon_idle_timer.stop()
        if hasattr(self, "webtoon_build_timer"):
            self.webtoon_build_timer.stop()
        self.webtoon_pending_paths = []
        self.webtoon_container_layout = None
        if hasattr(self, "overlay_timer"):
            self.overlay_timer.stop()
        self.hide_overlays()

    def stop_animated_image(self):
        if hasattr(self, "animated_image_timer"):
            self.animated_image_timer.stop()
        for task in list(getattr(self, "animated_image_task_refs", set())):
            task.cancel()
        if hasattr(self, "animated_image_pool"):
            self.animated_image_pool.clear()
        self.animated_image_states = {}
        self.animated_image_reader = None
        self.animated_image_frame_count = 0
        self.animated_image_index = 0
        self.animated_image_label = None
        self.animated_image_path = None

    def animated_render_spec(self):
        area = self.viewer_area()
        return {
            "area_width": area.width(),
            "area_height": area.height(),
            "fit_mode": self.fit_mode,
            "zoom_factor": self.zoom_factor,
            "rotation": self.rotation,
            "max_frame_pixels": self.performance_policy.max_animated_frame_pixels,
        }

    def try_start_animated_image(self, label, path):
        path = Path(path)
        if not self.is_animated_image_path(path):
            return False
        key = id(label)
        existing = self.animated_image_states.get(key)
        render_spec = self.animated_render_spec()
        if existing and existing.get("path") == path and existing.get("label") is label:
            task = existing.get("task")
            if task is not None:
                if existing.get("render_spec") != render_spec:
                    self.animated_render_token += 1
                    existing["render_token"] = self.animated_render_token
                    existing["render_spec"] = render_spec
                    task.update_render_spec(self.animated_render_token, render_spec)
                return True
        if existing:
            task = existing.get("task")
            if task is not None:
                task.cancel()
        self.animated_image_token += 1
        self.animated_render_token += 1
        token = self.animated_image_token
        render_token = self.animated_render_token
        task = AnimatedImageTask(
            self.render_generation,
            key,
            token,
            path,
            render_token,
            render_spec,
            self.playback_rate,
            archive_source=self.archive_sources.get(str(path)),
        )
        state = {
            "task": task,
            "token": token,
            "render_token": render_token,
            "render_spec": render_spec,
            "frame_count": 0,
            "index": 0,
            "label": label,
            "path": path,
            "has_frame": False,
        }
        self.animated_image_states[key] = state
        self.animated_image_task_refs.add(task)
        task.signals.frameReady.connect(self.animated_frame_ready, Qt.QueuedConnection)
        task.signals.finished.connect(self.animated_image_finished, Qt.QueuedConnection)
        self.animated_image_pool.start(task, 10)
        self.animated_image_index = 0
        self.animated_image_label = label
        self.animated_image_path = path
        return True

    def animated_frame_ready(self, result):
        task = result.get("task")
        try:
            if result.get("generation") != self.render_generation:
                return
            state = self.animated_image_states.get(result.get("state_key"))
            if (
                state is None
                or state.get("task") is not task
                or state.get("token") != result.get("token")
                or state.get("render_token") != result.get("render_token")
                or str(state.get("path")) != result.get("path")
            ):
                return
            label = state.get("label")
            if label is None or label.parent() is None:
                return
            image = result.get("image")
            if not isinstance(image, QImage) or image.isNull():
                return
            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                return
            label.setMinimumHeight(0)
            label.setText("")
            label.setPixmap(pixmap)
            state["has_frame"] = True
            state["frame_count"] = int(result.get("frame_count", 1))
            state["index"] = int(result.get("index", 0))
            self.animated_image_frame_count = state["frame_count"]
            self.animated_image_index = state["index"]
            self.animated_image_label = label
            self.animated_image_path = state["path"]
            state["last_duration"] = int(result.get("duration", 80) or 80)
            if bool(result.get("animated")):
                self.current_has_animation = True
                self.animated_rate_btn.show()
                self.position_overlays()
        except RuntimeError:
            pass
        finally:
            if task is not None:
                task.acknowledge()

    def animated_image_finished(self, result):
        task = result.get("task")
        self.animated_image_task_refs.discard(task)
        state = self.animated_image_states.get(result.get("state_key"))
        if state is None or state.get("task") is not task or state.get("token") != result.get("token"):
            return
        state["task"] = None
        if result.get("error") and not state.get("has_frame") and result.get("generation") == self.render_generation:
            label = state.get("label")
            try:
                if label is not None and label.parent() is not None:
                    label.setText(Path(result.get("path", "")).name)
                    self.queue_viewer_decode(label, state["path"], self.render_generation, priority=10)
            except RuntimeError:
                pass

    def render_animated_image_frame(self, state=None):
        if state is None and self.animated_image_states:
            state = next(iter(self.animated_image_states.values()))
        if state is None:
            return 80
        task = state.get("task")
        if task is not None:
            self.animated_render_token += 1
            render_spec = self.animated_render_spec()
            state["render_token"] = self.animated_render_token
            state["render_spec"] = render_spec
            task.update_render_spec(self.animated_render_token, render_spec)
        return 80

    def advance_animated_image(self):
        if hasattr(self, "animated_image_timer"):
            self.animated_image_timer.stop()

    def update_image_labels(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.webtoon_loaded = set()
            self.update_webtoon_visible_images(generation)
            return
        for label, path in self.labels:
            if self.is_animated_image_path(path):
                self.try_start_animated_image(label, path)
                continue
            label.setText("Loading…")
            self.queue_viewer_decode(
                label,
                path,
                self.render_generation,
                priority=10,
                render_token=self.image_update_token,
            )

    def start_visible_animations(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            return
        for label, path in self.labels:
            if self.is_animated_image_path(path):
                self.try_start_animated_image(label, path)

    def load_image_label(self, label, path):
        if self.try_start_animated_image(label, path):
            return True
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            if self.webtoon_target_width is None:
                self.reset_webtoon_target_width(path)
            pix = self.scaled_static_pixmap(path, self.webtoon_target_width)
            if pix.isNull():
                label.setText(path.name)
                return False
            label.setFixedSize(pix.size())
            label.setText("")
            label.setPixmap(pix)
            QTimer.singleShot(0, self.update_webtoon_container_extent)
            return True
        pix = QPixmap(str(path))
        if pix.isNull():
            label.setText(path.name)
            return False
        if self.rotation:
            from PySide6.QtGui import QTransform
            pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
        target = self.target_size(label, pix)
        label.setMinimumHeight(0)
        label.setText("")
        label.setPixmap(pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return True

    def append_webtoon_labels(self, count=6):
        if (
            self.webtoon_build_generation != self.render_generation
            or self.webtoon_container_layout is None
            or not self.is_webtoon_viewer_mode()
        ):
            self.webtoon_build_timer.stop()
            return
        for _ in range(min(int(count), len(self.webtoon_pending_paths))):
            path = self.webtoon_pending_paths.pop(0)
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_StyledBackground, True)
            label.setAutoFillBackground(True)
            placeholder_width = max(1, int(self.webtoon_target_width or WEBTOON_MIN_WIDTH))
            label.setFixedSize(placeholder_width, 120)
            label.setStyleSheet("background: #050505; color: #777;")
            label.setText(path.name)
            self.webtoon_container_layout.addWidget(label, 0, Qt.AlignHCenter)
            self.labels.append((label, path))
            self.webtoon_label_indices[id(label)] = len(self.labels) - 1
        if not self.webtoon_pending_paths:
            self.webtoon_build_timer.stop()
        QTimer.singleShot(0, self.update_webtoon_container_extent)
        self.schedule_webtoon_visible_update(self.render_generation)

    def update_webtoon_container_extent(self):
        if not self.webtoon_container or not self.webtoon_container_layout:
            return
        self.webtoon_container_layout.activate()
        height = max(1, self.webtoon_container_layout.sizeHint().height())
        self.webtoon_container.setMinimumHeight(height)
        self.webtoon_container.updateGeometry()
        self.webtoon_label_tops = [label.y() for label, _ in self.labels]

    def visible_webtoon_indices(self, margin=2):
        if not self.webtoon_scroll or not self.labels:
            return []
        viewport_top = self.webtoon_scroll.verticalScrollBar().value()
        if len(self.webtoon_label_tops) != len(self.labels):
            self.webtoon_label_tops = [label.y() for label, _ in self.labels]
        anchor = bisect.bisect_left(self.webtoon_label_tops, viewport_top)
        if anchor >= len(self.labels):
            anchor = len(self.labels) - 1
        start = max(0, anchor - margin)
        end = min(len(self.labels) - 1, anchor + margin)
        return list(range(start, end + 1))

    def update_webtoon_visible_images(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        margin = 4 if self.webtoon_auto_scroll_active else 2
        visible = set(
            self.visible_webtoon_indices(
                margin=max(margin, int(self.performance_policy.webtoon_lookahead) + 1)
            )
        )
        self.release_offscreen_webtoon_pixmaps(visible)
        for idx in visible:
            if idx in self.webtoon_loaded:
                continue
            label, path = self.labels[idx]
            if label.property("decode_generation") == self.render_generation:
                continue
            label.setProperty("decode_generation", self.render_generation)
            self.queue_viewer_decode(label, path, self.render_generation, priority=10)

    def release_offscreen_webtoon_pixmaps(self, visible=None):
        if not self.labels or not self.is_webtoon_viewer_mode():
            return
        if visible is None:
            visible = set(self.visible_webtoon_indices(
                margin=max(2, int(self.performance_policy.webtoon_lookahead) + 1)
            ))
        for idx in list(self.webtoon_loaded):
            if idx < 0 or idx >= len(self.labels):
                self.webtoon_loaded.discard(idx)
                continue
            label, path = self.labels[idx]
            if idx in visible:
                continue
            if not label.pixmap().isNull():
                label.setPixmap(QPixmap())
                label.setText(path.name)
                label.setFixedSize(
                    max(1, int(self.webtoon_target_width or WEBTOON_MIN_WIDTH)),
                    120,
                )
                self.webtoon_loaded.discard(idx)

    def load_next_webtoon_idle_image(self):
        if self.viewer_mode not in ("webtoon", "webtoon_vertical") or not self.labels:
            self.webtoon_idle_timer.stop()
            return
        if not self.performance_policy.idle_webtoon_preload:
            self.webtoon_idle_timer.stop()
            return
        self.update_webtoon_visible_images(self.render_generation)
        if any(str(path) in self.archive_sources for _, path in self.labels):
            # ZIP browsing is intentionally demand-driven: visible members and
            # the small nearby margin are decoded, never the entire archive.
            self.webtoon_idle_timer.stop()
            return
        visible_margin = max(
            4 if self.webtoon_auto_scroll_active else 2,
            int(self.performance_policy.webtoon_lookahead) + 1,
        )
        visible = set(self.visible_webtoon_indices(margin=visible_margin))
        for _ in range(len(self.labels)):
            idx = self.webtoon_idle_index % len(self.labels)
            self.webtoon_idle_index += 1
            if idx in self.webtoon_loaded or idx in visible:
                continue
            label, path = self.labels[idx]
            if label.property("decode_generation") != self.render_generation:
                label.setProperty("decode_generation", self.render_generation)
                self.queue_viewer_decode(label, path, self.render_generation, priority=-10, preload=True)
            break
        if len(self.webtoon_loaded) >= len(self.labels):
            self.webtoon_idle_timer.stop()

    def target_size(self, label, pix):
        area = self.viewer_area()
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            if self.webtoon_target_width is None:
                self.webtoon_target_width = self.compute_webtoon_target_width()
            width = max(1, int(self.webtoon_target_width))
            if pix.width() <= 0:
                return QSize(width, max(1, pix.height()))
            return QSize(width, max(1, int(pix.height() * width / pix.width())))
        if self.fit_mode == "fit_width":
            base = QSize(area.width(), max(1, int(pix.height() * area.width() / pix.width())))
        elif self.fit_mode == "fit_window":
            scale = min(area.width() / pix.width(), area.height() / pix.height())
            base = QSize(max(1, int(pix.width() * scale)), max(1, int(pix.height() * scale)))
        elif self.fit_mode == "manual":
            # The decode request already includes the manual zoom factor.
            # Applying it again here made each resize/zoom gesture compound
            # the scale and caused large images to balloon in memory.
            return pix.size()
        elif self.fit_mode == "actual":
            return pix.size()
        else:
            base = QSize(max(1, int(pix.width() * area.height() / pix.height())), area.height())
        return QSize(max(1, int(base.width() * self.zoom_factor)), max(1, int(base.height() * self.zoom_factor)))
        """
        if self.fit_mode == "actual":
            return QSize(max(1, int(pix.width() * self.zoom_factor)), max(1, int(pix.height() * self.zoom_factor)))
        if self.fit_mode == "fit_width":
            return QSize(area.width(), max(1, int(pix.height() * area.width() / pix.width())))
        if self.fit_mode == "fit_window":
            return area
        if self.fit_mode == "manual":
            return QSize(max(1, int(pix.width() * self.zoom_factor)), max(1, int(pix.height() * self.zoom_factor)))
        return QSize(max(1, int(pix.width() * area.height() / pix.height())), area.height())
        """

    def viewer_area(self):
        size = self.central.size()
        width = max(1, size.width())
        height = max(1, size.height())
        if self.viewer_mode == "double":
            width = max(1, width // 2)
        elif self.viewer_mode == "triple":
            width = max(1, width // 3)
        return QSize(width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_overlays()
        if self.is_active_viewer():
            self.schedule_image_update()

    def mouseMoveEvent(self, event):
        self.show_overlays(event.position().toPoint())
        super().mouseMoveEvent(event)

    def position_overlays(self):
        margin = 14
        self.viewer_overlay.adjustSize()
        self.rotation_overlay.adjustSize()
        self.video_overlay.adjustSize()
        viewer_w = min(self.viewer_overlay.sizeHint().width(), max(220, self.central.width() - margin * 2))
        viewer_h = self.viewer_overlay.sizeHint().height()
        self.viewer_overlay.setGeometry(
            max(margin, (self.central.width() - viewer_w) // 2),
            margin,
            viewer_w,
            viewer_h,
        )
        rotate_w = min(self.rotation_overlay.sizeHint().width(), max(160, self.central.width() - margin * 2))
        rotate_h = self.rotation_overlay.sizeHint().height()
        self.rotation_overlay.setGeometry(
            max(margin, (self.central.width() - rotate_w) // 2),
            max(margin, self.central.height() - rotate_h - margin),
            rotate_w,
            rotate_h,
        )
        video_w = min(self.video_overlay.sizeHint().width(), max(220, self.central.width() - margin * 2))
        video_h = self.video_overlay.sizeHint().height()
        self.video_overlay.setGeometry(
            max(margin, (self.central.width() - video_w) // 2),
            max(margin, self.central.height() - video_h - margin),
            video_w,
            video_h,
        )
        self.webtoon_auto_scroll_overlay.adjustSize()
        webtoon_w = min(self.webtoon_auto_scroll_overlay.sizeHint().width(), max(130, self.central.width() - margin * 2))
        webtoon_h = self.webtoon_auto_scroll_overlay.sizeHint().height()
        self.webtoon_auto_scroll_overlay.setGeometry(
            max(margin, self.central.width() - webtoon_w - margin),
            max(margin, (self.central.height() - webtoon_h) // 2),
            webtoon_w,
            webtoon_h,
        )
        if not self.is_webtoon_viewer_mode():
            self.webtoon_auto_scroll_overlay.hide()
        # A transparent Qt widget raised above VLC's native Direct3D HWND is
        # composed as an opaque black rectangle on Windows.  It used to cover
        # exactly the lower 90 logical pixels of every video.  Keep it hidden;
        # update_video_controls() polls the cursor for the same hover behavior.
        self.input_layer.hide()
        self.viewer_overlay.raise_()
        self.rotation_overlay.raise_()
        self.video_overlay.raise_()
        self.webtoon_auto_scroll_overlay.raise_()

    def show_overlays(self, pos=None):
        self.position_overlays()
        if pos is None:
            pos = self.central.mapFromGlobal(self.cursor().pos())
        top_hot = self.viewer_overlay.geometry().adjusted(-24, -24, 24, 28)
        bottom_widget = self.video_overlay if getattr(self, "current_is_video", False) else self.rotation_overlay
        bottom_hot = bottom_widget.geometry().adjusted(-24, -28, 24, 24)
        show_top = top_hot.contains(pos) or self.viewer_overlay.geometry().contains(pos)
        show_bottom = bottom_hot.contains(pos) or bottom_widget.geometry().contains(pos)
        if show_top:
            self.viewer_overlay.show()
        if getattr(self, "current_is_video", False):
            if show_bottom:
                self.video_overlay.show()
            self.rotation_overlay.hide()
        else:
            self.video_overlay.hide()
            if show_bottom:
                self.rotation_overlay.show()
        if self.viewer_overlay.isVisible() or self.video_overlay.isVisible() or self.rotation_overlay.isVisible():
            self.overlay_timer.start(1800)
        if self.is_webtoon_viewer_mode():
            webtoon_hot = self.webtoon_auto_scroll_overlay.geometry().adjusted(-36, -36, 36, 36)
            if webtoon_hot.contains(pos):
                self.show_webtoon_auto_scroll_overlay()

    def hide_overlays(self):
        self.viewer_overlay.hide()
        self.rotation_overlay.hide()
        self.video_overlay.hide()

    def wheelEvent(self, event):
        if self.handle_wheel_delta(event.angleDelta().y()):
            return
        if event.angleDelta().y() < 0:
            self.next_media()
        else:
            self.previous_media()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.toggle_fullscreen()
        elif event.button() == Qt.BackButton:
            self.previous_media()
        elif event.button() == Qt.ForwardButton:
            self.next_media()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.point_on_overlay(self.central.mapFromGlobal(event.globalPosition().toPoint())):
            return
        self.exitRequested.emit()

    def keyPressEvent(self, event):
        if self.handle_direct_zoom_key(event):
            return
        if event.matches(QKeySequence.Copy):
            self.copy_current()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            return
        if event.key() == Qt.Key_Escape and self.window().isFullScreen():
            self.window().showNormal()
        elif event.key() == Qt.Key_Escape:
            self.exitRequested.emit()
        elif event.key() == Qt.Key_PageDown:
            self.next_media()
        elif event.key() == Qt.Key_PageUp:
            self.previous_media()
        elif event.key() == Qt.Key_Home:
            self.first_media()
        elif event.key() == Qt.Key_End:
            self.last_media()
        elif event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier and self.is_webtoon_viewer_mode():
            self.toggle_webtoon_auto_scroll()
        elif event.key() == Qt.Key_Space:
            self.handle_space()
        elif event.key() == Qt.Key_Delete:
            self.request_delete_current()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if not self.is_active_viewer():
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Resize and obj.objectName() == "videoFrame":
            try:
                label = obj.findChild(QLabel, "videoStatusLabel")
                if label is not None:
                    label.setGeometry(obj.rect())
            except RuntimeError:
                pass
        if event.type() == QEvent.KeyPress:
            if self.handle_direct_zoom_key(event):
                return True
            if event.matches(QKeySequence.Copy):
                self.copy_current()
                return True
            if event.matches(QKeySequence.Paste):
                self.pasteRequested.emit()
                return True
            if event.key() == Qt.Key_PageDown:
                if self.scroll_webtoon_page(1):
                    return True
                self.next_media()
                return True
            if event.key() == Qt.Key_PageUp:
                if self.scroll_webtoon_page(-1):
                    return True
                self.previous_media()
                return True
            if event.key() == Qt.Key_Home:
                self.first_media()
                return True
            if event.key() == Qt.Key_End:
                self.last_media()
                return True
            if event.key() == Qt.Key_Space and event.modifiers() & Qt.ControlModifier and self.is_webtoon_viewer_mode():
                self.toggle_webtoon_auto_scroll()
                return True
            if event.key() == Qt.Key_Space:
                self.handle_space()
                return True
            if event.key() == Qt.Key_Delete:
                self.request_delete_current()
                return True
            if event.key() == Qt.Key_Escape:
                if self.window().isFullScreen():
                    self.window().showNormal()
                else:
                    self.exitRequested.emit()
                return True
        if event.type() == QEvent.Wheel:
            if self.handle_wheel_delta(event.angleDelta().y()):
                return True
            if event.angleDelta().y() < 0:
                self.next_media()
            else:
                self.previous_media()
            return True
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.MiddleButton:
                self.toggle_fullscreen()
                return True
            if event.button() == Qt.BackButton:
                self.previous_media()
                return True
            if event.button() == Qt.ForwardButton:
                self.next_media()
                return True
        if event.type() == QEvent.ContextMenu:
            self.show_context_menu(event.globalPos())
            return True
        if event.type() == QEvent.MouseButtonDblClick:
            pos = self.central.mapFromGlobal(event.globalPosition().toPoint())
            if self.point_on_overlay(pos):
                return False
            self.exitRequested.emit()
            return True
        if event.type() == QEvent.MouseMove:
            self.show_overlays(event.position().toPoint())
        return super().eventFilter(obj, event)

    def is_active_viewer(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "main_stack"):
            return parent.main_stack.currentWidget() is self
        return self.isVisible()

    def _video_lifecycle_busy(self):
        now = time.monotonic()
        active_starts = any(
            now - float(started) < VIDEO_START_TIMEOUT_MS / 1000.0
            for started in self.video_start_started.values()
        )
        # Cleanup owns retired VLC players on its worker thread.  It does not
        # prevent the GUI from rendering the next image/video: a new video
        # request simply waits for a fresh standby slot while cleanup drains.
        # Treating cleanup as a navigation lock made rapid mixed-media moves
        # appear stuck until an unrelated event arrived.
        return bool(active_starts)

    def _resume_pending_navigation(self):
        if self._video_lifecycle_busy() or self.pending_navigation_index is None:
            return False
        target = max(0, min(len(self.items) - 1, int(self.pending_navigation_index)))
        render_requested = bool(self.pending_render_requested)
        render_reset = bool(self.pending_render_reset)
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        if target == self.index and not render_requested:
            return False
        self.index = target
        self.show_current(reset=render_reset or not self.zoom_locked)
        return True

    def next_media(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(1)
            return
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        base_index = self.pending_navigation_index if self.pending_navigation_index is not None else self.index
        new_index = min(len(self.items) - 1, base_index + step)
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        if new_index == self.index:
            return
        self.index = new_index
        self.show_current(reset=not self.zoom_locked)

    def next_media_wrap(self):
        if not self.items:
            return
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(1)
            return
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        base_index = self.pending_navigation_index if self.pending_navigation_index is not None else self.index
        new_index = (base_index + step) % len(self.items)
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        self.index = new_index
        self.show_current(reset=not self.zoom_locked)

    def handle_space(self):
        if getattr(self, "current_is_video", False):
            self.toggle_play()
        else:
            self.next_media_wrap()

    def request_delete_current(self):
        if not self.items:
            return
        self.deleteRequested.emit(str(self.items[self.index]))

    def copy_current(self):
        if not self.items:
            return
        self.copyRequested.emit(str(self.items[self.index]))

    def cut_current(self):
        if self.items:
            self.cutRequested.emit(str(self.items[self.index]))

    def properties_current(self):
        if self.items:
            self.propertiesRequested.emit(str(self.items[self.index]))

    def add_menu_action(self, menu, label, callback, shortcut_key=None, checkable=False, checked=False):
        action = menu.addAction(label)
        action.triggered.connect(callback)
        action.setCheckable(checkable)
        action.setChecked(checked)
        if shortcut_key:
            sequences = self.settings.get("shortcuts", {}).get(shortcut_key, [])
            if sequences:
                action.setShortcut(QKeySequence(sequences[0]))
        return action

    def build_context_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #211f29; color: #f4f0fb; border: 1px solid #4a4459; border-radius: 7px; padding: 2px; font-size: 8pt; }
            QMenu::item { padding: 1px 17px 1px 7px; min-height: 12px; border-radius: 4px; }
            QMenu::item:selected { background: #8c78cf; color: white; }
            QMenu::separator { height: 1px; background: #454052; margin: 2px 5px; }
            QMenu::indicator { width: 10px; height: 10px; }
        """)
        self.add_menu_action(menu, "Zoom In", self.zoom_in, "zoom_in")
        self.add_menu_action(menu, "Zoom Out", self.zoom_out, "zoom_out")
        menu.addSeparator()
        self.add_menu_action(menu, "Fit Height", lambda: self.set_fit_mode("fit_height"), "fit_height")
        self.add_menu_action(menu, "Fit Width", lambda: self.set_fit_mode("fit_width"), "fit_width")
        self.add_menu_action(menu, "Window Fit", lambda: self.set_fit_mode("fit_window"), "fit_window")
        self.add_menu_action(menu, "Original Size", lambda: self.set_fit_mode("actual"), "actual_size")
        self.add_menu_action(
            menu,
            "Lock",
            self.toggle_zoom_lock,
            "toggle_zoom_lock",
            checkable=True,
            checked=self.zoom_locked,
        )
        menu.addSeparator()
        self.add_menu_action(menu, "Single", lambda: self.set_viewer_mode("single"), "viewer_single")
        double_menu = menu.addMenu("Double")
        double_menu.addAction("Page", lambda: self.set_viewer_mode("double", "page"))
        double_menu.addAction("Manga Page", lambda: self.set_viewer_mode("double", "manga_page"))
        double_menu.addAction("Slide", lambda: self.set_viewer_mode("double", "slide"))
        triple_menu = menu.addMenu("Triple")
        triple_menu.addAction("Page", lambda: self.set_viewer_mode("triple", "page"))
        triple_menu.addAction("Slide", lambda: self.set_viewer_mode("triple", "slide"))
        self.add_menu_action(menu, "Webtoon", lambda: self.set_viewer_mode("webtoon_vertical"), "viewer_webtoon")
        menu.addSeparator()
        self.add_menu_action(menu, "Rotate Left", self.rotate_left, "rotate_left")
        self.add_menu_action(menu, "Rotate Right", self.rotate_right, "rotate_right")
        self.add_menu_action(menu, "Reset Rotation", self.reset_rotation, "reset_rotation")
        menu.addSeparator()
        menu.addAction("Cut", self.cut_current)
        menu.addAction("Copy", self.copy_current)
        menu.addAction("Paste", self.pasteRequested.emit)
        menu.addAction("Delete", self.request_delete_current)
        menu.addAction("Properties", self.properties_current)
        return menu

    def show_context_menu(self, global_pos):
        menu = self.build_context_menu()
        menu.exec(global_pos)

    def remove_current_after_delete(self, deleted_path):
        deleted_path = str(deleted_path)
        self.items = [p for p in self.items if str(p) != deleted_path]
        if not self.items:
            return False
        self.index = min(self.index, len(self.items) - 1)
        self.show_current(reset=not self.zoom_locked)
        return True

    def previous_media(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(-1)
            return
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        base_index = self.pending_navigation_index if self.pending_navigation_index is not None else self.index
        new_index = max(0, base_index - step)
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        if new_index == self.index:
            return
        self.index = new_index
        self.show_current(reset=not self.zoom_locked)

    def first_media(self):
        if self.index == 0:
            return
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        self.index = 0
        self.show_current(reset=not self.zoom_locked)

    def last_media(self):
        last_index = max(0, len(self.items) - 1)
        if self.index == last_index:
            return
        self.pending_navigation_index = None
        self.pending_render_requested = False
        self.pending_render_reset = False
        self.index = last_index
        self.show_current(reset=not self.zoom_locked)

    def handle_wheel_delta(self, delta):
        if self.scroll_webtoon(delta):
            return True
        if delta < 0:
            self.next_media()
        else:
            self.previous_media()
        return True

    def scroll_webtoon(self, delta):
        if self.viewer_mode not in ("webtoon", "webtoon_vertical") or not self.webtoon_scroll:
            return False
        if self.webtoon_auto_scroll_active:
            self.stop_webtoon_auto_scroll()
        bar = self.webtoon_scroll.verticalScrollBar()
        step = max(24, int(abs(delta) * 0.45))
        bar.setValue(bar.value() - step if delta > 0 else bar.value() + step)
        return True

    def scroll_webtoon_page(self, direction):
        if self.viewer_mode not in ("webtoon", "webtoon_vertical") or not self.webtoon_scroll:
            return False
        bar = self.webtoon_scroll.verticalScrollBar()
        step = max(1, self.webtoon_scroll.viewport().height() - 80)
        bar.setValue(bar.value() + direction * step)
        return True

    def point_on_overlay(self, pos):
        overlays = [self.viewer_overlay, self.rotation_overlay, self.video_overlay, self.webtoon_auto_scroll_overlay]
        return any(widget.isVisible() and widget.geometry().contains(pos) for widget in overlays)

    def force_manual_for_zoom(self):
        if self.fit_mode == "manual":
            return
        scale = self.current_display_scale()
        self.fit_mode = "manual"
        self.zoom_factor = scale
        self.fit_combo.blockSignals(True)
        self.fit_combo.setCurrentText("manual")
        self.fit_combo.blockSignals(False)
        self.settings["default_fit"] = "manual"
        save_settings(self.settings)
        self.update_manual_zoom_controls()

    def zoom_to_region(self, label, rect):
        if rect is None or rect.width() < 2 or rect.height() < 2:
            return
        self.force_manual_for_zoom()
        multiplier = min(label.width() / rect.width(), label.height() / rect.height())
        multiplier = max(1.0, min(20.0, float(multiplier)))
        center_delta = label.rect().center() - rect.center()
        self.zoom_factor = max(0.05, min(10.0, self.zoom_factor * multiplier))
        self.update_manual_zoom_text()
        self.schedule_image_update()
        QTimer.singleShot(
            0,
            lambda target=label, delta=center_delta, factor=multiplier: target.set_pan_offset(
                QPoint(int(delta.x() * factor), int(delta.y() * factor))
            ),
        )

    def current_display_scale(self):
        for label, path in self.labels:
            if self.viewer_mode in ("webtoon", "webtoon_vertical"):
                size = self.image_pixel_size(path)
                if size.isValid() and size.width() > 0:
                    width = self.webtoon_target_width or self.compute_webtoon_target_width(path)
                    return max(0.05, min(10.0, width / size.width()))
            source_size = self.image_pixel_size(path)
            display_pixmap = getattr(label, "_viewer_pixmap", QPixmap())
            if not source_size.isValid() or source_size.width() <= 0 or display_pixmap.isNull():
                continue
            return max(0.05, min(10.0, display_pixmap.width() / source_size.width()))
        return max(0.05, min(10.0, self.zoom_factor))

    def handle_direct_zoom_key(self, event):
        """Handle physical +/- keys consistently, including the keypad."""
        if event is None or event.type() != QEvent.KeyPress:
            return False
        modifiers = event.modifiers()
        blocked = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        if modifiers & blocked:
            return False
        key = event.key()
        text = event.text()
        if key == Qt.Key_Plus or text == "+":
            self.zoom_in()
            event.accept()
            return True
        if key == Qt.Key_Minus or text in ("-", "−"):
            self.zoom_out()
            event.accept()
            return True
        return False

    def zoom_in(self):
        self.force_manual_for_zoom()
        self.zoom_factor = min(10.0, self.zoom_factor * 1.15)
        self.update_manual_zoom_text()
        self.schedule_image_update()

    def zoom_out(self):
        self.force_manual_for_zoom()
        self.zoom_factor = max(0.05, self.zoom_factor / 1.15)
        self.update_manual_zoom_text()
        self.schedule_image_update()

    def rotate_right(self):
        self.rotation = (self.rotation + 90) % 360
        self.schedule_image_update()

    def rotate_left(self):
        self.rotation = (self.rotation - 90) % 360
        self.schedule_image_update()

    def reset_rotation(self):
        self.rotation = 0
        self.schedule_image_update()

    def set_fit_mode(self, mode):
        self.fit_mode = mode
        self.zoom_factor = 1.0
        self.settings["default_fit"] = mode
        save_settings(self.settings)
        self.update_manual_zoom_controls()
        self.schedule_image_update()

    def set_viewer_mode(self, mode, step=None):
        self.viewer_mode = mode
        if step is not None:
            self.step_mode = step
        self.settings["viewer_mode"] = mode
        self.settings["viewer_step"] = self.step_mode
        save_settings(self.settings)
        self.update_mode_button()
        self.show_current(reset=False)

    def toggle_zoom_lock(self):
        self.zoom_locked = not self.zoom_locked if not isinstance(self.sender(), QPushButton) else self.lock_btn.isChecked()
        self.lock_btn.setChecked(self.zoom_locked)
        self.settings["zoom_locked"] = self.zoom_locked
        save_settings(self.settings)

    def toggle_play(self):
        if not self.media_player:
            return
        try:
            state = self.media_player.get_state()
        except Exception:
            state = None
        ended_states = []
        if vlc is not None:
            ended_states = [vlc.State.Ended, vlc.State.Stopped, vlc.State.Error]
        if self.video_finished or self.video_stopped_by_user or state in ended_states:
            self.replay_video()
            return
        if state == getattr(vlc.State, "Paused", None):
            self.media_player.play()
            self.video_timer.start(250)
        elif state == getattr(vlc.State, "Playing", None):
            self.media_player.pause()
        else:
            self.media_player.play()
            self.video_timer.start(250)

    def replay_video(self):
        if not self.media_player:
            return
        try:
            restarting = self.video_stopped_by_user or self.video_finished
            primary_token = None
            primary_state = None
            for token, state in self.video_slot_states.items():
                if state.get("primary") and state.get("player") is self.media_player:
                    primary_token = token
                    primary_state = state
                    break
            if restarting and primary_token is not None:
                self._restart_video_slot(primary_token, force=True)
                return
            self.video_finished = False
            self.video_stopped_by_user = False
            self.media_player.set_time(0)
            self.media_player.play()
            self.apply_video_playback_rate(self.media_player)
            self.media_player.audio_set_volume(self.volume_slider.value())
            if primary_state is not None:
                primary_state["ended"] = False
                primary_state["restarting"] = False
            self.video_timer.start(250)
        except Exception:
            pass

    def set_video_volume(self, value):
        players = [self.media_player, *self.extra_media_players]
        for player in players:
            if player is None:
                continue
            lock = self.video_player_locks.setdefault(id(player), threading.RLock())
            if not lock.acquire(timeout=0.01):
                continue
            try:
                player.audio_set_volume(value)
                # Only the primary slot is audible.  Keeping the secondary
                # players muted prevents audio from a previous page leaking
                # while the next video is still being prepared.
                player.audio_set_mute(player is not self.media_player)
            except Exception:
                pass
            finally:
                lock.release()

    def begin_video_seek(self):
        self._seeking_video = True

    def preview_video_seek(self, value):
        length = self.video_length()
        if length > 0:
            self.time_label.setText(f"{self.format_ms(int(length * value / 1000))} / {self.format_ms(length)}")

    def finish_video_seek(self):
        length = self.video_length()
        if self.media_player and length > 0:
            try:
                self.media_player.set_time(int(length * self.seek_slider.value() / 1000))
            except Exception:
                pass
        self._seeking_video = False

    def video_length(self):
        if not self.media_player:
            return 0
        try:
            return max(0, int(self.media_player.get_length()))
        except Exception:
            return 0

    def update_video_controls(self):
        if not self.media_player or self._seeking_video or self._video_lifecycle_busy():
            return
        if getattr(self, "current_is_video", False):
            cursor_pos = self.central.mapFromGlobal(QCursor.pos())
            if self.central.rect().contains(cursor_pos):
                self.show_overlays(cursor_pos)
        ended_states = set()
        if vlc is not None:
            ended_states = {
                getattr(vlc.State, "Ended", None),
                getattr(vlc.State, "Stopped", None),
                getattr(vlc.State, "Error", None),
            }
            ended_states.discard(None)
        for token, state in list(self.video_slot_states.items()):
            if state.get("ended") or state.get("restarting"):
                continue
            try:
                player_state = state["player"].get_state()
            except Exception:
                continue
            if player_state in ended_states:
                self._mark_video_ended(token)
        try:
            length = max(0, int(self.media_player.get_length()))
            current = max(0, int(self.media_player.get_time()))
        except Exception:
            return
        self.time_label.setText(f"{self.format_ms(current)} / {self.format_ms(length)}")
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(0 if length <= 0 else min(1000, int(current * 1000 / length)))
        self.seek_slider.blockSignals(False)

    def format_ms(self, ms):
        seconds = max(0, ms // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def toggle_fullscreen(self):
        top = self.window()
        if top.isFullScreen():
            top.showNormal()
        else:
            top.showFullScreen()

    def closeEvent(self, event):
        self.shutdown_for_close()
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        self.closed.emit()
        super().closeEvent(event)


class ShortcutDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.working_settings = copy.deepcopy(settings)
        self.setWindowTitle("Shortcut Settings")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)
        self.rows = {}
        form_widget = QWidget()
        form_widget.setObjectName("settingsForm")
        form = QFormLayout(form_widget)
        form.setContentsMargins(10, 10, 10, 10)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.working_settings.get("theme", "dark"))
        self.theme_combo.currentTextChanged.connect(self.set_theme)
        form.addRow("theme", self.theme_combo)
        self.instance_combo = QComboBox()
        self.instance_combo.addItems(["multi", "single"])
        self.instance_combo.setCurrentText(self.working_settings.get("instance_mode", "multi"))
        self.instance_combo.currentTextChanged.connect(self.set_instance_mode)
        form.addRow("instance mode", self.instance_combo)
        self.performance_combo = QComboBox()
        self.performance_combo.addItems(["conservative", "balanced", "fast"])
        self.performance_combo.setCurrentText(self.working_settings.get("performance_profile", "balanced"))
        self.performance_combo.currentTextChanged.connect(
            lambda mode: self.working_settings.__setitem__("performance_profile", mode)
        )
        form.addRow("performance", self.performance_combo)
        self.default_viewer_combo = QComboBox()
        self.default_viewer_combo.addItems(["single", "double", "triple", "webtoon"])
        self.default_viewer_combo.setCurrentText(self.working_settings.get("default_viewer_mode", "single"))
        self.default_viewer_combo.currentTextChanged.connect(
            lambda mode: self.working_settings.__setitem__("default_viewer_mode", mode)
        )
        form.addRow("default viewer mode", self.default_viewer_combo)
        self.viewer_start_combo = QComboBox()
        self.viewer_start_combo.addItems(["fullscreen", "window"])
        self.viewer_start_combo.setCurrentText(self.working_settings.get("viewer_start_mode", "fullscreen"))
        self.viewer_start_combo.currentTextChanged.connect(
            lambda mode: self.working_settings.__setitem__("viewer_start_mode", mode)
        )
        form.addRow("viewer start", self.viewer_start_combo)
        for action, values in sorted(self.working_settings.get("shortcuts", {}).items()):
            edit_btn = QPushButton(", ".join(values))
            edit_btn.clicked.connect(lambda checked=False, a=action: self.edit_action(a))
            self.rows[action] = edit_btn
            form.addRow(action, edit_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Done")
        buttons.button(QDialogButtonBox.Save).setProperty("accent", True)
        buttons.accepted.connect(self.commit_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def edit_action(self, action):
        current = ", ".join(self.working_settings["shortcuts"].get(action, []))
        text, ok = QInputDialog.getText(
            self,
            "Shortcut",
            "Comma separated shortcuts. Mouse tokens: MouseMiddle, MouseBack, MouseForward, WheelUp, WheelDown",
            text=current,
        )
        if ok:
            values = [v.strip() for v in text.split(",") if v.strip()]
            self.working_settings["shortcuts"][action] = values
            self.rows[action].setText(", ".join(values))

    def set_theme(self, theme):
        self.working_settings["theme"] = theme

    def set_instance_mode(self, mode):
        self.working_settings["instance_mode"] = mode

    def commit_changes(self):
        self.settings.clear()
        self.settings.update(copy.deepcopy(self.working_settings))
        save_settings(self.settings)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, startup_path=None):
        super().__init__()
        self.settings = load_settings()
        self.performance_policy = performance_policy_for(self.settings)
        self.closing = False
        startup_path = Path(startup_path) if startup_path else None
        self.startup_media_path = None
        startup_mode = ""
        if startup_path:
            try:
                mode = startup_path.stat().st_mode
                startup_mode = "dir" if stat_module.S_ISDIR(mode) else "file" if stat_module.S_ISREG(mode) else ""
            except OSError:
                startup_mode = ""
        if startup_mode == "file" and is_media(startup_path):
            self.current_folder = startup_path.parent
            self.startup_media_path = startup_path
        elif startup_mode == "dir":
            self.current_folder = startup_path
        else:
            self.current_folder = DEFAULT_START_FOLDER
        if not startup_mode and not self.safe_is_dir(self.current_folder):
            self.current_folder = DEFAULT_START_FOLDER
        self.settings["last_folder"] = DEFAULT_LAST_FOLDER_SETTING
        save_settings(self.settings)
        self.media_paths = []
        self.viewer = None
        self.vlc_prewarm_inflight = False
        self.vlc_prewarm_task = None
        self.vlc_prewarm_thread = None
        self.vlc_prewarm_instance = None
        self.vlc_prewarm_bundles = []
        self.explorer_geometry_before_viewer = None
        self.history = []
        self.history_index = -1
        self.entries = []
        self.archive_tempdirs = []
        self.archive_sources_by_root = {}
        self.archive_root_by_path = {}
        self.archive_context_last_used = {}
        self.archive_contexts = {}
        self.archive_member_sources = {}
        self.archive_sessions = []
        self.archive_pool = QThreadPool(self)
        self.archive_pool.setMaxThreadCount(1)
        self.archive_task_refs = set()
        self.archive_navigation_generation = 0
        self.navigation_position_serial = 0
        self.pending_navigation_position = None
        self.navigation_position_timer = QTimer(self)
        self.navigation_position_timer.setInterval(35)
        self.navigation_position_timer.timeout.connect(self.apply_pending_navigation_position)
        self.display_path = str(self.current_folder)
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.unc_generation = 0
        self.folder_cache = {}
        self.current_snapshot_key = ""
        self.explorer_dirty = False
        self.folder_scan_generation = 0
        self.folder_scan_pool = QThreadPool(self)
        self.folder_scan_pool.setMaxThreadCount(1)
        self.folder_scan_pool.setThreadPriority(QThread.LowPriority)
        self.folder_scan_task_refs = set()
        self.unc_share_task_refs = set()
        self.thumbnail_cache = {}
        self.thumbnail_cache_meta = {}
        self.thumbnail_cache_order = []
        self.thumbnail_cache_cost = {}
        self.thumbnail_cache_bytes = 0
        self.thumbnail_generation = 0
        self.thumbnail_inflight = set()
        self.thumbnail_paused = False
        self.thumbnail_pool = QThreadPool(self)
        self.thumbnail_pool.setThreadPriority(QThread.IdlePriority)
        self.file_op_pool = QThreadPool(self)
        self.file_op_pool.setMaxThreadCount(1)
        self.file_op_pool.setThreadPriority(QThread.LowPriority)
        self.file_op_task_refs = set()
        self.thumbnail_idle_cursor = 0
        self.thumbnail_task_refs = set()
        self.thumbnail_queue = deque()
        self.thumbnail_queue_set = set()
        self.thumbnail_cycle_started = False
        self.generic_media_icon = None
        self.entry_by_path = {}
        self.view_render_keys = {"list": None, "details": None}
        self.explorer_render_pending = False
        self._list_render_entries = []
        self._list_render_index = 0
        self._list_render_token = 0
        self._list_render_lightweight = True
        self._list_render_key = None
        self._list_render_scroll = 0
        self.list_item_by_path = {}
        self.detail_item_by_path = {}
        self.cut_clipboard_paths = set()
        self.tabs = []
        self.current_tab = 0
        self._loading_tab = False
        self.folder_watcher = QFileSystemWatcher(self)
        self.folder_watcher.directoryChanged.connect(self.on_watched_folder_changed)
        self.watched_folder_path = ""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.reload_current_if_available)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.apply_quick_search_now)
        self.tree_sync_timer = QTimer(self)
        self.tree_sync_timer.setSingleShot(True)
        self.tree_sync_timer.timeout.connect(self.sync_tree_selection)
        self.pending_tree_path = ""
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.queue_idle_thumbnail)
        self.thumbnail_resume_timer = QTimer(self)
        self.thumbnail_resume_timer.setSingleShot(True)
        self.thumbnail_resume_timer.setInterval(25)
        self.thumbnail_resume_timer.timeout.connect(self.resume_thumbnails_after_viewer)
        self.settings_save_timer = QTimer(self)
        self.settings_save_timer.setSingleShot(True)
        self.settings_save_timer.setInterval(250)
        self.settings_save_timer.timeout.connect(lambda: save_settings(self.settings))
        self.apply_performance_profile()
        self.startup_media_scan_timer = QTimer(self)
        self.startup_media_scan_timer.setInterval(1)
        self.startup_media_scan_timer.timeout.connect(self.process_startup_media_scan)
        self.startup_media_scan_iter = None
        self.startup_media_scan_paths = []
        self.startup_media_scan_seen = set()
        self.startup_media_scan_target = None
        self.icon_provider = QFileIconProvider()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1280, 820)
        self._build_ui()
        self.apply_theme()
        self._build_actions()
        self.native_input_filter = ViewerNativeInputFilter(self)
        QApplication.instance().installNativeEventFilter(self.native_input_filter)
        self.mouse_wheel_hook = ViewerMouseWheelHook(self)
        self.mouse_wheel_hook.install()
        self.remove_legacy_thumb_cache()
        self.ensure_folder_tab()
        if self.startup_media_path:
            self.prepare_startup_media_folder()
            QTimer.singleShot(0, self.open_startup_media)
        else:
            self.load_folder(self.current_folder)

    def _build_ui(self):
        self.tree_model = QFileSystemModel()
        self.tree_model.setRootPath("")
        self.tree_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)

        self.tree = QTreeView()
        self.tree.setModel(self.tree_model)
        for column in range(1, self.tree_model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.clicked.connect(self.on_tree_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.viewport().installEventFilter(self)

        self.preview = PreviewPanel()
        self.preview.source_resolver = self.archive_source_for_path
        self.quick_paths = QListWidget()
        self.quick_paths.setContextMenuPolicy(Qt.CustomContextMenu)
        self.quick_paths.customContextMenuRequested.connect(self.quick_paths_menu)
        self.quick_paths.itemDoubleClicked.connect(self.open_quick_path_item)
        self.quick_paths.itemActivated.connect(self.open_quick_path_item)
        self.quick_paths.setToolTip("App-only shortcut paths")
        self.populate_quick_paths()

        left_tabs = QTabWidget()
        left_tabs.setObjectName("navigationTabs")
        left_tabs.addTab(self.tree, "Folders")
        left_tabs.addTab(self.quick_paths, "Shortcuts")
        self.shortcut_add_btn = self.make_icon_button("+", self.add_typed_quick_path)
        self.shortcut_add_btn.setToolTip("Add shortcut path")
        left_tabs.setCornerWidget(self.shortcut_add_btn, Qt.TopRightCorner)
        self.shortcut_add_btn.hide()
        left_tabs.currentChanged.connect(lambda index: self.shortcut_add_btn.setVisible(index == 1))

        self.left_splitter = QSplitter(Qt.Vertical)
        self.left_splitter.addWidget(left_tabs)
        self.left_splitter.addWidget(self.preview)
        self.left_splitter.setChildrenCollapsible(False)
        self.left_splitter.setSizes([620, 220])

        self.list = ThumbList()
        self.list.openRequested.connect(self.open_path)
        self.list.previewRequested.connect(self.preview.show_path)
        self.list.customContextMenuRequested.connect(self.list_menu)
        self.list.copyRequested.connect(self.copy_selected)
        self.list.deleteRequested.connect(self.delete_selected)
        self.list.pasteRequested.connect(self.paste_from_clipboard)
        self.list.itemSelectionChanged.connect(self.update_command_buttons)
        self.list.installEventFilter(self)
        self.list.viewport().installEventFilter(self)
        self.list.verticalScrollBar().valueChanged.connect(self.prioritize_visible_thumbnails)
        self.list.horizontalScrollBar().valueChanged.connect(self.prioritize_visible_thumbnails)

        self.details = DetailsTable()
        self.details.openRequested.connect(self.open_path)
        self.details.previewRequested.connect(self.preview.show_path)
        self.details.sortedRequested.connect(self.set_sort_from_header)
        self.details.setContextMenuPolicy(Qt.CustomContextMenu)
        self.details.customContextMenuRequested.connect(self.details_menu)
        self.details.copyRequested.connect(self.copy_selected)
        self.details.deleteRequested.connect(self.delete_selected)
        self.details.pasteRequested.connect(self.paste_from_clipboard)
        self.details.itemSelectionChanged.connect(self.update_command_buttons)
        self.details.installEventFilter(self)
        self.details.viewport().installEventFilter(self)
        self.details.verticalScrollBar().valueChanged.connect(self.prioritize_visible_thumbnails)
        self.details.horizontalScrollBar().valueChanged.connect(self.prioritize_visible_thumbnails)
        self.tree.installEventFilter(self)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.list)
        self.view_stack.addWidget(self.details)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(r"Enter path, for example C:\Images or \\svr\share")
        self.path_edit.returnPressed.connect(self.go_to_typed_path)

        self.view_combo = QComboBox()
        self.view_combo.addItems(["large", "medium", "small", "list", "details"])
        self.view_combo.blockSignals(True)
        self.view_combo.setCurrentText(self.settings.get("view_mode", "large"))
        self.view_combo.blockSignals(False)
        self.view_combo.currentTextChanged.connect(self.change_view_mode)

        self.view_combo.hide()

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(4)
        header = QWidget()
        header.setObjectName("explorerHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(6, 5, 6, 6)
        header_layout.setSpacing(4)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        self.folder_tabs = QTabBar()
        self.folder_tabs.setObjectName("folderTabs")
        self.folder_tabs.setDrawBase(False)
        self.folder_tabs.setMovable(True)
        self.folder_tabs.setTabsClosable(False)
        self.folder_tabs.currentChanged.connect(self.on_folder_tab_changed)
        self.add_tab_btn = self.make_icon_button("+", self.add_folder_tab)
        tab_row.addWidget(self.folder_tabs)
        tab_row.addWidget(self.add_tab_btn)
        tab_row.addStretch(1)
        header_layout.addLayout(tab_row)

        command_row = QHBoxLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        self.select_button = QToolButton()
        self.select_button.setCheckable(True)
        self.select_button.setProperty("selectionToggle", True)
        self.select_button.setFixedSize(32, 30)
        self.select_button.clicked.connect(self.toggle_select_all)
        command_row.addWidget(self.select_button)
        command_row.addSpacing(6)
        command_row.addWidget(self.make_icon_button("", self.go_back, QStyle.SP_ArrowBack, "Back"))
        command_row.addWidget(self.make_icon_button("", self.go_forward, QStyle.SP_ArrowForward, "Forward"))
        command_row.addWidget(self.make_icon_button("", self.go_up, QStyle.SP_ArrowUp, "Up"))
        command_row.addSpacing(8)
        self.sort_button = self.make_sort_button()
        self.view_button = self.make_view_button()
        command_row.addWidget(self.sort_button)
        command_row.addSpacing(8)
        command_row.addWidget(self.view_button)
        command_row.addSpacing(8)
        command_row.addWidget(self.path_edit, 1)
        self.quick_search = QLineEdit()
        self.quick_search.setPlaceholderText("Quick Search")
        self.quick_search.textChanged.connect(self.apply_quick_search)
        command_row.addWidget(self.quick_search)
        header_layout.addLayout(command_row)

        right_layout.addWidget(header)
        right_layout.addWidget(self.view_stack, 1)

        self.explorer_root = QSplitter(Qt.Horizontal)
        self.explorer_root.addWidget(self.left_splitter)
        self.explorer_root.addWidget(right_widget)
        self.explorer_root.setSizes([320, 960])
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.explorer_root)
        self.setCentralWidget(self.main_stack)
        self.list.set_view_mode_name(self.view_combo.currentText())
        self.view_stack.setCurrentWidget(self.details if self.view_combo.currentText() == "details" else self.list)
        self.update_command_buttons()

    def make_icon_button(self, text, callback, standard_icon=None, tooltip=""):
        button = QToolButton()
        button.setText(text)
        if standard_icon is not None:
            button.setIcon(self.style().standardIcon(standard_icon))
            button.setIconSize(QSize(16, 16))
        button.setProperty("compactIcon", True)
        button.setFixedSize(32, 30)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        return button

    def apply_theme(self):
        light = self.settings.get("theme", "dark") == "light"
        self._dark_theme = not light
        if hasattr(self, "list"):
            self.list.set_dark_theme(self._dark_theme)
        if hasattr(self, "details"):
            self.details._dark_theme = self._dark_theme
        colors = {
            "base": "#fffafd" if light else "#17161d",
            "surface": "#ffffff" if light else "#211f29",
            "raised": "#ffffff" if light else "#2b2935",
            "hover": "#dcd4ff" if light else "#363242",
            "border": "#e8deef" if light else "#403c4d",
            "border_strong": "#d8cbe7" if light else "#514b61",
            "text": "#332d42" if light else "#f4f0fb",
            "muted": "#8d819e" if light else "#aaa3b8",
            "accent": "#9c87ee" if light else "#937cda",
            "accent_hover": "#8d77df" if light else "#a18be5",
            "selection": "#dcd4ff" if light else "#7962bd",
            "selection_text": "#231c34" if light else "#ffffff",
            "track": "#f1ebf7" if light else "#292631",
            "scroll": "#c7bad9" if light else "#645c78",
        }
        self.setStyleSheet(f"""
            QMainWindow, QDialog {{ background: {colors['base']}; color: {colors['text']}; }}
            QWidget {{ color: {colors['text']}; font-size: 9pt; }}
            QFrame {{ border: none; }}
            QWidget#explorerHeader {{
                background: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 10px;
            }}
            QLabel#previewPanel {{
                background: {colors['surface']}; color: {colors['muted']};
                border: 1px solid {colors['border']}; border-radius: 9px;
            }}
            QWidget#settingsForm {{ background: {colors['base']}; }}
            QScrollArea QWidget#qt_scrollarea_viewport {{ background: {colors['base']}; }}
            QTabWidget#navigationTabs::pane {{
                background: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 9px;
            }}
            QTreeView, QListWidget, QTableWidget {{
                background: {colors['surface']}; color: {colors['text']};
                border: 1px solid {colors['border']}; border-radius: 9px;
                outline: 0; padding: 2px;
            }}
            QTreeView {{ font-size: 8pt; }}
            QTreeView::item {{ padding: 2px 3px; }}
            QTreeView::item {{
                border: none; padding: 4px; border-radius: 5px;
            }}
            QListWidget::item {{ padding: 4px; }}
            QTableWidget::item {{ padding: 4px; }}
            QTreeView::item:hover, QListWidget::item:hover, QTableWidget::item:hover {{
                background: {colors['hover']};
            }}
            QTreeView::item:selected, QListWidget::item:selected, QTableWidget::item:selected {{
                background: {colors['selection']}; color: {colors['selection_text']};
            }}
            QHeaderView {{ background: transparent; border: none; }}
            QHeaderView::section {{
                background: {colors['raised']}; color: {colors['text']};
                border: none; border-right: 1px solid {colors['border']};
                border-bottom: 1px solid {colors['border']}; padding: 6px 8px;
                font-weight: 600;
            }}
            QLineEdit, QSpinBox {{
                background: {colors['surface']}; color: {colors['text']};
                border: 1px solid {colors['border_strong']}; border-radius: 8px;
                padding: 5px 9px; selection-background-color: {colors['accent']};
            }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {colors['accent']}; }}
            QPushButton, QToolButton, QComboBox {{
                background: {colors['raised']}; color: {colors['text']};
                border: 1px solid {colors['border_strong']}; border-radius: 8px;
                padding: 5px 10px; min-height: 18px;
            }}
            QPushButton:hover, QToolButton:hover, QComboBox:hover {{
                background: {colors['hover']}; border-color: {colors['accent']};
            }}
            QPushButton:pressed, QToolButton:pressed {{ background: {colors['accent']}; color: white; }}
            QPushButton:checked, QToolButton:checked {{
                background: {colors['accent']}; color: white; border-color: {colors['accent']};
            }}
            QPushButton[accent="true"] {{
                background: {colors['accent']}; color: white; border-color: {colors['accent']}; font-weight: 600;
            }}
            QPushButton[accent="true"]:hover {{ background: {colors['accent_hover']}; }}
            QToolButton[compactIcon="true"], QToolButton[selectionToggle="true"] {{
                padding: 3px; border-radius: 8px;
            }}
            QToolButton[selectionToggle="true"] {{ font-weight: 700; font-size: 11pt; }}
            QToolButton[tabClose="true"] {{
                background: transparent; border: none; border-radius: 7px; padding: 0; font-size: 11pt;
            }}
            QToolButton[tabClose="true"]:hover {{ background: {colors['hover']}; color: {colors['accent']}; }}
            QComboBox {{ padding-right: 24px; }}
            QComboBox::drop-down {{ border: none; width: 22px; }}
            QComboBox QAbstractItemView {{
                background: {colors['surface']}; color: {colors['text']};
                border: 1px solid {colors['border']}; border-radius: 8px;
                selection-background-color: {colors['accent']}; padding: 4px;
            }}
            QMenu {{
                background: {colors['surface']}; color: {colors['text']};
                border: 1px solid {colors['border']}; border-radius: 9px; padding: 5px;
            }}
            QMenu::item {{ padding: 6px 26px 6px 10px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {colors['accent']}; color: white; }}
            QMenu::separator {{ height: 1px; background: {colors['border']}; margin: 4px 7px; }}
            QTabWidget::pane {{ border: 1px solid {colors['border']}; border-radius: 9px; top: -1px; }}
            QTabBar::tab {{
                background: transparent; color: {colors['muted']}; border: none;
                padding: 7px 15px; margin: 2px 2px 0 0; border-radius: 8px;
            }}
            QTabBar#folderTabs {{ border: none; background: transparent; qproperty-drawBase: 0; }}
            QTabBar::tab:hover {{ background: {colors['hover']}; color: {colors['text']}; }}
            QTabBar::tab:selected {{
                background: {colors['selection']}; color: {colors['selection_text']}; font-weight: 700;
                border: 1px solid {colors['accent']};
            }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
                background: {colors['scroll']}; border-radius: 4px; min-height: 30px; min-width: 30px;
            }}
            QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: {colors['accent']}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QSplitter::handle {{ background: {colors['border']}; }}
            QSplitter::handle:hover {{ background: {colors['accent']}; }}
            QToolTip {{
                background: {colors['surface']}; color: {colors['text']};
                border: 1px solid {colors['border']}; border-radius: 6px; padding: 5px;
            }}
            QSlider::groove:horizontal {{ height: 5px; background: {colors['track']}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 13px; margin: -5px 0; border-radius: 6px; background: {colors['accent']}; }}
        """)

    def make_menu_button(self, text, entries, detail=""):
        button = QToolButton()
        button.setText(detail or text)
        button.setMinimumWidth(92)
        button.setMinimumHeight(30)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        if entries:
            for label, callback in entries:
                menu.addAction(label, callback)
        else:
            empty = menu.addAction("(none)")
            empty.setEnabled(False)
        button.setMenu(menu)
        return button

    def two_line_button_text(self, title, detail):
        detail = detail or "-"
        return f"{title}\n{detail}"

    def update_command_buttons(self):
        if hasattr(self, "sort_button"):
            self.sort_button.setText(f"Sort  {self.sort_label()}")
        if hasattr(self, "view_button"):
            self.view_button.setText(f"View  {self.view_combo.currentText().title()}")
        if hasattr(self, "select_button"):
            checked = self.all_items_selected()
            self.select_button.setChecked(checked)
            self.select_button.setText("\u2713" if checked else "")
            self.select_button.setText("☑" if checked else "☐")
            self.select_button.setToolTip("Select all")

    def sort_label(self):
        mode = self.settings.get("sort_mode", "name_asc")
        ascending = self.settings.get("sort_ascending", True)
        if mode.endswith("_desc"):
            ascending = False
            mode = mode[:-5]
        elif mode.endswith("_asc"):
            ascending = True
            mode = mode[:-4]
        names = {
            "name": "Name",
            "size": "Size",
            "type": "Type",
            "modified": "Date",
            "properties": "Props",
        }
        arrow = "\u2191" if ascending else "\u2193"
        return f"{names.get(mode, mode.title())} {arrow}"

    def make_view_button(self):
        entries = []
        for mode in ["large", "medium", "small", "list", "details"]:
            entries.append((mode, lambda m=mode: self.view_combo.setCurrentText(m)))
        return self.make_menu_button("View", entries, f"View  {self.view_combo.currentText().title()}")

    def make_sort_button(self):
        entries = [
            ("Filename", lambda: self.set_sort_from_header("name")),
            ("Size (KB)", lambda: self.set_sort_from_header("size")),
            ("Image Type", lambda: self.set_sort_from_header("type")),
            ("Modified Date", lambda: self.set_sort_from_header("modified")),
            ("Image Properties", lambda: self.set_sort_from_header("properties")),
        ]
        return self.make_menu_button("Sort", entries, f"Sort  {self.sort_label()}")

    def select_all_items(self):
        if self.view_combo.currentText() == "details":
            self.details.selectAll()
        else:
            self.list.selectAll()
        self.update_command_buttons()

    def clear_selection(self):
        self.details.clearSelection()
        self.list.clearSelection()
        self.update_command_buttons()

    def all_items_selected(self):
        if self.view_combo.currentText() == "details":
            total = self.details.rowCount()
            return total > 0 and len({idx.row() for idx in self.details.selectedIndexes()}) >= total
        total = self.list.count()
        return total > 0 and len(self.list.selectedItems()) >= total

    def toggle_select_all(self):
        if self.all_items_selected():
            self.clear_selection()
        else:
            self.select_all_items()

    def apply_quick_search(self):
        self.search_timer.start(120)

    def apply_quick_search_now(self):
        self.populate_list()

    def go_home(self):
        self.load_folder(DEFAULT_START_FOLDER)

    def ensure_folder_tab(self):
        if self.tabs:
            return
        path = self.current_folder
        self.tabs.append({"path": path, "display": str(path), "history": [str(path)], "history_index": 0})
        self._loading_tab = True
        try:
            index = self.folder_tabs.addTab(path.name or str(path))
            self.install_tab_close_button(index)
            self.folder_tabs.setCurrentIndex(0)
            self.current_tab = 0
        finally:
            self._loading_tab = False

    def add_folder_tab(self, path=None):
        self.save_current_tab()
        path = Path(path) if path else DEFAULT_START_FOLDER
        if not self.safe_is_dir(path):
            path = DEFAULT_START_FOLDER
        self.tabs.append({"path": path, "display": str(path), "history": [str(path)], "history_index": 0})
        index = self.folder_tabs.addTab(path.name or str(path))
        self.install_tab_close_button(index)
        self.folder_tabs.setCurrentIndex(index)

    def install_tab_close_button(self, index):
        button = QToolButton(self.folder_tabs)
        button.setText("\u00d7")
        button.setProperty("tabClose", True)
        button.setFixedSize(18, 18)
        button.setToolTip("Close tab")
        button.clicked.connect(lambda _checked=False, target=button: self.close_tab_button(target))
        self.folder_tabs.setTabButton(index, QTabBar.RightSide, button)

    def close_tab_button(self, button):
        for index in range(self.folder_tabs.count()):
            if self.folder_tabs.tabButton(index, QTabBar.RightSide) is button:
                self.close_folder_tab(index)
                return

    def save_current_tab(self):
        if 0 <= self.current_tab < len(self.tabs):
            self.tabs[self.current_tab]["path"] = self.current_folder
            self.tabs[self.current_tab]["display"] = self.display_path
            self.tabs[self.current_tab]["history"] = list(self.history)
            self.tabs[self.current_tab]["history_index"] = self.history_index

    def update_current_tab(self):
        if 0 <= self.current_tab < len(self.tabs):
            self.tabs[self.current_tab]["path"] = self.current_folder
            self.tabs[self.current_tab]["display"] = self.display_path
            self.tabs[self.current_tab]["history"] = list(self.history)
            self.tabs[self.current_tab]["history_index"] = self.history_index
            label = Path(self.display_path).name or self.display_path
            self.folder_tabs.setTabText(self.current_tab, label)

    def on_folder_tab_changed(self, index):
        if self._loading_tab or index < 0 or index >= len(self.tabs):
            return
        self.save_current_tab()
        self.current_tab = index
        tab = self.tabs[index]
        self.history = list(tab.get("history", [tab.get("display", str(tab["path"]))]))
        self.history_index = int(tab.get("history_index", len(self.history) - 1))
        self._loading_tab = True
        try:
            self.load_folder(tab["path"], add_history=False, display_path=tab.get("display"), sync_tree=False)
        finally:
            self._loading_tab = False

    def close_folder_tab(self, index):
        if index < 0 or index >= len(self.tabs):
            return
        if len(self.tabs) <= 1:
            return
        self.tabs.pop(index)
        self.folder_tabs.removeTab(index)
        self.current_tab = max(0, min(self.folder_tabs.currentIndex(), len(self.tabs) - 1))
        self.on_folder_tab_changed(self.current_tab)

    def _build_actions(self):
        self.nav_toolbar = QToolBar()
        self.nav_toolbar.setMovable(False)
        self.addToolBar(self.nav_toolbar)
        self.nav_toolbar.hide()

        actions = [
            ("Back", self.go_back),
            ("Forward", self.go_forward),
            ("Up", self.go_up),
            ("Refresh", self.reload_current),
        ]
        for label, callback in actions:
            act = QAction(label, self)
            act.triggered.connect(callback)
            self.nav_toolbar.addAction(act)
        self.nav_toolbar.addSeparator()

        view_menu = QMenu("View", self)
        for mode in ["large", "medium", "small", "list", "details"]:
            view_menu.addAction(mode, lambda checked=False, m=mode: self.view_combo.setCurrentText(m))
        view_button = QPushButton("View")
        view_button.setMenu(view_menu)
        self.nav_toolbar.addWidget(view_button)

        sort_menu = QMenu("Sort", self)
        for key, label in [
            ("name", "Filename"),
            ("size", "Size (KB)"),
            ("type", "Image Type"),
            ("modified", "Modified Date"),
            ("properties", "Image Properties"),
        ]:
            sort_menu.addAction(label, lambda checked=False, k=key: self.set_sort_from_header(k))
        sort_button = QPushButton("Sort")
        sort_button.setMenu(sort_menu)
        self.nav_toolbar.addWidget(sort_button)

        shortcut_map = {
            "open_viewer": self.open_selected_viewer,
            "back": self.go_back,
            "forward": self.go_forward,
            "rename": self.rename_selected,
            "delete": self.handle_delete_shortcut,
        }
        for name, callback in shortcut_map.items():
            for seq in self.settings.get("shortcuts", {}).get(name, []):
                if not seq.startswith("Mouse") and not seq.startswith("Wheel"):
                    shortcut = QShortcut(QKeySequence(seq), self)
                    shortcut.setContext(Qt.ApplicationShortcut)
                    shortcut.activated.connect(callback)
        backspace = QShortcut(QKeySequence(Qt.Key_Backspace), self)
        backspace.setContext(Qt.ApplicationShortcut)
        backspace.activated.connect(self.go_back)
        settings_shortcut = QShortcut(QKeySequence(Qt.Key_F1), self)
        settings_shortcut.setContext(Qt.ApplicationShortcut)
        settings_shortcut.activated.connect(self.open_shortcuts)

    def on_tree_clicked(self, index):
        path = Path(self.tree_model.filePath(index))
        if path.exists():
            self.load_folder(path, sync_tree=False)

    def populate_quick_paths(self):
        self.quick_paths.clear()
        for entry in self.settings.get("quick_paths", []):
            if isinstance(entry, dict):
                label = entry.get("label") or Path(entry.get("path", "")).name or entry.get("path", "")
                path = entry.get("path", "")
            else:
                path = str(entry)
                label = Path(path).name or path
            if not path:
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            item.setIcon(self.icon_provider.icon(QFileInfo(path)))
            self.quick_paths.addItem(item)

    def save_quick_paths(self):
        paths = []
        for row in range(self.quick_paths.count()):
            item = self.quick_paths.item(row)
            paths.append({"label": item.text(), "path": item.data(Qt.UserRole)})
        self.settings["quick_paths"] = paths
        save_settings(self.settings)

    def open_quick_path_item(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.load_folder(path)

    def add_current_quick_path(self):
        self.add_quick_path(str(self.current_folder))

    def add_quick_path(self, path, label=None):
        path = str(path)
        for row in range(self.quick_paths.count()):
            if self.quick_paths.item(row).data(Qt.UserRole) == path:
                return
        item = QListWidgetItem(label or Path(path).name or path)
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        item.setIcon(self.icon_provider.icon(QFileInfo(path)))
        self.quick_paths.addItem(item)
        self.save_quick_paths()

    def add_typed_quick_path(self):
        text, ok = QInputDialog.getText(self, "Add Shortcut", "Path")
        if not ok or not text.strip():
            return
        path = text.strip().strip('"')
        label = Path(path).name or path
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, path)
        item.setToolTip(path)
        item.setIcon(self.icon_provider.icon(QFileInfo(path)))
        self.quick_paths.addItem(item)
        self.save_quick_paths()

    def rename_quick_path(self):
        item = self.quick_paths.currentItem()
        if not item:
            return
        text, ok = QInputDialog.getText(self, "Edit Shortcut Label", "Label", text=item.text())
        if ok and text.strip():
            item.setText(text.strip())
            self.save_quick_paths()

    def remove_quick_path(self):
        row = self.quick_paths.currentRow()
        if row >= 0:
            self.quick_paths.takeItem(row)
            self.save_quick_paths()

    def quick_paths_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_quick_path_item(self.quick_paths.currentItem()) if self.quick_paths.currentItem() else None)
        menu.addSeparator()
        menu.addAction("Add Current Folder", self.add_current_quick_path)
        menu.addAction("Add Path...", self.add_typed_quick_path)
        menu.addAction("Edit Label", self.rename_quick_path)
        menu.addAction("Remove", self.remove_quick_path)
        menu.exec(self.quick_paths.mapToGlobal(pos))

    def safe_is_dir(self, folder):
        try:
            return Path(folder).is_dir()
        except OSError:
            return False

    def folder_signature(self, folder):
        try:
            stat = Path(folder).stat()
            return (int(stat.st_mtime_ns), int(getattr(stat, "st_size", 0)))
        except OSError:
            return (0, 0)

    def _store_folder_snapshot(self, key, snapshot):
        key = str(key)
        self.folder_cache[key] = snapshot
        if key in getattr(self, "archive_sources_by_root", {}):
            return
        limit = 12 if self.performance_policy.low_spec else 32
        while len(self.folder_cache) > limit:
            removable = next(
                (
                    candidate
                    for candidate in self.folder_cache
                    if candidate not in (key, self.current_snapshot_key)
                ),
                None,
            )
            if removable is None:
                break
            self.folder_cache.pop(removable, None)

    def scan_folder_entries(self, folder, cancel_check=None):
        entries = []
        with os.scandir(folder) as iterator:
            for child in iterator:
                if cancel_check is not None and cancel_check():
                    raise InterruptedError
                try:
                    is_dir_entry = child.is_dir(follow_symlinks=False)
                    path = Path(child.path)
                    if not is_dir_entry and not is_media(path) and not is_archive(path):
                        continue
                    stat = child.stat(follow_symlinks=False)
                    entries.append(
                        MediaItem(
                            path=path,
                            is_dir=is_dir_entry,
                            size=0 if is_dir_entry else int(stat.st_size),
                            mtime=float(stat.st_mtime),
                        )
                    )
                except OSError:
                    continue
        return entries

    def cached_folder_entries(self, folder, force=False):
        folder = Path(folder)
        key = os.path.normcase(os.path.abspath(str(folder)))
        signature = self.folder_signature(folder)
        cached = self.folder_cache.get(key)
        if not force and cached is not None and cached.signature == signature:
            return list(cached.entries), key, False
        entries = self.scan_folder_entries(folder)
        self._store_folder_snapshot(key, FolderSnapshot(folder, entries, signature))
        return list(entries), key, True

    def invalidate_folder_cache(self, folder=None):
        if folder is None:
            self.folder_cache.clear()
            return
        key = os.path.normcase(os.path.abspath(str(folder)))
        self.folder_cache.pop(key, None)

    def collect_media_paths(self, folder):
        media_paths = []
        try:
            for child in Path(folder).iterdir():
                if child.is_file() and is_media(child):
                    media_paths.append(str(child))
        except (PermissionError, FileNotFoundError, OSError):
            pass
        return media_paths

    def prepare_startup_media_folder(self):
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.display_path = str(self.current_folder)
        self.path_edit.setText(self.display_path)
        self.watch_current_folder()
        self.pending_tree_path = str(self.current_folder)
        # A direct file open enters the viewer immediately.  QFileSystemModel
        # path resolution is deferred until the explorer is actually visible;
        # doing this behind the viewer caused intermittent cold-start stalls.
        self.tree_sync_timer.stop()
        startup = str(self.startup_media_path)
        snapshot_key = os.path.normcase(os.path.abspath(str(self.current_folder)))
        context_changed = snapshot_key != self.current_snapshot_key
        if context_changed:
            # A direct file-open must atomically invalidate the previous
            # explorer folder.  Otherwise exit_viewer_mode() sees non-empty
            # stale rows and restores them under the new address/tab path.
            self.folder_scan_generation += 1
            for task in list(self.folder_scan_task_refs):
                task.cancel()
            self.folder_scan_pool.clear()
            self.pause_thumbnail_work(cancel_pending=True)
            self.entries = []
            self.entry_by_path = {}
            self.list.clear()
            self.details.clear_entries()
            self.list_item_by_path = {}
            self.detail_item_by_path = {}
            self.view_render_keys["list"] = None
            self.view_render_keys["details"] = None
            self.explorer_render_pending = True
            self.current_snapshot_key = snapshot_key
            self.explorer_dirty = False
            self.media_paths = [startup]
        elif startup not in self.media_paths:
            self.media_paths.insert(0, startup)
        self.startup_media_scan_target = startup
        self.update_current_tab()
        return context_changed

    def start_startup_media_scan(self):
        """Use the one cancellable background folder scan for direct opens."""
        if self.startup_media_path:
            self.populate_list(lightweight=True, force=False, preserve_existing=True)

    def process_startup_media_scan(self):
        # Kept as a no-op for old queued timer events during an in-place update.
        self.startup_media_scan_timer.stop()
        self.startup_media_scan_iter = None

    def apply_startup_media_scan_paths(self, final=False):
        target = self.startup_media_scan_target or (str(self.startup_media_path) if self.startup_media_path else "")
        if not target:
            return
        paths = list(self.startup_media_scan_paths)
        if target not in paths:
            paths.insert(0, target)
        self.apply_media_paths_to_active_viewer(paths, target=target, final=final)

    def apply_media_paths_to_active_viewer(self, paths, target=None, final=False):
        paths = list(dict.fromkeys(str(path) for path in paths if is_media(path)))
        target = str(target or "")
        if target and target not in paths:
            paths.insert(0, target)
        current = target
        previous_item_count = 0
        previous_grid_count = 0
        previous_viewer_paths = []
        if self.viewer and self.viewer.items:
            previous_item_count = len(self.viewer.items)
            previous_viewer_paths = [str(path) for path in self.viewer.items]
            current = str(self.viewer.items[self.viewer.index])
            try:
                previous_grid_count = int(self.viewer.grid.count())
            except (AttributeError, RuntimeError):
                previous_grid_count = 0
        paths_changed = paths != self.media_paths
        self.media_paths = paths
        if not self.viewer:
            return
        self.viewer.items = [Path(path) for path in self.media_paths if is_media(path)]
        if not self.viewer.items:
            return
        current_key = self.normalized_location_path(current) if current else ""
        path_index = {
            self.normalized_location_path(path): index
            for index, path in enumerate(self.media_paths)
        }
        if current_key in path_index:
            self.viewer.index = path_index[current_key]
        else:
            self.viewer.index = min(self.viewer.index, len(self.viewer.items) - 1)
        viewer_paths_changed = previous_viewer_paths != [str(path) for path in self.viewer.items]
        provisional_group_needs_refresh = False
        if final and viewer_paths_changed and previous_item_count <= 1:
            if self.viewer.viewer_mode in ("double", "triple"):
                provisional_group_needs_refresh = len(self.viewer.current_group()) > previous_grid_count
        if final and viewer_paths_changed and (
            self.viewer.viewer_mode in ("webtoon", "webtoon_vertical")
            or provisional_group_needs_refresh
        ):
            self.viewer.show_current(reset=False)
        else:
            title_name = self.viewer.active_display_path.name if self.viewer.active_display_path else self.viewer.items[self.viewer.index].name
            self.viewer.setWindowTitle(f"{APP_NAME} - {self.viewer.index + 1}/{len(self.viewer.items)} - {title_name}")
            self.viewer.update_filename_labels()

    def remove_legacy_thumb_cache(self):
        old_cache = RUN_DIR / ".thumb_cache"
        if old_cache.exists():
            try:
                shutil.rmtree(old_cache)
            except Exception:
                pass

    def load_folder(
        self,
        folder,
        add_history=True,
        display_path=None,
        force=False,
        sync_tree=True,
        navigation=None,
    ):
        if display_path is None or "::" not in str(display_path):
            self.archive_navigation_generation += 1
        self.unc_generation += 1
        for previous_task in list(self.unc_share_task_refs):
            previous_task.cancel()
        self.unc_share_task_refs.clear()
        folder = Path(folder)
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.current_folder = folder
        archive_root_key = self.archive_root_by_path.get(self.normalized_location_path(folder))
        if archive_root_key:
            self.archive_context_last_used[archive_root_key] = time.monotonic()
        self.display_path = display_path or str(folder)
        self.prepare_navigation_position(navigation, folder)
        if add_history:
            self.history = self.history[: self.history_index + 1]
            self.history.append(self.display_path)
            self.history_index = len(self.history) - 1
        if display_path is None:
            self.settings["last_folder"] = str(DEFAULT_START_FOLDER)
        self.schedule_settings_save()
        self.path_edit.setText(self.display_path)
        self.watch_current_folder()
        if sync_tree:
            self.pending_tree_path = str(folder)
            self.tree_sync_timer.start(180)
        else:
            self.tree_sync_timer.stop()
            self.pending_tree_path = ""
        self.populate_list(force=force)
        self.update_current_tab()
        return True

    def prepare_navigation_position(self, navigation, folder=None):
        self.navigation_position_serial += 1
        self.navigation_position_timer.stop()
        self.pending_navigation_position = None
        if not navigation:
            return
        mode = str(navigation.get("mode") or "").lower()
        if mode not in ("top", "anchor"):
            return
        if folder is None and self.virtual_unc_server:
            location_key = f"unc:{self.virtual_unc_server.lower()}"
        else:
            folder = Path(folder if folder is not None else self.current_folder)
            location_key = os.path.normcase(os.path.abspath(str(folder)))
        self.pending_navigation_position = {
            "serial": self.navigation_position_serial,
            "folder_key": location_key,
            "mode": mode,
            "anchor": str(navigation.get("anchor") or ""),
            "deadline": time.monotonic() + 2.5,
            "settle_until": 0.0,
        }
        self.navigation_position_timer.start()

    def reset_explorer_list_position(self):
        self.list.clearSelection()
        self.details.clearSelection()
        self.list.selectionModel().clearCurrentIndex()
        self.details.selectionModel().clearCurrentIndex()
        self.list.scrollToTop()
        self.details.scrollToTop()

    def apply_pending_navigation_position(self):
        state = self.pending_navigation_position
        if not state:
            self.navigation_position_timer.stop()
            return
        current_key = (
            f"unc:{self.virtual_unc_server.lower()}"
            if self.virtual_unc_server
            else os.path.normcase(os.path.abspath(str(self.current_folder)))
        )
        if current_key != state["folder_key"]:
            self.pending_navigation_position = None
            self.navigation_position_timer.stop()
            return

        now = time.monotonic()
        mode = state["mode"]
        applied = False
        if mode == "top":
            self.reset_explorer_list_position()
            applied = True
        else:
            anchor = state["anchor"]
            if self.view_combo.currentText() == "details":
                item = self.detail_item_by_path.get(anchor)
                if item is not None:
                    self.details.selectRow(item.row())
                    self.details.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                    applied = True
            else:
                item = self.list_item_by_path.get(anchor)
                if item is not None:
                    self.list.setCurrentItem(item)
                    self.list.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                    applied = True

        if applied:
            if not state["settle_until"]:
                state["settle_until"] = now + 0.55
            if now >= state["settle_until"]:
                self.pending_navigation_position = None
                self.navigation_position_timer.stop()
            return

        if now >= state["deadline"]:
            self.reset_explorer_list_position()
            self.pending_navigation_position = None
            self.navigation_position_timer.stop()

    def sync_tree_selection(self):
        path = self.pending_tree_path
        if not path or path != str(self.current_folder):
            return
        if self.viewer is not None and self.main_stack.currentWidget() is self.viewer:
            return
        current = self.tree.currentIndex()
        if current.isValid() and os.path.normcase(self.tree_model.filePath(current)) == os.path.normcase(path):
            return
        vertical = self.tree.verticalScrollBar().value()
        horizontal = self.tree.horizontalScrollBar().value()
        index = self.tree_model.index(path)
        if index.isValid():
            self.tree.setUpdatesEnabled(False)
            self.tree.setCurrentIndex(index)
            self.tree.setUpdatesEnabled(True)
            self.tree.verticalScrollBar().setValue(vertical)
            self.tree.horizontalScrollBar().setValue(horizontal)

    def populate_list(self, lightweight=True, force=False, preserve_existing=False):
        if self.closing:
            return
        self.pause_thumbnail_work(cancel_pending=True)
        if not preserve_existing:
            self.list.clear()
            self.details.clear_entries()
            self.list_item_by_path = {}
            self.detail_item_by_path = {}
            self.view_render_keys["list"] = None
            self.view_render_keys["details"] = None
        if self.virtual_unc_server:
            self.folder_scan_generation += 1
            for previous_task in list(self.folder_scan_task_refs):
                previous_task.cancel()
            self.folder_scan_pool.clear()
            entries = [MediaItem(path, True, label) for label, path in self.virtual_entries]
            self.entries = entries
            self.media_paths = []
            self.render_entries(entries, lightweight=lightweight)
            return
        folder = Path(self.current_folder)
        snapshot_key = os.path.normcase(os.path.abspath(str(folder)))
        self.current_snapshot_key = snapshot_key
        cached = self.folder_cache.get(snapshot_key)
        if not force and cached is not None:
            self.apply_folder_entries(list(cached.entries), snapshot_key, lightweight=lightweight)
            return
        else:
            signature = (0, 0)
        self.folder_scan_generation += 1
        generation = self.folder_scan_generation
        for previous_task in list(self.folder_scan_task_refs):
            previous_task.cancel()
        self.folder_scan_pool.clear()
        if not preserve_existing:
            self.entries = []
            self.media_paths = []
            self.render_entries([], lightweight=False)
        task = FolderScanTask(generation, folder, signature, self.scan_folder_entries)
        self.folder_scan_task_refs.add(task)
        task.signals.finished.connect(
            lambda result_generation, result_folder, entries, result, ref=task, use_lightweight=lightweight: self.folder_scan_ready(
                result_generation, result_folder, entries, result, ref, use_lightweight
            )
        )
        self.folder_scan_pool.start(task, 10)

    def folder_scan_ready(self, generation, folder, entries, result, task, lightweight=True):
        self.folder_scan_task_refs.discard(task)
        if self.closing:
            return
        if generation != self.folder_scan_generation or Path(folder) != Path(self.current_folder):
            return
        if result.get("cancelled"):
            return
        if result.get("error") or entries is None:
            QMessageBox.warning(self, "Folder error", f"Cannot read folder:\n{folder}\n\n{result.get('error', '')}")
            return
        snapshot_key = os.path.normcase(os.path.abspath(str(folder)))
        signature = tuple(result.get("signature_after") or self.folder_signature(folder))
        self._store_folder_snapshot(
            snapshot_key,
            FolderSnapshot(Path(folder), list(entries), signature),
        )
        self.apply_folder_entries(list(entries), snapshot_key, lightweight=lightweight)

    def schedule_vlc_prewarm(self, entries=None):
        """Start cold libVLC plugin scanning while the explorer is visible."""
        if (
            vlc is None
            or self.closing
            or self.vlc_prewarm_inflight
            or self.vlc_prewarm_instance is not None
            or (self.viewer is not None and self.main_stack.currentWidget() is self.viewer)
        ):
            return
        entries = self.entries if entries is None else entries
        if not any(not entry.is_dir and is_video(entry.path) for entry in entries):
            return
        self.vlc_prewarm_inflight = True
        task = VlcInitTask(vlc)
        self.vlc_prewarm_task = task
        task.signals.finished.connect(self._vlc_prewarm_finished, Qt.QueuedConnection)
        self.vlc_prewarm_thread = threading.Thread(
            target=task.run,
            name="PhotoViewer-VLC-Prewarm",
            daemon=True,
        )
        self.vlc_prewarm_thread.start()

    def _vlc_prewarm_finished(self, instance, bundles, error, task):
        if task is not self.vlc_prewarm_task:
            return
        self.vlc_prewarm_inflight = False
        self.vlc_prewarm_task = None
        if self.closing or error or instance is None:
            for _player_instance, player in list(bundles or []):
                try:
                    player.release()
                except Exception:
                    pass
            try:
                if instance is not None:
                    instance.release()
            except Exception:
                pass
            return
        viewer = self.viewer
        viewer_active = viewer is not None and self.main_stack.currentWidget() is viewer
        if not viewer_active:
            self.vlc_prewarm_instance = instance
            self.vlc_prewarm_bundles = list(bundles or [])
            return
        viewer.vlc_instance = instance
        viewer.vlc_init_inflight = False
        viewer.vlc_init_error = ""
        players = [player for _player_instance, player in bundles or []]
        for player_instance, player in bundles or []:
            viewer.video_player_instances[id(player)] = player_instance
            viewer._configure_media_player(player)
        viewer.video_standby_players.extend(players)
        viewer._dispatch_pending_video_requests()

    def apply_folder_entries(self, entries, snapshot_key, lightweight=True):
        self.current_snapshot_key = snapshot_key
        self.explorer_dirty = False
        query = self.quick_search.text().strip().lower() if hasattr(self, "quick_search") else ""
        if query:
            entries = [entry for entry in entries if query in entry.path.name.lower()]

        sort_mode = self.settings.get("sort_mode", "name")
        ascending = self.settings.get("sort_ascending", True)
        entries = self.sorted_entries(entries, sort_mode, ascending)
        self.entries = entries
        self.entry_by_path = {str(entry.path): entry for entry in entries}
        self.media_paths = [str(e.path) for e in entries if not e.is_dir and is_media(e.path)]
        self.schedule_vlc_prewarm(entries)
        viewer_active = self.viewer is not None and self.main_stack.currentWidget() is self.viewer
        if viewer_active:
            # Do not build thousands of hidden QList/QTable widgets behind an
            # active viewer.  The cache and sibling media list are complete;
            # one render is performed only when returning to the explorer.
            self.explorer_render_pending = True
        else:
            self.render_entries(entries, lightweight=lightweight)
            self.explorer_render_pending = False
        if (
            self.viewer is not None
            and self.main_stack.currentWidget() is self.viewer
            and self.startup_media_path is not None
            and Path(self.startup_media_path).parent == Path(self.current_folder)
        ):
            self.apply_media_paths_to_active_viewer(
                self.media_paths,
                target=str(self.startup_media_path),
                final=True,
            )

    def render_entries(self, entries=None, lightweight=True, preserve_scroll=False):
        entries = list(self.entries if entries is None else entries)
        self._list_render_token += 1
        render_token = self._list_render_token
        self._list_render_entries = []
        self._list_render_index = 0
        self.entry_by_path = {str(entry.path): entry for entry in entries}
        view_name = "details" if self.view_combo.currentText() == "details" else "list"
        render_key = self.current_render_key(entries)
        list_scroll = self.list.verticalScrollBar().value() if preserve_scroll else 0
        details_scroll = self.details.verticalScrollBar().value() if preserve_scroll else 0
        if self.view_render_keys.get(view_name) == render_key:
            self.update_command_buttons()
            if lightweight:
                self.thumbnail_paused = False
                self.start_thumbnail_loading()
            return
        self.list.setUpdatesEnabled(False)
        self.details.setUpdatesEnabled(False)
        if view_name == "details":
            self.details.clear_entries()
            self.detail_item_by_path = {}
            self.details.load_entries(
                entries,
                self.icon_provider,
                lambda entry: self.entry_icon(entry, lightweight=lightweight),
                lightweight=lightweight,
                row_ready=lambda entry, item: self.detail_item_by_path.__setitem__(str(entry.path), item),
            )
        else:
            self.list.clear()
            self.list_item_by_path = {}
            if len(entries) > 1500:
                # Keep the first paint bounded for very large folders.  Rows
                # are appended in short event-loop slices so the window can
                # still receive input and thumbnails can prioritize visible
                # rows while the remainder is built.
                self._list_render_entries = entries
                self._list_render_index = 0
                self._list_render_token = render_token
                self._list_render_lightweight = lightweight
                self._list_render_key = render_key
                self._list_render_scroll = list_scroll
                self.view_render_keys[view_name] = None
                self.list.setUpdatesEnabled(True)
                self.details.setUpdatesEnabled(True)
                self._append_list_render_chunk(render_token)
                return
            for entry in entries:
                self._append_list_item(entry, lightweight)
        self.view_render_keys[view_name] = render_key
        self.list.setUpdatesEnabled(True)
        self.details.setUpdatesEnabled(True)
        if preserve_scroll:
            self.list.verticalScrollBar().setValue(list_scroll)
            self.details.verticalScrollBar().setValue(details_scroll)
        else:
            # Clearing and immediately repopulating a cached folder can leave
            # Qt's old numeric scrollbar value alive.  Force a deterministic
            # baseline; navigation-specific positioning is applied afterward.
            self.reset_explorer_list_position()
        self.update_command_buttons()
        if lightweight:
            self.thumbnail_paused = False
            self.start_thumbnail_loading()

    def _append_list_item(self, entry, lightweight=True):
        item = QListWidgetItem(entry.display_name)
        item.setData(Qt.UserRole, str(entry.path))
        item.setToolTip(str(entry.path))
        item.setIcon(self.entry_icon(entry, lightweight=lightweight))
        color = (
            type_color(entry.path, entry.is_dir, dark_theme=self._dark_theme)
            if self.list.viewMode() == QListWidget.ListMode
            else None
        )
        if color is not None:
            item.setBackground(color)
        self.list.addItem(item)
        self.list_item_by_path[str(entry.path)] = item

    def _append_list_render_chunk(self, token=None):
        token = self._list_render_token if token is None else int(token)
        if token != self._list_render_token or self.closing:
            return
        entries = self._list_render_entries
        if not entries:
            self.view_render_keys["list"] = self._list_render_key
            return
        start = self._list_render_index
        end = min(len(entries), start + 256)
        self.list.setUpdatesEnabled(False)
        for entry in entries[start:end]:
            self._append_list_item(entry, self._list_render_lightweight)
        self._list_render_index = end
        self.list.setUpdatesEnabled(True)
        if end < len(entries):
            QTimer.singleShot(0, lambda current=token: self._append_list_render_chunk(current))
            return
        self.view_render_keys["list"] = self._list_render_key
        self.list.verticalScrollBar().setValue(self._list_render_scroll)
        self.update_command_buttons()
        if self._list_render_lightweight:
            self.thumbnail_paused = False
            self.start_thumbnail_loading()

    def entry_icon(self, entry, lightweight=True):
        path = str(entry.path)
        cached = self.thumbnail_cache.get(path)
        if cached is not None and self.thumbnail_cache_meta.get(path) == (entry.size, entry.mtime):
            return cached
        if lightweight:
            if entry.is_dir:
                return self.icon_provider.icon(QFileInfo(path))
            if self.generic_media_icon is None:
                self.generic_media_icon = self.style().standardIcon(QStyle.SP_FileIcon)
            return self.generic_media_icon
        return self.make_icon(entry)

    def apply_performance_profile(self):
        name = self.settings.get("performance_profile", "balanced")
        if name not in PERFORMANCE_PROFILES:
            name = "balanced"
            self.settings["performance_profile"] = name
        profile = PERFORMANCE_PROFILES[name]
        self.performance_policy = performance_policy_for(self.settings)
        self.performance_profile = dict(profile)
        self.thumbnail_start_ms = int(profile["thumbnail_start_ms"])
        self.thumbnail_gap_ms = int(profile["thumbnail_gap_ms"])
        self.thumbnail_pool.setMaxThreadCount(int(self.performance_policy.thumbnail_workers))
        self.thumbnail_pool.setThreadPriority(QThread.IdlePriority)
        if self.viewer is not None:
            self.viewer.apply_performance_policy(self.performance_policy)
        if hasattr(self, "thumbnail_timer") and self.thumbnail_timer.isActive():
            self.thumbnail_timer.stop()
            if self.thumbnail_queue and not self.thumbnail_paused:
                self.thumbnail_timer.start(self.performance_policy.thumbnail_gap_ms)

    def schedule_settings_save(self):
        self.settings_save_timer.start()

    def current_render_key(self, entries=None):
        entries = self.entries if entries is None else entries
        folder_key = self.current_snapshot_key or os.path.normcase(os.path.abspath(str(self.current_folder)))
        return (
            folder_key,
            self.settings.get("theme", "dark"),
            tuple((str(entry.path), int(entry.size), float(entry.mtime)) for entry in entries),
        )

    def start_thumbnail_loading(self):
        if self.thumbnail_paused:
            return
        self.thumbnail_idle_cursor = 0
        self.thumbnail_cycle_started = False
        QTimer.singleShot(0, self.prioritize_visible_thumbnails)

    def pause_thumbnail_work(self, cancel_pending=False):
        self.thumbnail_timer.stop()
        if hasattr(self, "thumbnail_resume_timer"):
            self.thumbnail_resume_timer.stop()
        self.thumbnail_paused = True
        if cancel_pending:
            self.thumbnail_generation += 1
            for task in list(self.thumbnail_task_refs):
                task.cancel()
            self.thumbnail_pool.clear()
            self.thumbnail_inflight.clear()
            self.thumbnail_queue = deque()
            self.thumbnail_queue_set.clear()
            self.thumbnail_cycle_started = False

    def queue_thumbnail(self, path, priority=0):
        if self.thumbnail_paused:
            return False
        path = str(path)
        entry = self.entry_by_path.get(path)
        if entry is None or entry.is_dir or is_archive(entry.path) or not is_media(entry.path):
            return False
        if self.thumbnail_cache_meta.get(path) == (entry.size, entry.mtime) and path in self.thumbnail_cache:
            self.apply_thumbnail_icon(path, self.thumbnail_cache[path])
            return False
        if path in self.thumbnail_inflight:
            return False
        task = ImageDecodeTask(
            self.thumbnail_generation,
            path,
            (192, 192),
            canvas_size=(192, 192),
            video_shell=is_video(entry.path),
            thread_priority=QThread.IdlePriority,
            archive_source=self.archive_source_for_path(path),
        )
        self.thumbnail_inflight.add(path)
        self.thumbnail_task_refs.add(task)
        task.signals.finished.connect(
            lambda generation, result_path, payload, metadata, ref=task: self.thumbnail_ready(
                generation, result_path, payload, metadata, ref
            )
        )
        self.thumbnail_pool.start(task, int(priority))
        return True

    def prioritize_visible_thumbnails(self):
        if self.thumbnail_paused or not hasattr(self, "entries"):
            return
        visible = self.visible_paths()
        if not visible:
            visible = [str(entry.path) for entry in self.entries[:24]]
        media_order = [str(entry.path) for entry in self.entries if not entry.is_dir and is_media(entry.path)]
        priority_paths = list(dict.fromkeys(str(path) for path in visible))
        position_map = {path: index for index, path in enumerate(media_order)}
        positions = [position_map[path] for path in priority_paths if path in position_map]
        if positions:
            span = max(12, len(priority_paths) * 2)
            start = max(0, min(positions) - len(priority_paths))
            end = min(len(media_order), max(positions) + span + 1)
            priority_paths.extend(path for path in media_order[start:end] if path not in priority_paths)
        archive_context = self.current_snapshot_key in self.archive_sources_by_root
        if archive_context:
            # A remote archive must remain demand-driven.  Loading all members
            # in the idle tail would silently download the complete ZIP.
            ordered = list(dict.fromkeys(priority_paths + list(self.thumbnail_queue)))
        else:
            ordered = list(dict.fromkeys(priority_paths + list(self.thumbnail_queue) + media_order))
        self.thumbnail_queue = deque(
            path
            for path in ordered
            if path not in self.thumbnail_inflight
            and (
                path not in self.thumbnail_cache
                or self.thumbnail_cache_meta.get(path)
                != (
                    self.entry_by_path.get(path).size if self.entry_by_path.get(path) else -1,
                    self.entry_by_path.get(path).mtime if self.entry_by_path.get(path) else -1,
                )
            )
        )
        self.thumbnail_queue_set = set(self.thumbnail_queue)
        if self.thumbnail_queue and not self.thumbnail_timer.isActive():
            delay = self.thumbnail_gap_ms if self.thumbnail_cycle_started else self.thumbnail_start_ms
            self.thumbnail_timer.start(delay)

    def visible_paths(self):
        paths = []
        if self.view_combo.currentText() == "details":
            viewport = self.details.viewport()
            top = self.details.rowAt(0)
            bottom = self.details.rowAt(max(0, viewport.height() - 1))
            if top < 0:
                top = 0
            if bottom < 0:
                bottom = min(self.details.rowCount() - 1, top + 40)
            for row in range(top, min(self.details.rowCount(), bottom + 1)):
                item = self.details.item(row, 0)
                if item:
                    paths.append(item.data(Qt.UserRole))
        else:
            rect = self.list.viewport().rect()
            top_index = self.list.indexAt(rect.topLeft())
            bottom_index = self.list.indexAt(rect.bottomRight())
            top = top_index.row() if top_index.isValid() else 0
            bottom = bottom_index.row() if bottom_index.isValid() else min(self.list.count() - 1, top + 40)
            if bottom < top:
                bottom = min(self.list.count() - 1, top + 40)
            for row in range(max(0, top), min(self.list.count(), bottom + 1)):
                item = self.list.item(row)
                if item:
                    paths.append(item.data(Qt.UserRole))
        return paths

    def process_next_thumbnail(self):
        self.prioritize_visible_thumbnails()

    def queue_idle_thumbnail(self):
        if self.thumbnail_paused or not self.entries:
            return
        if len(self.thumbnail_inflight) >= max(1, self.thumbnail_pool.maxThreadCount()):
            self.thumbnail_timer.start(self.thumbnail_gap_ms)
            return
        while self.thumbnail_queue:
            if hasattr(self.thumbnail_queue, "popleft"):
                path = self.thumbnail_queue.popleft()
            else:
                path = self.thumbnail_queue.pop(0)
            self.thumbnail_queue_set.discard(path)
            if self.queue_thumbnail(path, priority=0):
                self.thumbnail_cycle_started = True
                break
        if self.thumbnail_queue:
            self.thumbnail_timer.start(self.thumbnail_gap_ms)

    def thumbnail_ready(self, generation, path, payload, metadata, task):
        self.thumbnail_task_refs.discard(task)
        if self.closing:
            return
        if generation != self.thumbnail_generation:
            return
        self.thumbnail_inflight.discard(path)
        entry = self.entry_by_path.get(path)
        if entry is None:
            return
        if metadata.get("image_size"):
            entry.image_size = tuple(metadata["image_size"])
        pixmap = QPixmap()
        if isinstance(payload, QImage):
            pixmap = QPixmap.fromImage(payload)
        elif isinstance(payload, (bytes, bytearray)):
            pixmap.loadFromData(bytes(payload), "PNG")
        if pixmap.isNull():
            icon = self.generic_media_icon or self.style().standardIcon(QStyle.SP_FileIcon)
        else:
            icon = QIcon(pixmap)
        self.thumbnail_cache[path] = icon
        self.thumbnail_cache_meta[path] = (entry.size, entry.mtime)
        previous_cost = self.thumbnail_cache_cost.get(path, 0)
        self.thumbnail_cache_bytes = max(0, self.thumbnail_cache_bytes - previous_cost)
        icon_cost = 192 * 192 * 4
        self.thumbnail_cache_cost[path] = icon_cost
        self.thumbnail_cache_bytes += icon_cost
        if path in self.thumbnail_cache_order:
            self.thumbnail_cache_order.remove(path)
        self.thumbnail_cache_order.append(path)
        while self.thumbnail_cache_order and (
            len(self.thumbnail_cache_order) > 1024
            or self.thumbnail_cache_bytes > self.performance_policy.thumbnail_cache_limit_bytes
        ):
            old = self.thumbnail_cache_order.pop(0)
            self.thumbnail_cache.pop(old, None)
            self.thumbnail_cache_meta.pop(old, None)
            self.thumbnail_cache_bytes = max(
                0,
                self.thumbnail_cache_bytes - self.thumbnail_cache_cost.pop(old, 0),
            )
        self.apply_thumbnail_icon(path, icon)
        if self.thumbnail_queue and not self.thumbnail_timer.isActive() and not self.thumbnail_paused:
            self.thumbnail_timer.start(self.thumbnail_gap_ms)

    def apply_thumbnail_icon(self, path, icon):
        path = str(path)
        item = getattr(self, "list_item_by_path", {}).get(path)
        if item is not None:
            try:
                item.setIcon(icon)
            except RuntimeError:
                self.list_item_by_path.pop(path, None)
        item = getattr(self, "detail_item_by_path", {}).get(path)
        if item is not None:
            try:
                item.setIcon(icon)
                entry = self.entry_by_path.get(path)
                if entry is not None and entry.image_size:
                    properties_item = self.details.item(item.row(), 4)
                    if properties_item is not None:
                        properties_item.setText(f"{entry.image_size[0]}x{entry.image_size[1]}")
                        properties_item.setData(Qt.UserRole + 1, entry.image_size)
            except RuntimeError:
                self.detail_item_by_path.pop(path, None)

    def make_thumbnail_icon(self, entry):
        if entry.is_dir:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))
        if is_video(entry.path):
            return self.make_icon(entry)
        try:
            with Image.open(entry.path) as img:
                if getattr(img, "is_animated", False):
                    img.seek(0)
                img = img.convert("RGBA")
                img.thumbnail((192, 192))
                canvas = Image.new("RGBA", (192, 192), (0, 0, 0, 255))
                canvas.alpha_composite(img, ((192 - img.width) // 2, (192 - img.height) // 2))
                data = BytesIO()
                canvas.save(data, format="PNG")
                pix = QPixmap()
                pix.loadFromData(data.getvalue(), "PNG")
                return QIcon(pix)
        except Exception:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))

    def sorted_entries(self, entries, sort_mode, ascending):
        def key_name(item):
            return natural_sort_key(item.display_name)

        if sort_mode.endswith("_desc"):
            ascending = False
        elif sort_mode.endswith("_asc"):
            ascending = True
        key_map = {
            "name": key_name,
            "name_asc": key_name,
            "name_desc": key_name,
            "size": lambda x: 0 if x.is_dir else x.size,
            "size_asc": lambda x: 0 if x.is_dir else x.size,
            "size_desc": lambda x: 0 if x.is_dir else x.size,
            "type": lambda x: (
                x.kind,
                x.path.suffix.lower(),
                natural_sort_key(x.display_name),
            ),
            "modified": lambda x: x.mtime,
            "date_desc": lambda x: x.mtime,
            "date_asc": lambda x: x.mtime,
            "properties": lambda x: x.image_size or (0, 0),
        }
        entries.sort(key=key_map.get(sort_mode, key_name), reverse=not ascending)
        entries.sort(key=lambda x: not x.is_dir)
        return entries

    def set_sort_from_header(self, key, ascending=None):
        self.pause_thumbnail_work(cancel_pending=True)
        current_key = self.settings.get("sort_mode", "name")
        if current_key.endswith("_desc"):
            current_key = current_key[:-5]
        elif current_key.endswith("_asc"):
            current_key = current_key[:-4]
        current_ascending = self.settings.get("sort_ascending", True)
        if ascending is None:
            ascending = not current_ascending if current_key == key else True
        self.settings["sort_mode"] = key
        self.settings["sort_ascending"] = ascending
        self.schedule_settings_save()
        self.update_command_buttons()
        try:
            self.entries = self.sorted_entries(list(self.entries), key, ascending)
            self.media_paths = [str(entry.path) for entry in self.entries if not entry.is_dir and is_media(entry.path)]
            self.reorder_rendered_entries(key, ascending)
        finally:
            self.thumbnail_paused = False
            self.start_thumbnail_loading()

    def reorder_rendered_entries(self, sort_key, ascending):
        if self.view_combo.currentText() == "details":
            column_map = {
                "name": 0,
                "size": 1,
                "type": 2,
                "modified": 3,
                "properties": 4,
            }
            self.details.setSortingEnabled(True)
            self.details.sortItems(column_map.get(sort_key, 0), Qt.AscendingOrder if ascending else Qt.DescendingOrder)
            self.details.setSortingEnabled(False)
            self.detail_item_by_path = {}
            for row in range(self.details.rowCount()):
                item = self.details.item(row, 0)
                if item:
                    self.detail_item_by_path[str(item.data(Qt.UserRole))] = item
            self.prioritize_visible_thumbnails()
            self.view_render_keys["details"] = self.current_render_key(self.entries)
            return
        if self.view_combo.currentText() != "details":
            current_path = ""
            if self.list.currentItem():
                current_path = str(self.list.currentItem().data(Qt.UserRole))
            item_map = {}
            while self.list.count():
                item = self.list.takeItem(0)
                item_map[str(item.data(Qt.UserRole))] = item
            for entry in self.entries:
                item = item_map.get(str(entry.path))
                if item is not None:
                    self.list.addItem(item)
            self.list_item_by_path = item_map
            if current_path in item_map:
                self.list.setCurrentItem(item_map[current_path])
            self.prioritize_visible_thumbnails()
            self.view_render_keys["list"] = self.current_render_key(self.entries)
            return
        self.render_entries(self.entries, lightweight=True, preserve_scroll=True)

    def make_icon(self, entry):
        if entry.is_dir:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))
        if is_video(entry.path):
            pix = windows_shell_thumbnail(entry.path, 192)
            if pix is not None and not pix.isNull():
                canvas = QPixmap(192, 192)
                canvas.fill(QColor("#050505"))
                painter = QPainter(canvas)
                scaled = pix.scaled(192, 192, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap((192 - scaled.width()) // 2, (192 - scaled.height()) // 2, scaled)
                painter.end()
                return QIcon(canvas)
            return self.style().standardIcon(QStyle.SP_MediaPlay)
        if entry.path.suffix.lower() == ".gif":
            return self.icon_provider.icon(QFileInfo(str(entry.path)))
        try:
            with Image.open(entry.path) as img:
                img = img.convert("RGBA")
                img.thumbnail((192, 192))
                canvas = Image.new("RGBA", (192, 192), (0, 0, 0, 255))
                canvas.alpha_composite(img, ((192 - img.width) // 2, (192 - img.height) // 2))
                data = BytesIO()
                canvas.save(data, format="PNG")
                pix = QPixmap()
                pix.loadFromData(data.getvalue(), "PNG")
                return QIcon(pix)
        except Exception:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))

    def change_view_mode(self, mode):
        if self.view_combo.currentText() != mode:
            self.view_combo.blockSignals(True)
            self.view_combo.setCurrentText(mode)
            self.view_combo.blockSignals(False)
        self.settings["view_mode"] = mode
        self.schedule_settings_save()
        self.list.set_view_mode_name(mode)
        self.view_stack.setCurrentWidget(self.details if mode == "details" else self.list)
        self.update_command_buttons()
        self.render_entries(self.entries, lightweight=True, preserve_scroll=True)

    def reload_current(self):
        self.invalidate_folder_cache(self.current_folder)
        self.populate_list(force=True)

    def watch_current_folder(self):
        try:
            folder_text = str(self.current_folder)
            archive_virtual = self.normalized_location_path(self.current_folder) in self.archive_sources_by_root
            watchable = (
                not self.virtual_unc_server
                and not archive_virtual
                and not folder_text.startswith("\\\\")
                and self.safe_is_dir(self.current_folder)
            )
            target = folder_text if watchable else ""
            if target == self.watched_folder_path:
                return
            watched = self.folder_watcher.directories()
            if watched:
                self.folder_watcher.removePaths(watched)
            if target:
                self.folder_watcher.addPath(target)
            self.watched_folder_path = target
        except Exception:
            pass

    def on_watched_folder_changed(self, path):
        if Path(path) == self.current_folder:
            self.explorer_dirty = True
            self.invalidate_folder_cache(path)
            self.refresh_timer.start(250)

    def reload_current_if_available(self):
        if self.safe_is_dir(self.current_folder):
            self.populate_list(force=True)
            self.watch_current_folder()

    def go_to_typed_path(self):
        text = self.path_edit.text().strip().strip('"')
        if text:
            self.open_location(text)

    def open_location(self, text, add_history=True, navigation=None):
        text = str(text).strip().strip('"')
        if not text:
            return False
        server = unc_server_name(text)
        if server:
            return self.load_unc_server(server, add_history=add_history, navigation=navigation)
        if "::" in str(text):
            archive_text, inner_text = str(text).split("::", 1)
            archive = Path(archive_text)
            inner_parts = [part for part in inner_text.replace("\\", "/").split("/") if part and part != "."]
            if inner_parts:
                for root_key, root_archive in list(self.archive_sources_by_root.items()):
                    if os.path.normcase(os.path.abspath(str(root_archive))) != os.path.normcase(os.path.abspath(str(archive))):
                        continue
                    root = Path(root_key)
                    candidate = root.joinpath(*inner_parts)
                    candidate_key = self.normalized_location_path(candidate)
                    if candidate_key in self.archive_sources_by_root:
                        relative_text = "/".join(inner_parts)
                        display = f"{archive}::{relative_text}"
                        return self.load_folder(
                            candidate,
                            add_history=add_history,
                            display_path=display,
                            force=False,
                            sync_tree=False,
                            navigation=navigation,
                        )
            return self.open_archive(archive, add_history=add_history, navigation=navigation)
        path = Path(text)
        if path.is_file() and is_archive(path):
            return self.open_archive(path, add_history=add_history, navigation=navigation)
        return self.load_folder(path, add_history=add_history, navigation=navigation)

    def load_unc_server(self, server, add_history=True, navigation=None):
        display = f"\\\\{server}"
        self.archive_navigation_generation += 1
        self.unc_generation += 1
        generation = self.unc_generation
        for previous_task in list(self.unc_share_task_refs):
            previous_task.cancel()
        for previous_task in list(self.folder_scan_task_refs):
            previous_task.cancel()
        self.folder_scan_pool.clear()
        self.virtual_unc_server = server
        self.virtual_entries = []
        self.current_folder = Path(display)
        self.display_path = display
        self.prepare_navigation_position(navigation)
        self.path_edit.setText(display)
        if add_history:
            self.history = self.history[: self.history_index + 1]
            self.history.append(display)
            self.history_index = len(self.history) - 1
        self.populate_list()
        self.update_current_tab()
        task = UncShareTask(generation, server)
        self.unc_share_task_refs.add(task)
        task.signals.finished.connect(self.unc_share_ready, Qt.QueuedConnection)
        self.folder_scan_pool.start(task, 10)
        return True

    def unc_share_ready(self, generation, server, shares, result):
        # Ignore a slow NetShareEnum reply after the user has navigated away
        # or requested another server.
        for task in list(self.unc_share_task_refs):
            if getattr(task, "generation", None) == int(generation) and getattr(task, "server", None) == str(server):
                self.unc_share_task_refs.discard(task)
        if (
            self.closing
            or int(generation) != int(self.unc_generation)
            or str(server) != str(self.virtual_unc_server)
        ):
            return
        if result.get("cancelled"):
            return
        display = f"\\\\{server}"
        if result.get("error") or not shares:
            QMessageBox.warning(
                self,
                "Invalid path",
                f"Cannot open SMB path or no shared folders were found:\n{display}",
            )
            return
        self.virtual_entries = list(shares)
        self.populate_list()
        self.update_current_tab()

    def open_path(self, path):
        p = Path(path)
        if p.is_dir():
            key = self.normalized_location_path(p)
            archive_path = self.archive_sources_by_root.get(key)
            if archive_path is not None:
                root_key = self.archive_root_by_path.get(key, key)
                root = Path(root_key)
                relative = p.relative_to(root).as_posix() if p != root else ""
                display = f"{archive_path}::{relative}" if relative else f"{archive_path}::"
                self.load_folder(p, display_path=display, sync_tree=False)
            else:
                self.load_folder(p)
        elif is_archive(p):
            self.open_archive(p)
        elif is_media(p):
            self.open_viewer_for(p)

    def open_startup_media(self):
        if self.startup_media_path and self.startup_media_path.exists():
            if self.open_viewer_for(self.startup_media_path):
                QTimer.singleShot(0, self.start_startup_media_scan)
                self.schedule_external_activation()

    def activate_from_external_request(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            foreground = int(user32.GetForegroundWindow() or 0)
            target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
            foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None) or 0) if foreground else 0
            attached = bool(
                target_thread
                and foreground_thread
                and target_thread != foreground_thread
                and user32.AttachThreadInput(target_thread, foreground_thread, True)
            )
            try:
                # SW_SHOW preserves the current fullscreen/windowed state.
                user32.ShowWindow(hwnd, 5)
                user32.BringWindowToTop(hwnd)
                # Lift above the current owner even when Windows rejects the
                # first focus request, then immediately remove TOPMOST so this
                # never becomes a persistent always-on-top window.
                position_flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, position_flags)
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, position_flags)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(target_thread, foreground_thread, False)
        except Exception:
            # Qt activation above remains the cross-version fallback.
            pass

    def schedule_external_activation(self):
        # Window-state changes and native media surfaces can finish one event
        # turn later, so repeat the user-requested activation after settling.
        self.activate_from_external_request()
        QTimer.singleShot(0, self.activate_from_external_request)
        QTimer.singleShot(120, self.activate_from_external_request)

    def open_external_request(self, path_text=None):
        self.schedule_external_activation()
        if not path_text:
            return
        path_text = str(path_text).strip().strip('"')
        if not path_text:
            return
        if unc_server_name(path_text):
            if self.viewer:
                self.exit_viewer_mode(refresh=False)
            self.open_location(path_text)
            return
        path = Path(path_text)
        direct_media_open = path.is_file() and is_media(path)
        if self.viewer:
            self.exit_viewer_mode(refresh=not direct_media_open)
        if direct_media_open:
            self.open_media_file_immediate(path)
        elif path.is_dir():
            self.load_folder(path)
        elif path.is_file() and is_archive(path):
            self.open_archive(path)
        else:
            QMessageBox.warning(self, "Invalid path", f"Cannot open this path:\n{path_text}")

    def open_archive(self, archive_path, add_history=True, navigation=None):
        archive_path = Path(archive_path)
        if not archive_path.exists():
            QMessageBox.warning(self, "Archive not found", f"Cannot open:\n{archive_path}")
            return False
        self.archive_navigation_generation += 1
        request_id = self.archive_navigation_generation
        self.unc_generation += 1
        for previous_task in list(self.unc_share_task_refs):
            previous_task.cancel()
        self.unc_share_task_refs.clear()
        for previous_task in list(self.archive_task_refs):
            previous_task.cancel()
        self.archive_pool.clear()
        task = ArchiveExtractTask(
            archive_path,
            add_history=add_history,
            navigation=navigation,
            request_id=request_id,
        )
        self.archive_task_refs.add(task)
        task.signals.finished.connect(lambda result, ref=task: self.archive_ready(result, ref))
        self.archive_pool.start(task)
        return True

    def archive_source_for_path(self, path):
        return self.archive_member_sources.get(str(path))

    def archive_ready(self, result, task):
        self.archive_task_refs.discard(task)
        if self.closing or result.get("cancelled") or int(result.get("request_id", 0)) != int(self.archive_navigation_generation):
            session = result.get("session")
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            tempdir = result.get("tempdir")
            if tempdir is not None:
                try:
                    tempdir.cleanup()
                except Exception:
                    pass
            return
        archive_path = Path(result.get("archive", ""))
        if result.get("error"):
            QMessageBox.warning(
                self,
                "Archive error",
                f"Cannot read archive:\n{archive_path}\n\n{result['error']}",
            )
            session = result.get("session")
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            tempdir = result.get("tempdir")
            if tempdir is not None:
                try:
                    tempdir.cleanup()
                except Exception:
                    pass
            return
        if not result.get("count") or result.get("tempdir") is None:
            session = result.get("session")
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            tempdir = result.get("tempdir")
            if tempdir is not None:
                try:
                    tempdir.cleanup()
                except Exception:
                    pass
            QMessageBox.information(self, "Archive", "No image files found in this zip.")
            return
        self.archive_tempdirs.append(result["tempdir"])
        session = result.get("session")
        if session is not None:
            self.archive_sessions.append(session)
        sources = result.get("sources") or {}
        self.archive_member_sources.update(sources)
        root = Path(result["root"])
        snapshot_key = os.path.normcase(os.path.abspath(str(root)))
        self.archive_sources_by_root[snapshot_key] = archive_path
        self.archive_root_by_path[snapshot_key] = snapshot_key
        self.archive_context_last_used[snapshot_key] = time.monotonic()
        self.archive_contexts[snapshot_key] = {
            "tempdir": result.get("tempdir"),
            "session": session,
            "source_paths": set(sources),
        }
        snapshots = result.get("snapshots") or {str(root): list(result.get("entries") or [])}
        for folder_text, folder_entries in snapshots.items():
            virtual_folder = Path(folder_text)
            folder_key = self.normalized_location_path(virtual_folder)
            self.archive_sources_by_root[folder_key] = archive_path
            self.archive_root_by_path[folder_key] = snapshot_key
            self.archive_context_last_used[folder_key] = time.monotonic()
            self._store_folder_snapshot(
                folder_key,
                FolderSnapshot(
                    virtual_folder,
                    list(folder_entries),
                    self.folder_signature(virtual_folder),
                ),
            )
        self.prune_archive_contexts()
        self.load_folder(
            root,
            add_history=result.get("add_history", True),
            display_path=f"{archive_path}::",
            force=False,
            sync_tree=False,
            navigation=result.get("navigation"),
        )

    def prune_archive_contexts(self, keep=3):
        """Bound temporary ZIP sessions while retaining recent navigation."""
        roots = {}
        for key, root_key in self.archive_root_by_path.items():
            roots.setdefault(root_key, []).append(key)
        if len(roots) <= max(1, int(keep)):
            return
        ordered = sorted(
            roots,
            key=lambda root_key: self.archive_context_last_used.get(root_key, 0.0),
        )
        current_root = self.archive_root_by_path.get(
            self.normalized_location_path(self.current_folder), ""
        )
        for root_key in ordered:
            if len(roots) <= max(1, int(keep)):
                break
            if root_key == current_root:
                continue
            context = self.archive_contexts.pop(root_key, None) or {}
            for key in roots.pop(root_key, []):
                self.archive_sources_by_root.pop(key, None)
                self.archive_root_by_path.pop(key, None)
                self.archive_context_last_used.pop(key, None)
                self.folder_cache.pop(key, None)
            for path in context.get("source_paths", set()):
                self.archive_member_sources.pop(path, None)
            tempdir = context.get("tempdir")
            if tempdir is not None:
                try:
                    tempdir.cleanup()
                except Exception:
                    pass
            session = context.get("session")
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            if tempdir in self.archive_tempdirs:
                self.archive_tempdirs.remove(tempdir)
            if session in self.archive_sessions:
                self.archive_sessions.remove(session)
            # The lists are kept for compatibility with existing shutdown
            # code; sessions are closed only when their whole context leaves.
            if roots.get(root_key) is not None:
                roots.pop(root_key, None)

    def selected_paths(self):
        if self.view_combo.currentText() == "details":
            return self.details.selected_paths()
        items = self.list.selectedItems()
        if not items and self.list.currentItem():
            items = [self.list.currentItem()]
        return [Path(i.data(Qt.UserRole)) for i in items]

    def selected_primary_path(self):
        paths = self.selected_paths()
        return paths[0] if paths else self.current_folder

    def copy_selected(self):
        if self.main_stack.currentWidget() != self.explorer_root:
            return
        focus = QApplication.focusWidget()
        if focus in (self.path_edit, getattr(self, "quick_search", None)):
            return
        paths = self.selected_paths()
        if paths:
            self.copy_paths(paths)

    def copy_paths(self, paths):
        self.cut_clipboard_paths = set()
        copy_files_to_clipboard(paths)

    def cut_paths(self, paths):
        existing = [Path(path) for path in paths if Path(path).exists()]
        if not existing:
            return
        copy_files_to_clipboard(existing)
        self.cut_clipboard_paths = {str(path) for path in existing}

    def _start_file_operation(self, operation, **kwargs):
        if self.closing:
            return None
        task = FileOperationTask(operation, **kwargs)
        self.file_op_task_refs.add(task)
        task.signals.finished.connect(
            lambda result, ref=task: self._file_operation_finished(result, ref),
            Qt.QueuedConnection,
        )
        self.file_op_pool.start(task)
        return task

    def _file_operation_finished(self, result, task):
        self.file_op_task_refs.discard(task)
        if self.closing or result.get("cancelled"):
            return
        errors = list(result.get("errors") or [])
        if errors:
            title = "Paste failed" if result.get("operation") == "paste" else "Delete failed"
            QMessageBox.warning(self, title, "Could not complete operation:\n\n" + "\n\n".join(errors[:3]))
        if result.get("operation") == "paste" and self.cut_clipboard_paths:
            self.cut_clipboard_paths = set()
        target_folder = Path(result.get("target_folder") or self.current_folder)
        self.invalidate_folder_cache(target_folder)
        current_target = self.normalized_location_path(self.current_folder) == self.normalized_location_path(target_folder)
        if current_target:
            self.populate_list(force=True)
        if current_target and self.viewer and self.main_stack.currentWidget() == self.viewer:
            current = str(self.viewer.items[self.viewer.index]) if self.viewer.items else ""
            self.viewer.items = [Path(p) for p in self.media_paths]
            if self.viewer.items:
                if current in self.media_paths:
                    self.viewer.index = self.media_paths.index(current)
                else:
                    self.viewer.index = min(self.viewer.index, len(self.viewer.items) - 1)
                self.viewer.show_current(reset=False)
            self.viewer.setFocus()
        copied = list(result.get("copied") or [])
        if copied and current_target and self.main_stack.currentWidget() == self.explorer_root:
            self.select_path(copied[0])

    def paste_from_clipboard(self, target_folder=None):
        active_viewer = bool(self.viewer and self.main_stack.currentWidget() == self.viewer)
        active_explorer = self.main_stack.currentWidget() == self.explorer_root
        if not active_explorer and not active_viewer:
            return
        focus = QApplication.focusWidget()
        if active_explorer and focus in (self.path_edit, getattr(self, "quick_search", None)):
            return
        target_folder = Path(target_folder) if target_folder else self.current_folder
        if self.virtual_unc_server or not self.safe_is_dir(target_folder):
            return
        urls = QApplication.clipboard().mimeData().urls()
        sources = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if not sources:
            return
        move_mode = bool(self.cut_clipboard_paths) and all(str(source) in self.cut_clipboard_paths for source in sources)
        self._start_file_operation(
            "paste",
            target_folder=target_folder,
            sources=sources,
            move_mode=move_mode,
        )

    def open_selected_viewer(self):
        if QApplication.focusWidget() is self.path_edit:
            self.go_to_typed_path()
            return
        paths = self.selected_paths()
        if paths:
            if paths[0].is_dir():
                self.load_folder(paths[0])
            else:
                self.open_viewer_for(paths[0])

    def open_media_file_immediate(self, path):
        path = Path(path)
        if not path.exists() or not path.is_file() or not is_media(path):
            return False
        target_folder = path.parent
        # A file-association request can arrive while another folder is open.
        # The target folder may have a snapshot from an earlier visit, but it
        # is not being watched while inactive.  Show the requested file first,
        # then force one background scan instead of trusting that stale cache.
        self.invalidate_folder_cache(target_folder)
        self.current_folder = target_folder
        self.startup_media_path = path
        self.prepare_startup_media_folder()
        if self.open_viewer_for(path):
            # One cancellable scan supplies both explorer rows and the active
            # viewer's complete sibling list.  preserve_existing keeps the
            # requested image visible while the scan runs.
            self.populate_list(lightweight=True, force=True, preserve_existing=True)
            return True
        return False

    def open_viewer_for(self, path):
        if not self.media_paths:
            return False
        path = str(path)
        try:
            idx = self.media_paths.index(path)
        except ValueError:
            # Explorer/file-association paths can differ only in case or
            # separator normalization on Windows.  Falling back to index 0
            # opens an apparently random image and makes subsequent order
            # navigation look corrupted, especially in large mixed folders.
            requested_key = self.normalized_location_path(path)
            idx = next(
                (
                    index
                    for index, candidate in enumerate(self.media_paths)
                    if self.normalized_location_path(candidate) == requested_key
                ),
                0,
            )
        self.pause_thumbnail_work(cancel_pending=True)
        self.preview.suspend()
        if self.main_stack.currentWidget() is self.explorer_root:
            self.explorer_geometry_before_viewer = self.saveGeometry()
        if self.viewer is None:
            self.viewer = ViewerWindow(self.settings, self)
            self.viewer.exitRequested.connect(self.exit_viewer_mode)
            self.viewer.deleteRequested.connect(self.delete_from_viewer)
            self.viewer.copyRequested.connect(self.copy_from_viewer)
            self.viewer.cutRequested.connect(self.cut_from_viewer)
            self.viewer.pasteRequested.connect(self.paste_from_clipboard)
            self.viewer.propertiesRequested.connect(lambda path: self.show_properties(Path(path)))
            self.main_stack.addWidget(self.viewer)
        if self.vlc_prewarm_instance is not None:
            self.viewer.vlc_instance = self.vlc_prewarm_instance
            self.viewer.vlc_init_inflight = False
            self.viewer.vlc_init_error = ""
            bundles = list(self.vlc_prewarm_bundles)
            self.vlc_prewarm_instance = None
            self.vlc_prewarm_bundles = []
            for player_instance, player in bundles:
                self.viewer.video_player_instances[id(player)] = player_instance
                self.viewer._configure_media_player(player)
                self.viewer.video_standby_players.append(player)
        elif self.vlc_prewarm_inflight:
            # The viewer will queue the current video; the prewarm callback
            # dispatches it as soon as the cold plugin scan completes.
            self.viewer.vlc_init_inflight = True
        self.viewer.item_signatures = {str(entry.path): (entry.size, entry.mtime) for entry in self.entries}
        active_media_paths = set(self.media_paths)
        self.viewer.archive_sources = {
            path: source
            for path, source in self.archive_member_sources.items()
            if path in active_media_paths
        }
        thumbnail_icon = self.thumbnail_cache.get(path)
        self.viewer.opening_placeholder = (
            thumbnail_icon.pixmap(QSize(512, 512)) if thumbnail_icon is not None else QPixmap()
        )
        self.viewer.update_mode_button()
        self.nav_toolbar.hide()
        self.main_stack.setCurrentWidget(self.viewer)
        if self.settings.get("viewer_start_mode", "fullscreen") == "window":
            self.showNormal()
            source_size = QImageReader(path).size() if is_image(path) else QSize()
            screen = QApplication.primaryScreen().availableGeometry()
            width = source_size.width() if source_size.isValid() else 960
            height = source_size.height() if source_size.isValid() else 720
            self.resize(
                max(480, min(width, int(screen.width() * 0.9))),
                max(360, min(height, int(screen.height() * 0.9))),
            )
        else:
            self.showFullScreen()
        self.viewer.load(self.media_paths, idx)
        self.viewer.setFocus()
        return True

    def copy_from_viewer(self, path):
        self.copy_paths([Path(path)])
        if self.viewer:
            self.viewer.setFocus()

    def cut_from_viewer(self, path):
        self.cut_paths([Path(path)])
        if self.viewer:
            self.viewer.setFocus()

    def handle_delete_shortcut(self):
        if self.viewer and self.main_stack.currentWidget() == self.viewer:
            self.viewer.request_delete_current()
        else:
            self.delete_selected()

    @staticmethod
    def is_media_file_busy_error(error):
        return isinstance(error, PermissionError) or getattr(error, "winerror", None) in (32, 33)

    def release_media_file_workers(self, timeout_ms=2000):
        """Release short-lived decoder/player file handles before one delete retry."""
        self.pause_thumbnail_work(cancel_pending=True)
        pools = [self.thumbnail_pool]
        if self.viewer:
            self.viewer.cancel_pending_decodes()
            self.viewer.stop_animated_image()
            self.viewer.stop_media()
            pools.extend((
                self.viewer.decode_pool,
                self.viewer.preload_decode_pool,
                self.viewer.animated_image_pool,
            ))
        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        for pool in pools:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 0:
                break
            pool.waitForDone(remaining_ms)

    def delete_from_viewer(self, path):
        if not self.viewer:
            return
        path = Path(path)
        deleted_path = str(path)
        deleted_index = self.viewer.index
        if path.exists():
            try:
                send_to_recycle_bin(path)
            except Exception as error:
                if self.is_media_file_busy_error(error):
                    self.release_media_file_workers()
                    try:
                        send_to_recycle_bin(path)
                    except Exception:
                        QMessageBox.warning(self, "Delete failed", f"Could not move to recycle bin:\n{path}")
                        self.viewer.setFocus()
                        return
                else:
                    QMessageBox.warning(self, "Delete failed", f"Could not move to recycle bin:\n{path}")
                    self.viewer.setFocus()
                    return

        self.media_paths = [item for item in self.media_paths if item != deleted_path]
        self.startup_media_scan_paths = [item for item in self.startup_media_scan_paths if item != deleted_path]
        self.startup_media_scan_seen.discard(deleted_path)
        self.viewer.remove_current_after_delete(deleted_path)

        if not self.viewer.items:
            candidates = []
            seen = set()
            for item in [*self.media_paths, *self.startup_media_scan_paths]:
                item_path = Path(item)
                key = os.path.normcase(os.path.abspath(str(item_path)))
                if key in seen or str(item_path) == deleted_path:
                    continue
                if item_path.exists() and item_path.is_file() and is_media(item_path):
                    seen.add(key)
                    candidates.append(str(item_path))
            if not candidates:
                candidates = [
                    item
                    for item in self.collect_media_paths(self.current_folder)
                    if item != deleted_path
                ]
            self.media_paths = candidates
            if candidates:
                self.viewer.items = [Path(item) for item in candidates]
                self.viewer.index = min(deleted_index, len(self.viewer.items) - 1)
                self.viewer.show_current(reset=not self.viewer.zoom_locked)
            else:
                self.exit_viewer_mode()
                self.invalidate_folder_cache(self.current_folder)
                self.populate_list(force=True, preserve_existing=True)
                return

        current_path = str(self.viewer.items[self.viewer.index])
        if self.startup_media_path and str(self.startup_media_path) == deleted_path:
            self.startup_media_path = Path(current_path)
        if self.startup_media_scan_target == deleted_path:
            self.startup_media_scan_target = current_path
        self.invalidate_folder_cache(self.current_folder)
        self.populate_list(force=True, preserve_existing=True)
        self.viewer.setFocus()

    def exit_viewer_mode(self, refresh=False):
        if not self.viewer:
            return
        current = None
        if self.viewer.items:
            current = str(self.viewer.items[self.viewer.index])
        self.viewer.deactivate()
        if self.viewer._app_filter_installed:
            QApplication.instance().removeEventFilter(self.viewer)
            self.viewer._app_filter_installed = False
        self.main_stack.setCurrentWidget(self.explorer_root)
        self.explorer_root.update()
        self.main_stack.update()
        self.nav_toolbar.hide()
        if self.isFullScreen():
            self.showNormal()
        if self.explorer_geometry_before_viewer is not None:
            self.restoreGeometry(self.explorer_geometry_before_viewer)
        if not self.entries:
            snapshot = self.folder_cache.get(self.current_snapshot_key)
            if snapshot is not None:
                self.entries = self.sorted_entries(
                    list(snapshot.entries),
                    self.settings.get("sort_mode", "name"),
                    self.settings.get("sort_ascending", True),
                )
                self.entry_by_path = {str(entry.path): entry for entry in self.entries}
                self.media_paths = [
                    str(entry.path)
                    for entry in self.entries
                    if not entry.is_dir and is_media(entry.path)
                ]
                self.explorer_render_pending = True
            elif self.media_paths:
                # Emergency restore uses the already-known sibling list only;
                # it deliberately performs no per-file stat and no folder scan.
                self.entries = self.sorted_entries(
                    [MediaItem(Path(path), False) for path in self.media_paths],
                    self.settings.get("sort_mode", "name"),
                    self.settings.get("sort_ascending", True),
                )
                self.entry_by_path = {str(entry.path): entry for entry in self.entries}
                self.explorer_render_pending = True
        if self.explorer_render_pending:
            self.render_entries(self.entries, lightweight=True)
            self.explorer_render_pending = False
        visible_count = self.details.rowCount() if self.view_combo.currentText() == "details" else self.list.count()
        if refresh or self.explorer_dirty:
            self.populate_list(lightweight=True, force=True, preserve_existing=True)
        elif self.entries:
            if visible_count == 0:
                self.render_entries(self.entries, lightweight=True)
        if current:
            self.select_path(current, scroll=False)
        if self.pending_tree_path:
            self.tree_sync_timer.start(0)
        self.preview.resume()
        self.thumbnail_paused = True
        # The viewer object is intentionally retained for fast re-entry.  Once
        # it is hidden, warm libVLC again from the cached folder snapshot so a
        # later video open does not pay the cold plugin-scan cost a second time.
        self.schedule_vlc_prewarm(self.entries)
        self.thumbnail_resume_timer.start()

    def resume_thumbnails_after_viewer(self):
        if self.closing or self.main_stack.currentWidget() is not self.explorer_root:
            return
        if self.viewer is not None:
            active_viewer_workers = (
                self.viewer.decode_pool.activeThreadCount()
                + self.viewer.preload_decode_pool.activeThreadCount()
                + self.viewer.animated_image_pool.activeThreadCount()
            )
            if active_viewer_workers:
                self.thumbnail_resume_timer.start()
                return
        self.thumbnail_paused = False
        self.prioritize_visible_thumbnails()

    def select_path(self, path, scroll=True):
        if self.view_combo.currentText() == "details":
            for row in range(self.details.rowCount()):
                item = self.details.item(row, 0)
                if item and item.data(Qt.UserRole) == path:
                    self.details.selectRow(row)
                    if scroll:
                        self.details.scrollToItem(item)
                    break
        else:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole) == path:
                    self.list.setCurrentItem(item)
                    if scroll:
                        self.list.scrollToItem(item)
                    break

    def go_up(self):
        # ``\\server`` is already the highest navigable level exposed by the
        # explorer.  ``current_folder`` intentionally keeps the last physical
        # folder while that virtual share list is visible, so never derive an
        # Up target from that stale physical path.
        if self.virtual_unc_server:
            return
        current_key = os.path.normcase(os.path.abspath(str(self.current_folder)))
        archive_path = self.archive_sources_by_root.get(current_key)
        if archive_path is not None:
            root_key = self.archive_root_by_path.get(current_key, current_key)
            if current_key != root_key:
                root = Path(root_key)
                parent = Path(self.current_folder).parent
                relative = parent.relative_to(root).as_posix() if parent != root else ""
                display = f"{archive_path}::{relative}" if relative else f"{archive_path}::"
                self.load_folder(parent, display_path=display, sync_tree=False, navigation={"mode": "top"})
            else:
                self.open_location(Path(archive_path).parent, navigation={"mode": "top"})
            return
        parent = self.navigation_parent_path(self.current_folder)
        if parent != self.current_folder:
            # Going up from ``\\server\share`` must use the virtual UNC share
            # listing rather than scanning ``\\server`` as a normal folder.
            self.open_location(parent, navigation={"mode": "top"})

    @staticmethod
    def normalized_location_path(path):
        return os.path.normcase(os.path.abspath(str(path)))

    @staticmethod
    def navigation_parent_path(path):
        path = Path(path)
        text = str(path).replace("/", "\\").rstrip("\\")
        if text.startswith("\\\\"):
            parts = [part for part in text[2:].split("\\") if part]
            # pathlib treats ``\\server\share`` as an indivisible drive root.
            # The explorer still exposes ``\\server`` above that share.
            if len(parts) == 2:
                return Path(f"\\\\{parts[0]}")
        return path.parent

    def current_navigation_source_path(self):
        if self.virtual_unc_server:
            return Path(f"\\\\{self.virtual_unc_server}")
        current_key = self.normalized_location_path(self.current_folder)
        archive_path = self.archive_sources_by_root.get(current_key)
        return Path(archive_path) if archive_path is not None else Path(self.current_folder)

    def back_navigation_request(self, target_text):
        source = self.current_navigation_source_path()
        target_text = str(target_text).split("::", 1)[0]
        target = Path(target_text)
        if self.normalized_location_path(self.navigation_parent_path(source)) == self.normalized_location_path(target):
            return {"mode": "anchor", "anchor": str(source)}
        return {"mode": "top"}

    def go_back(self):
        if self.history_index > 0:
            target = self.history[self.history_index - 1]
            navigation = self.back_navigation_request(target)
            self.history_index -= 1
            self.open_location(target, add_history=False, navigation=navigation)

    def go_forward(self):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self.open_location(
                self.history[self.history_index],
                add_history=False,
                navigation={"mode": "top"},
            )

    def mousePressEvent(self, event):
        if self.main_stack.currentWidget() == self.explorer_root:
            if event.button() == Qt.BackButton:
                self.go_back()
                return
            if event.button() == Qt.ForwardButton:
                self.go_forward()
                return
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if hasattr(self, "main_stack") and self.main_stack.currentWidget() == self.explorer_root:
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.BackButton:
                    self.go_back()
                    return True
                if event.button() == Qt.ForwardButton:
                    self.go_forward()
                    return True
            if event.type() == QEvent.KeyPress:
                if event.matches(QKeySequence.Copy):
                    self.copy_selected()
                    return True
                if event.matches(QKeySequence.Paste):
                    self.paste_from_clipboard()
                    return True
                if event.key() == Qt.Key_Backspace:
                    self.go_back()
                    return True
        return super().eventFilter(obj, event)

    def new_folder(self, parent=None):
        parent = Path(parent) if parent else self.current_folder
        if not self.safe_is_dir(parent):
            return
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name")
        if ok and name.strip():
            (parent / name.strip()).mkdir(exist_ok=True)
            self.invalidate_folder_cache(parent)
            self.populate_list(force=True)

    def rename_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        self.rename_path(paths[0])

    def rename_path(self, path):
        path = Path(path)
        if not path.exists():
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name", text=path.name)
        if ok and name.strip() and name.strip() != path.name:
            path.rename(path.with_name(name.strip()))
            self.invalidate_folder_cache(self.current_folder)
            self.populate_list(force=True)

    def delete_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        self.delete_paths(paths)

    def delete_paths(self, paths):
        paths = [Path(path) for path in paths if Path(path).exists()]
        if not paths:
            return
        names = "\n".join(str(path) for path in paths[:10])
        more = "" if len(paths) <= 10 else f"\n... and {len(paths) - 10} more"
        answer = QMessageBox.question(self, "Delete", f"Move {len(paths)} item(s) to recycle bin if possible?\n\n{names}{more}")
        if answer != QMessageBox.Yes:
            return
        self._start_file_operation("delete", sources=paths, target_folder=self.current_folder)

    def show_properties(self, path):
        path = Path(path)
        if not path.exists():
            return
        if sys.platform == "win32":
            class ShellExecuteInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]
            info = ShellExecuteInfo()
            info.cbSize = ctypes.sizeof(ShellExecuteInfo)
            info.fMask = 0x0000000C
            info.hwnd = int(self.winId())
            info.lpVerb = "properties"
            info.lpFile = str(path)
            info.nShow = 1
            if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
                QMessageBox.warning(self, "Properties", f"Could not open properties:\n{path}")
            return
        os.startfile(str(path))

    def list_menu(self, pos):
        item = self.list.itemAt(pos)
        if item:
            self.list.setCurrentItem(item)
        menu = QMenu(self)
        path = self.selected_primary_path()
        menu.addAction("Open Viewer (&V)", self.open_selected_viewer)
        if path.is_dir():
            menu.addAction("Add Shortcut (&S)", lambda p=path: self.add_quick_path(str(p)))
        menu.addSeparator()
        menu.addAction("Open in Windows (&E)", lambda p=path: self.open_in_explorer(p))
        menu.addSeparator()
        menu.addAction("New Folder (&N)", self.new_folder)
        menu.addSeparator()
        menu.addAction("Cut (&T)", lambda: self.cut_paths(self.selected_paths()))
        menu.addAction("Copy (&C)", self.copy_selected)
        menu.addAction("Paste (&P)", self.paste_from_clipboard)
        menu.addAction("Rename (&M)", self.rename_selected)
        menu.addAction("Delete (&D)", self.delete_selected)
        menu.addSeparator()
        menu.addAction("Properties (&R)", lambda p=path: self.show_properties(p))
        menu.exec(self.list.mapToGlobal(pos))

    def details_menu(self, pos):
        item = self.details.itemAt(pos)
        if item:
            self.details.selectRow(item.row())
        menu = QMenu(self)
        path = self.selected_primary_path()
        menu.addAction("Open Viewer (&V)", self.open_selected_viewer)
        if path.is_dir():
            menu.addAction("Add Shortcut (&S)", lambda p=path: self.add_quick_path(str(p)))
        menu.addSeparator()
        menu.addAction("Open in Windows (&E)", lambda p=path: self.open_in_explorer(p))
        menu.addSeparator()
        menu.addAction("New Folder (&N)", self.new_folder)
        menu.addSeparator()
        menu.addAction("Cut (&T)", lambda: self.cut_paths(self.selected_paths()))
        menu.addAction("Copy (&C)", self.copy_selected)
        menu.addAction("Paste (&P)", self.paste_from_clipboard)
        menu.addAction("Rename (&M)", self.rename_selected)
        menu.addAction("Delete (&D)", self.delete_selected)
        menu.addSeparator()
        menu.addAction("Properties (&R)", lambda p=path: self.show_properties(p))
        menu.exec(self.details.mapToGlobal(pos))

    def tree_menu(self, pos):
        menu = QMenu(self)
        index = self.tree.indexAt(pos)
        path = Path(self.tree_model.filePath(index)) if index.isValid() else self.current_folder
        if path.exists() and path.is_dir():
            if index.isValid():
                self.tree.setCurrentIndex(index)
            menu.addAction("Add Shortcut (&S)", lambda p=path: self.add_quick_path(str(p)))
            menu.addSeparator()
            menu.addAction("Open in Windows (&E)", lambda p=path: self.open_in_explorer(p))
            menu.addSeparator()
            menu.addAction("Add Tab (&B)", lambda p=path: self.add_folder_tab(p))
            menu.addSeparator()
            menu.addAction("New Folder (&N)", lambda p=path: self.new_folder(p))
            menu.addSeparator()
            menu.addAction("Cut (&T)", lambda p=path: self.cut_paths([p]))
            menu.addAction("Copy (&C)", lambda p=path: self.copy_paths([p]))
            menu.addAction("Paste (&P)", lambda p=path: self.paste_from_clipboard(p))
            menu.addAction("Rename (&M)", lambda p=path: self.rename_path(p))
            menu.addAction("Delete (&D)", lambda p=path: self.delete_paths([p]))
            menu.addSeparator()
            menu.addAction("Properties (&R)", lambda p=path: self.show_properties(p))
        menu.exec(self.tree.mapToGlobal(pos))

    def open_in_explorer(self, path=None):
        path = Path(path) if path else self.current_folder
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))

    def open_shortcuts(self):
        dlg = ShortcutDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            self.apply_performance_profile()
            self.apply_theme()
            self.render_entries(self.entries, lightweight=True, preserve_scroll=True)
            QMessageBox.information(self, "Settings", "Shortcut changes are saved. Restart to rebuild keyboard bindings.")

    def closeEvent(self, event):
        self.closing = True
        if hasattr(self, "thumbnail_resume_timer"):
            self.thumbnail_resume_timer.stop()
        self.folder_scan_generation += 1
        for task in list(getattr(self, "folder_scan_task_refs", set())):
            task.cancel()
        for task in list(getattr(self, "archive_task_refs", set())):
            task.cancel()
        for task in list(getattr(self, "unc_share_task_refs", set())):
            task.cancel()
        self.unc_share_task_refs.clear()
        for task in list(getattr(self, "file_op_task_refs", set())):
            task.cancel()
        if hasattr(self, "settings_save_timer") and self.settings_save_timer.isActive():
            self.settings_save_timer.stop()
            save_settings(self.settings)
        if hasattr(self, "thumbnail_pool"):
            self.pause_thumbnail_work(cancel_pending=True)
        if hasattr(self, "mouse_wheel_hook"):
            self.mouse_wheel_hook.uninstall()
        for pool in (
            getattr(self, "folder_scan_pool", None),
            getattr(self, "thumbnail_pool", None),
            getattr(self, "archive_pool", None),
            getattr(self, "file_op_pool", None),
        ):
            if pool is not None:
                pool.clear()
                pool.waitForDone(1500)
        if self.viewer:
            self.viewer.shutdown_for_close()
        if self.vlc_prewarm_thread is not None and self.vlc_prewarm_thread.is_alive():
            self.vlc_prewarm_thread.join(timeout=1.0)
        for _player_instance, player in list(self.vlc_prewarm_bundles):
            try:
                player.release()
            except Exception:
                pass
        self.vlc_prewarm_bundles = []
        if self.vlc_prewarm_instance is not None:
            try:
                self.vlc_prewarm_instance.release()
            except Exception:
                pass
            self.vlc_prewarm_instance = None
        for tempdir in getattr(self, "archive_tempdirs", []):
            try:
                tempdir.cleanup()
            except Exception:
                pass
        for session in getattr(self, "archive_sessions", []):
            try:
                session.close()
            except Exception:
                pass
        super().closeEvent(event)


def send_to_recycle_bin(path):
    try:
        from send2trash import send2trash
        send2trash(str(path))
    except Exception:
        raise


def copy_files_to_clipboard(paths):
    # QMimeData's ``text/uri-list`` is translated to CF_HDROP by Qt on
    # Windows, which is the format Explorer consumes for Ctrl+V.  Keep the
    # URLs for Qt/internal paste and also publish the Unicode Windows file
    # name flavor explicitly.  The latter matters on some Windows/Qt plugin
    # combinations where the delayed CF_HDROP conversion is not advertised
    # until the clipboard is queried by another process.
    existing = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        # Explorer requires absolute filesystem paths.  Avoid resolving
        # symlinks (or touching network targets) while still normalizing any
        # relative path supplied by a viewer/list item.
        if not path.is_absolute():
            path = Path(os.path.abspath(str(path)))
        existing.append(path)
    if not existing:
        return
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in existing])
    mime.setText("\n".join(str(path) for path in existing))
    if sys.platform == "win32":
        windows_paths = "\0".join(str(path) for path in existing) + "\0\0"
        mime.setData(
            'application/x-qt-windows-mime;value="FileNameW"',
            windows_paths.encode("utf-16le"),
        )
    QApplication.clipboard().setMimeData(mime)


def windows_shell_thumbnail_image(path, size=512):
    if sys.platform != "win32":
        return None
    com_initialized = False
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        class BITMAP(ctypes.Structure):
            _fields_ = [
                ("bmType", ctypes.c_long),
                ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long),
                ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wintypes.WORD),
                ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p),
            ]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        class IShellItemImageFactory(ctypes.Structure):
            pass

        QueryInterface = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        AddRef = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
        Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
        GetImage = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP))

        class IShellItemImageFactoryVtbl(ctypes.Structure):
            _fields_ = [
                ("QueryInterface", QueryInterface),
                ("AddRef", AddRef),
                ("Release", Release),
                ("GetImage", GetImage),
            ]

        IShellItemImageFactory._fields_ = [("lpVtbl", ctypes.POINTER(IShellItemImageFactoryVtbl))]

        iid = GUID(0xBCC18B79, 0xBA16, 0x442F, (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        ole32.CoInitialize(None)
        com_initialized = True
        factory = ctypes.c_void_p()
        shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
        if shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(iid), ctypes.byref(factory)) < 0 or not factory:
            ole32.CoUninitialize()
            com_initialized = False
            return None
        obj = ctypes.cast(factory, ctypes.POINTER(IShellItemImageFactory))
        hbitmap = wintypes.HBITMAP()
        flags = 0x1
        hr = obj.contents.lpVtbl.contents.GetImage(factory, SIZE(int(size), int(size)), flags, ctypes.byref(hbitmap))
        obj.contents.lpVtbl.contents.Release(factory)
        if hr < 0 or not hbitmap:
            ole32.CoUninitialize()
            com_initialized = False
            return None

        bitmap = BITMAP()
        gdi32.GetObjectW(hbitmap, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        width = int(bitmap.bmWidth)
        height = int(bitmap.bmHeight)
        if width <= 0 or height <= 0:
            gdi32.DeleteObject(hbitmap)
            ole32.CoUninitialize()
            com_initialized = False
            return None
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        buffer = (ctypes.c_ubyte * (width * height * 4))()
        hdc = user32.GetDC(None)
        try:
            lines = gdi32.GetDIBits(hdc, hbitmap, 0, height, ctypes.byref(buffer), ctypes.byref(bmi), 0)
        finally:
            user32.ReleaseDC(None, hdc)
            gdi32.DeleteObject(hbitmap)
        if lines == 0:
            ole32.CoUninitialize()
            com_initialized = False
            return None
        image = QImage(bytes(buffer), width, height, QImage.Format_ARGB32).copy()
        ole32.CoUninitialize()
        com_initialized = False
        return image if not image.isNull() else None
    except Exception:
        if com_initialized:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass
        return None


def windows_shell_thumbnail(path, size=512):
    image = windows_shell_thumbnail_image(path, size)
    if image is None or image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    return pixmap if not pixmap.isNull() else None


def unique_copy_target(target):
    target = Path(target)
    if not target.exists():
        return target
    parent = target.parent
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 10000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many duplicate names for {target.name}")


def path_contains(parent, child):
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def send_to_existing_instance(path_text=None):
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    payload = json.dumps({"path": path_text or ""}, ensure_ascii=False).encode("utf-8")
    socket.write(payload)
    socket.flush()
    socket.waitForBytesWritten(250)
    socket.disconnectFromServer()
    socket.waitForDisconnected(250)
    return True


def start_instance_server(window):
    server = QLocalServer(window)
    if not server.listen(INSTANCE_SERVER_NAME):
        probe = QLocalSocket()
        probe.connectToServer(INSTANCE_SERVER_NAME)
        if probe.waitForConnected(100):
            probe.disconnectFromServer()
            return None
        QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        if not server.listen(INSTANCE_SERVER_NAME):
            return None

    def handle_connection():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection._photo_viewer_handled = False

            def read_request(conn=connection):
                if getattr(conn, "_photo_viewer_handled", False):
                    return
                if conn.bytesAvailable() <= 0:
                    if conn.state() == QLocalSocket.UnconnectedState:
                        conn.deleteLater()
                    return
                conn._photo_viewer_handled = True
                try:
                    data = bytes(conn.readAll()).decode("utf-8", errors="replace")
                    payload = json.loads(data) if data else {}
                    window.open_external_request(payload.get("path") or None)
                except Exception:
                    window.open_external_request(None)
                finally:
                    conn.disconnectFromServer()
                    conn.deleteLater()

            connection.readyRead.connect(read_request)
            connection.disconnected.connect(read_request)
            if connection.bytesAvailable():
                QTimer.singleShot(0, read_request)

    server.newConnection.connect(handle_connection)
    return server


def main():
    migrate_legacy_settings()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "StynerPark.PhotoViewer"
            )
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    startup_path = sys.argv[1] if len(sys.argv) > 1 else None
    settings = load_settings()
    if settings.get("instance_mode", "multi") == "single" and send_to_existing_instance(startup_path):
        return
    win = MainWindow(startup_path=startup_path)
    win.instance_server = start_instance_server(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
