import json
import os
import queue
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
from io import BytesIO
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Photo Viewer"
APP_VERSION = "1.0.1"
LEGACY_APP_NAME = "Portable Photo Viewer"
INSTANCE_SERVER_NAME = "StynerPark_PhotoViewer_Instance"
DEFAULT_LAST_FOLDER_SETTING = r"%USERPROFILE%\Documents"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUN_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def resolve_settings_path(run_dir=None, local_appdata=None):
    if local_appdata is None:
        local_appdata = os.environ.get("LOCALAPPDATA")
    settings_root = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return settings_root / APP_NAME / "settings.json"


def migrate_legacy_settings(settings_path=None, local_appdata=None):
    target = Path(settings_path) if settings_path is not None else resolve_settings_path(
        local_appdata=local_appdata
    )
    if target.exists():
        return False
    if local_appdata is None:
        local_appdata = os.environ.get("LOCALAPPDATA")
    settings_root = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    legacy = settings_root / LEGACY_APP_NAME / "settings.json"
    if not legacy.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, target)
    return True


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
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QImageReader, QIntValidator, QKeySequence, QMovie, QPainter, QPalette, QPen, QPixmap, QShortcut
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
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

try:
    import vlc
except Exception:
    vlc = None


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

VIEWER_CACHE_LIMIT_BYTES = 128 * 1024 * 1024
WEBTOON_CACHE_LIMIT_BYTES = 192 * 1024 * 1024
THUMBNAIL_CACHE_LIMIT_BYTES = 128 * 1024 * 1024
MAX_ANIMATED_FRAME_PIXELS = 16 * 1024 * 1024


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
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def is_image(path):
    return Path(path).suffix.lower() in IMAGE_EXTS


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


def is_media(path):
    return Path(path).suffix.lower() in MEDIA_EXTS


def is_archive(path):
    return Path(path).suffix.lower() in ARCHIVE_EXTS


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


def type_color(path, is_dir_entry=False):
    if is_dir_entry or is_archive(path):
        return None
    ext = Path(path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".jfif"}:
        color = QColor("#a2ad45")
        color.setAlpha(78)
        return color
    if ext == ".png":
        color = QColor("#b96e63")
        color.setAlpha(76)
        return color
    if ext == ".webp":
        color = QColor("#7d9850")
        color.setAlpha(76)
        return color
    if ext == ".gif":
        color = QColor("#48a66a")
        color.setAlpha(72)
        return color
    if ext in {".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".mpeg", ".mpg", ".ts", ".m2ts", ".3gp", ".ogv"}:
        color = QColor("#4e9db1")
        color.setAlpha(74)
        return color
    if ext in {".bmp", ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm", ".pnm"}:
        color = QColor("#b38a4b")
        color.setAlpha(74)
        return color
    color = QColor("#80788f")
    color.setAlpha(60)
    return color


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


class DecodeSignals(QObject):
    finished = Signal(int, str, object, object)


class ImageDecodeTask(QRunnable):
    def __init__(self, generation, path, max_size, canvas_size=None, video_shell=False, thread_priority=QThread.LowPriority):
        super().__init__()
        self.generation = int(generation)
        self.path = str(path)
        self.max_size = tuple(max_size)
        self.canvas_size = tuple(canvas_size) if canvas_size else None
        self.video_shell = bool(video_shell)
        self.thread_priority = thread_priority
        self.cancelled = False
        self.signals = DecodeSignals()

    def cancel(self):
        self.cancelled = True

    def run(self):
        payload = None
        metadata = {}
        try:
            if self.cancelled:
                raise InterruptedError
            QThread.currentThread().setPriority(self.thread_priority)
            path = Path(self.path)
            if self.video_shell:
                payload = windows_shell_thumbnail_image(path, max(self.max_size))
            else:
                reader = QImageReader(str(path))
                source_size = reader.size()
                if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                    metadata = {
                        "image_size": (source_size.width(), source_size.height()),
                        "image_format": bytes(reader.format()).decode("ascii", errors="ignore").upper(),
                    }
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
                    metadata = {
                        "image_size": (int(source.width), int(source.height)),
                        "image_format": str(source.format or path.suffix.upper().strip(".")),
                    }
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

    def __init__(self, generation, state_key, token, path, render_token, render_spec):
        super().__init__()
        self.generation = int(generation)
        self.state_key = int(state_key)
        self.token = int(token)
        self.path = str(path)
        self._render_token = int(render_token)
        self._render_spec = dict(render_spec)
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

    def render_snapshot(self):
        with self._spec_lock:
            return self._render_token, dict(self._render_spec)

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
        if pixels > MAX_ANIMATED_FRAME_PIXELS:
            scale = (MAX_ANIMATED_FRAME_PIXELS / pixels) ** 0.5
            target_width = max(1, int(target_width * scale))
            target_height = max(1, int(target_height * scale))
        return target_width, target_height

    def run(self):
        error = ""
        delivered = 0
        try:
            QThread.currentThread().setPriority(QThread.LowPriority)
            with Image.open(self.path) as reader:
                frame_count = max(1, int(getattr(reader, "n_frames", 1) or 1))
                animated = bool(getattr(reader, "is_animated", False) and frame_count > 1)
                index = 0
                while not self.cancel_event.is_set():
                    reader.seek(index)
                    duration = max(20, int(reader.info.get("duration", 80) or 80))
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
                    refreshed = self.refresh_event.wait(duration / 1000.0)
                    self.refresh_event.clear()
                    if self.cancel_event.is_set():
                        break
                    if not refreshed:
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
    def __init__(self, archive_path, add_history=True):
        super().__init__()
        self.archive_path = str(archive_path)
        self.add_history = bool(add_history)
        self.signals = ArchiveSignals()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self):
        result = {
            "archive": self.archive_path,
            "add_history": self.add_history,
            "tempdir": None,
            "root": None,
            "count": 0,
            "entries": [],
            "error": "",
            "cancelled": False,
        }
        tempdir = None
        try:
            tempdir = tempfile.TemporaryDirectory(prefix="pmv_zip_")
            root = Path(tempdir.name)
            names = set()
            with zipfile.ZipFile(self.archive_path) as archive:
                for info in archive.infolist():
                    if self.cancelled:
                        raise InterruptedError
                    if info.is_dir():
                        continue
                    inner = Path(info.filename)
                    if inner.suffix.lower() not in IMAGE_EXTS:
                        continue
                    base_name = inner.name
                    stem = Path(base_name).stem
                    suffix = Path(base_name).suffix
                    index = 1
                    while base_name.lower() in names:
                        base_name = f"{stem}_{index}{suffix}"
                        index += 1
                    names.add(base_name.lower())
                    target = root / base_name
                    with archive.open(info) as source, target.open("wb") as destination:
                        while True:
                            if self.cancelled:
                                raise InterruptedError
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            destination.write(chunk)
                    stat = target.stat()
                    result["entries"].append(
                        MediaItem(target, False, size=int(stat.st_size), mtime=float(stat.st_mtime))
                    )
                    result["count"] += 1
            result["tempdir"] = tempdir
            result["root"] = root
        except InterruptedError:
            result["cancelled"] = True
            if tempdir is not None:
                tempdir.cleanup()
        except Exception as exc:
            result["error"] = str(exc)
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


class VlcInitSignals(QObject):
    finished = Signal(object, object, str, object)


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
        instance = None
        player = None
        error = ""
        try:
            if sys.platform == "win32":
                try:
                    ctypes.windll.kernel32.SetThreadPriority(
                        ctypes.windll.kernel32.GetCurrentThread(), -1
                    )
                except Exception:
                    pass
            instance = self.vlc_module.Instance("--quiet")
            if instance is None:
                raise RuntimeError("libVLC instance creation returned no instance")
            player = instance.media_player_new()
            if player is None:
                raise RuntimeError("libVLC media player creation returned no player")
        except Exception as exc:
            error = str(exc)
            try:
                if player is not None:
                    player.release()
            except Exception:
                pass
            try:
                if instance is not None:
                    instance.release()
            except Exception:
                pass
            instance = None
            player = None
        try:
            self.signals.finished.emit(instance, player, error, self)
        except RuntimeError:
            pass


class ThumbList(QListWidget):
    openRequested = Signal(str)
    previewRequested = Signal(str)
    copyRequested = Signal()
    deleteRequested = Signal()
    pasteRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("thumbList")
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemDoubleClicked.connect(self._open_item)
        self.itemSelectionChanged.connect(self._preview_selected)
        self.icon_provider = QFileIconProvider()
        self.setSpacing(8)

    def set_view_mode_name(self, mode):
        if mode == "list":
            self.setViewMode(QListWidget.ListMode)
            self.setIconSize(QSize(32, 32))
            self.setGridSize(QSize())
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "details":
            self.setViewMode(QListWidget.ListMode)
            self.setIconSize(QSize(48, 48))
            self.setGridSize(QSize())
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "small":
            self.setViewMode(QListWidget.IconMode)
            self.setIconSize(QSize(72, 72))
            self.setGridSize(QSize(116, 116))
            self.setResizeMode(QListWidget.Adjust)
        elif mode == "medium":
            self.setViewMode(QListWidget.IconMode)
            self.setIconSize(QSize(120, 120))
            self.setGridSize(QSize(168, 160))
            self.setResizeMode(QListWidget.Adjust)
        else:
            self.setViewMode(QListWidget.IconMode)
            self.setIconSize(QSize(168, 168))
            self.setGridSize(QSize(224, 216))
            self.setResizeMode(QListWidget.Adjust)

    def _open_item(self, item):
        self.openRequested.emit(item.data(Qt.UserRole))

    def _preview_selected(self):
        items = self.selectedItems()
        if items:
            self.previewRequested.emit(items[0].data(Qt.UserRole))

    def startDrag(self, supported_actions):
        super().startDrag(supported_actions)

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
                    entry.display_name.lower(),
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
                color = type_color(entry.path, entry.is_dir)
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
        self._task_refs = set()
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
        self._pool.clear()
        self.movie = None
        self._source_pixmap = QPixmap()
        self._decoded_pixel_size = QSize()
        self._current_path = str(path) if path else None
        if not path or not Path(path).exists():
            self.setText("Preview")
            self.setPixmap(QPixmap())
            return
        if is_video(path):
            self.setText("Video\n" + file_label(path))
            self.setPixmap(self.style().standardIcon(QStyle.SP_MediaPlay).pixmap(96, 96))
            return
        if Path(path).suffix.lower() == ".gif":
            movie = QMovie(path)
            if movie.isValid():
                self.movie = movie
                self.setMovie(movie)
                movie.start()
                return
        self.setText("Loading…")
        self.setPixmap(QPixmap())
        self._queue_decode(generation, str(path))

    def _decode_target(self):
        dpr = max(1.0, float(self.devicePixelRatioF()))
        oversample = 1.5
        width = max(480, int(self.width() * dpr * oversample))
        height = max(360, int(self.height() * dpr * oversample))
        scale = min(1.0, 2048.0 / max(width, height))
        return QSize(max(1, int(width * scale)), max(1, int(height * scale)))

    def _queue_decode(self, generation, path):
        target = self._decode_target()
        task = ImageDecodeTask(generation, path, (target.width(), target.height()))
        self._task_refs.add(task)
        task.signals.finished.connect(
            lambda result_generation, result_path, payload, metadata, ref=task: self._preview_ready(
                result_generation, result_path, payload, ref
            )
        )
        self._pool.start(task)

    def _reload_for_current_size(self):
        path = self._current_path
        if not path or not Path(path).exists() or is_video(path) or Path(path).suffix.lower() == ".gif":
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
        self._queue_decode(self._generation, path)

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
            if viewer and viewer.is_active_viewer() and self._point_in_window(lparam):
                info = self.MSLLHOOKSTRUCT.from_address(int(lparam))
                delta = ctypes.c_short((int(info.mouseData) >> 16) & 0xFFFF).value
                QTimer.singleShot(0, lambda d=delta: viewer.handle_wheel_delta(d))
                return 1
        return self.user32.CallNextHookEx(self.hook, code, wparam, lparam)

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

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.items = []
        self.item_signatures = {}
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
        self.pending_video_requests = []
        self.video_playback_token = 0
        self._video_end_callback = None
        self.video_slot_states = {}
        self.video_end_callbacks = {}
        self.video_loop_enabled = bool(settings.get("video_loop_enabled", False))
        self.video_cleanup_queue = queue.Queue()
        self.video_cleanup_closed = False
        self.video_cleanup_thread = threading.Thread(
            target=self._video_cleanup_worker,
            args=(self.video_cleanup_queue,),
            name="PhotoViewer-VLC-Cleanup",
            daemon=True,
        )
        self.video_cleanup_thread.start()
        self.movie = None
        self._app_filter_installed = False
        self._seeking_video = False
        self.video_path = None
        self.video_finished = False
        self.video_stopped_by_user = False
        self.webtoon_scroll = None
        self.webtoon_container = None
        self.webtoon_loaded = set()
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
        viewer_profile = PERFORMANCE_PROFILES.get(
            settings.get("performance_profile", "balanced"),
            PERFORMANCE_PROFILES["balanced"],
        )
        self.decode_pool = QThreadPool(self)
        self.decode_pool.setMaxThreadCount(max(1, int(viewer_profile["thumbnail_workers"])))
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
        self.animated_image_pool.setMaxThreadCount(3)
        self.animated_image_pool.setThreadPriority(QThread.LowPriority)
        self.animated_image_task_refs = set()
        self.animated_image_token = 0
        self.animated_render_token = 0

        self.setWindowTitle(APP_NAME + " - Viewer")
        self.setMinimumSize(900, 640)
        self._build_ui()
        self._build_shortcuts()
        self.videoEnded.connect(self._mark_video_ended, Qt.QueuedConnection)

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
        self.video_frame = QFrame()
        self.video_frame.setObjectName("videoFrame")
        self.video_frame.setAttribute(Qt.WA_StyledBackground, True)
        self.video_frame.setStyleSheet("background: #000;")
        self.video_frame.setAutoFillBackground(True)
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.setMouseTracking(True)
        self.central.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.installEventFilter(self)
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

        self.corner_filename_label = QLabel("", self.central)
        self.corner_filename_label.setObjectName("cornerFilenameLabel")
        self.corner_filename_label.setStyleSheet("""
            #cornerFilenameLabel { background: rgba(28,25,36,225); color: white; border: 1px solid rgba(151,126,218,130); border-radius: 8px; padding: 6px 10px; }
        """)
        self.corner_filename_label.hide()

        self.rotation_overlay = QFrame(self.central)
        self.rotation_overlay.setObjectName("rotationOverlay")
        self.rotation_overlay.setStyleSheet("""
            #rotationOverlay { background: rgba(28,25,36,235); border: 1px solid rgba(151,126,218,145); border-radius: 10px; color: white; }
            QPushButton { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 11px; }
            QPushButton:hover { background: #3b3549; border-color: #927bd8; }
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
        self.rotation_overlay.hide()

        self.video_overlay = QFrame(self.central)
        self.video_overlay.setObjectName("videoOverlay")
        self.video_overlay.setStyleSheet("""
            #videoOverlay { background: rgba(28,25,36,238); border: 1px solid rgba(151,126,218,150); border-radius: 10px; color: white; }
            QPushButton { background: #302c3b; color: #f5f1fc; border: 1px solid #4b445d; border-radius: 7px; padding: 4px 9px; }
            QPushButton:hover { background: #3b3549; border-color: #927bd8; }
            QPushButton:checked { background: #927bd8; border-color: #ad99e8; color: white; font-weight: 700; }
            QPushButton#videoLoopButton { padding: 0; font-size: 15px; font-weight: 700; }
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
        self.input_layer.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.input_layer.setStyleSheet("background: transparent;")
        self.input_layer.installEventFilter(self)
        self.input_layer.raise_()
        self.update_webtoon_auto_scroll_controls()

    def build_mode_menu(self):
        menu = QMenu(self.mode_btn)
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

    def _vlc_init_finished(self, instance, player, error, task):
        self.vlc_init_task_refs.discard(task)
        self.vlc_init_inflight = False
        self.vlc_init_error = error or ""
        pending = list(self.pending_video_requests)
        self.pending_video_requests = []
        if instance is None or player is None:
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
        self._configure_media_player(player)
        if not pending and not self.is_active_viewer():
            self._queue_video_cleanup([player])
            return
        self.video_standby_players.append(player)
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

    def _attach_video_end_event(self, player, path, frame, primary):
        self.video_playback_token += 1
        token = self.video_playback_token
        try:
            manager = player.event_manager()
            manager.event_detach(vlc.EventType.MediaPlayerEndReached)
        except Exception:
            manager = None
        try:
            callback = lambda _event, current=token: self.videoEnded.emit(current)
            (manager or player.event_manager()).event_attach(
                vlc.EventType.MediaPlayerEndReached,
                callback,
            )
            self.video_end_callbacks[token] = callback
            self.video_slot_states[token] = {
                "player": player,
                "path": Path(path),
                "frame": frame,
                "primary": bool(primary),
                "generation": self.render_generation,
                "ended": False,
                "restarting": False,
            }
            if primary:
                self._video_end_callback = callback
            return token
        except Exception:
            if primary:
                self._video_end_callback = None
            return None

    def _restart_video_slot(self, token):
        token = int(token)
        state = self.video_slot_states.get(token)
        if (
            not self.video_loop_enabled
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
        try:
            media = self.vlc_instance.media_new(str(path))
            player.set_media(media)
            player.set_hwnd(int(frame.winId()))
            self._configure_media_player(player)
            try:
                player.set_time(0)
            except Exception:
                pass
            result = player.play()
            if result is not None and int(result) < 0:
                return False
            player.audio_set_volume(self.volume_slider.value())
            state["ended"] = False
            if primary:
                self.video_finished = False
                self.video_stopped_by_user = False
                self.video_timer.start(250)
            return True
        except Exception:
            return False
        finally:
            state["restarting"] = False

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
        # Warm libVLC while the user is still looking at an image.  Direct
        # video opens still use the same asynchronous path, but image-to-video
        # navigation no longer waits to begin VLC initialization.
        if vlc is not None and any(is_video(path) for path in self.items):
            self._init_vlc_async()
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
                if widget is self.video_frame:
                    widget.hide()
                else:
                    widget.hide()
                    widget.deleteLater()
        self.labels = []

    def is_animated_image_path(self, path):
        return Path(path).suffix.lower() in (".gif", ".webp", ".apng")

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
        limit = WEBTOON_CACHE_LIMIT_BYTES if self.is_webtoon_viewer_mode() else VIEWER_CACHE_LIMIT_BYTES
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
        if cost <= 0 or cost > WEBTOON_CACHE_LIMIT_BYTES:
            return
        self.webtoon_pixmap_cache[key] = pixmap
        self.webtoon_pixmap_cache_order.append(key)
        self.webtoon_pixmap_cache_bytes += cost
        while self.webtoon_pixmap_cache_order and (
            len(self.webtoon_pixmap_cache_order) > 48
            or self.webtoon_pixmap_cache_bytes > WEBTOON_CACHE_LIMIT_BYTES
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

    def queue_viewer_decode(self, label, path, generation, priority=20, preload=False):
        path = Path(path)
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
        width = max(320, min(4096, int(area.width() * max(1.0, self.zoom_factor))))
        height = max(240, min(4096, int(area.height() * max(1.0, self.zoom_factor))))
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            width = max(WEBTOON_MIN_WIDTH, min(WEBTOON_MAX_WIDTH, int(self.webtoon_target_width or width)))
            height = 4096
        task = ImageDecodeTask(
            generation,
            path,
            (width, height),
            thread_priority=QThread.IdlePriority if preload else QThread.LowPriority,
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
                label.setFixedSize(scaled.size())
            else:
                label.setMinimumHeight(0)
            label.setText("")
            label.setPixmap(scaled)
            self.opening_placeholder = QPixmap()
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

    def process_next_viewer_preload(self):
        if not self.viewer_preload_queue:
            self.viewer_preload_timer.stop()
            return
        path = self.viewer_preload_queue.pop(0)
        self.viewer_preload_queued.discard(str(path))
        self.queue_viewer_decode(None, path, self.render_generation, priority=-10, preload=True)
        if self.viewer_preload_queue:
            profile = PERFORMANCE_PROFILES.get(
                self.settings.get("performance_profile", "balanced"), PERFORMANCE_PROFILES["balanced"]
            )
            self.viewer_preload_timer.start(profile["thumbnail_gap_ms"])

    def show_current(self, reset=False):
        transition_pixmaps = self.transition_pixmaps()
        self.cancel_pending_decodes()
        self.render_generation += 1
        generation = self.render_generation
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

        self.clear_grid()
        self.active_display_path = self.focus_path_for_group(group)
        if not group:
            label = QLabel("No media")
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_StyledBackground, True)
            label.setStyleSheet("background: #050505; color: #f0f0f0;")
            self.grid.addWidget(label, 0, 0)
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
            for item in prepared_items or []:
                col = item["col"]
                path = item["path"]
                if item["active_video"]:
                    primary = not primary_video_assigned
                    primary_video_assigned = True
                    frame = self.video_frame if primary else self.create_video_frame()
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
                    task = ImageDecodeTask(generation, path, (512, 512), video_shell=True)
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
            self.corner_filename_label,
        ):
            label.setText(name)
            label.setToolTip(name)

    def schedule_image_update(self, generation=None):
        if not self.is_active_viewer():
            return
        generation = self.render_generation if generation is None else generation
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.reset_webtoon_target_width()
            self.schedule_webtoon_visible_update(generation)
            return
        QTimer.singleShot(0, lambda g=generation: self.update_image_labels(g))
        QTimer.singleShot(40, lambda g=generation: self.update_image_labels(g))

    def schedule_webtoon_visible_update(self, generation=None):
        generation = self.render_generation if generation is None else generation
        QTimer.singleShot(0, lambda g=generation: self.update_webtoon_visible_images(g))
        QTimer.singleShot(60, lambda g=generation: self.update_webtoon_visible_images(g))

    def image_pixel_size(self, path):
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
        frame = QFrame()
        frame.setObjectName("videoFrame")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet("background: #000;")
        frame.setAutoFillBackground(True)
        frame.setFocusPolicy(Qt.StrongFocus)
        frame.setMouseTracking(True)
        frame.installEventFilter(self)
        return frame

    def _show_video_status(self, frame, text):
        try:
            label = frame.findChild(QLabel, "videoStatusLabel")
            if label is None:
                label = QLabel(frame)
                label.setObjectName("videoStatusLabel")
                label.setAlignment(Qt.AlignCenter)
                label.setAttribute(Qt.WA_StyledBackground, True)
                label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        if primary and self.media_player is None and self.vlc_instance is not None:
            try:
                self.media_player = self._acquire_video_player()
            except Exception:
                self.media_player = None
        player = self.media_player if primary else self._acquire_video_player()
        if not player:
            self._show_video_status(frame, "Video player unavailable\n" + Path(path).name)
            return
        try:
            if primary:
                self.video_path = Path(path)
                self.video_finished = False
                self.video_stopped_by_user = False
            else:
                self.extra_media_players.append(player)
            frame.setVisible(True)
            frame.show()
            frame.raise_()
            frame.repaint()
            self._hide_video_status(frame)
            media = self.vlc_instance.media_new(str(path))
            player.set_media(media)
            player.set_hwnd(int(frame.winId()))
            self._configure_media_player(player)
            self._attach_video_end_event(player, path, frame, primary)
            result = player.play()
            if result is not None and int(result) < 0:
                raise RuntimeError("libVLC rejected playback")
            player.audio_set_volume(self.volume_slider.value())
            if primary:
                self.video_timer.start(250)
                frame.setFocus()
        except Exception:
            if primary:
                self.video_path = None
            else:
                try:
                    self.extra_media_players.remove(player)
                except ValueError:
                    pass
                try:
                    player.release()
                except Exception:
                    pass
            self._show_video_status(frame, "Could not play video\n" + Path(path).name)

    def _acquire_video_player(self):
        if self.video_standby_players:
            player = self.video_standby_players.pop(0)
        else:
            player = self.vlc_instance.media_player_new()
        self._configure_media_player(player)
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
    def _video_cleanup_worker(work_queue):
        """Run potentially blocking libVLC stop/release calls off the GUI thread."""
        while True:
            player = work_queue.get()
            if player is None:
                work_queue.task_done()
                return
            try:
                try:
                    player.stop()
                except Exception:
                    pass
                try:
                    player.set_media(None)
                except Exception:
                    pass
                try:
                    player.release()
                except Exception:
                    pass
            finally:
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
        """Silence and detach a player without waiting for libVLC stop()."""
        try:
            player.audio_set_volume(0)
        except Exception:
            pass
        try:
            player.set_pause(1)
        except Exception:
            pass
        try:
            player.set_hwnd(0)
        except Exception:
            pass

    def _take_active_video_players(self):
        self.movie = None
        self.stop_animated_image()
        self.pending_video_requests = []
        self.video_playback_token += 1
        self._video_end_callback = None
        for token, state in list(getattr(self, "video_slot_states", {}).items()):
            try:
                state["player"].event_manager().event_detach(vlc.EventType.MediaPlayerEndReached)
            except Exception:
                pass
        self.video_slot_states = {}
        self.video_end_callbacks = {}
        self.video_stopped_by_user = True
        self.video_finished = False
        if hasattr(self, "video_timer"):
            self.video_timer.stop()
        players = self._unique_video_players(
            [self.media_player, *getattr(self, "extra_media_players", [])]
        )
        self.extra_media_players = []
        self.media_player = None
        try:
            self.video_frame.hide()
        except RuntimeError:
            pass
        self.video_path = None
        if hasattr(self, "seek_slider"):
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)
            self.time_label.setText("00:00 / 00:00")
        return players

    def _queue_video_cleanup(self, players):
        for player in self._unique_video_players(players):
            if self.video_cleanup_closed:
                try:
                    player.stop()
                except Exception:
                    pass
                try:
                    player.set_media(None)
                except Exception:
                    pass
                try:
                    player.release()
                except Exception:
                    pass
                continue
            self.video_cleanup_queue.put(player)

    def retire_media_for_transition(self):
        """Detach immediately, then retire old players without blocking navigation."""
        players = self._take_active_video_players()
        for player in players:
            self._quiesce_video_player(player)
        self._queue_video_cleanup(players)

    def stop_media(self):
        """Fully stop active players for explicit Stop or Explorer return."""
        players = self._take_active_video_players()
        players.extend(self.video_standby_players)
        self.video_standby_players = []
        for player in players:
            # Detaching the native surface before stop substantially reduces
            # the Windows/libVLC wait while preserving the no-stale-HWND fix.
            self._quiesce_video_player(player)
            try:
                player.stop()
            except Exception:
                pass
            try:
                player.set_media(None)
            except Exception:
                pass
            try:
                player.release()
            except Exception:
                pass

    def shutdown_video_cleanup(self):
        if self.video_cleanup_closed:
            return
        self.video_cleanup_closed = True
        self.video_cleanup_queue.put(None)

    def deactivate(self):
        self.cancel_pending_decodes()
        self.render_generation += 1
        self.decode_pool.clear()
        self.preload_decode_pool.clear()
        self.decode_inflight.clear()
        self.stop_webtoon_auto_scroll()
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
        }

    def try_start_animated_image(self, label, path):
        path = Path(path)
        if path.suffix.lower() not in (".gif", ".webp", ".apng"):
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
            self.queue_viewer_decode(label, path, self.render_generation, priority=10)

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

    def visible_webtoon_indices(self, margin=2):
        if not self.webtoon_scroll or not self.labels:
            return []
        viewport_top = self.webtoon_scroll.verticalScrollBar().value()
        anchor = 0
        for idx, (label, _) in enumerate(self.labels):
            top = label.y()
            bottom = top + max(1, label.height())
            if bottom >= viewport_top:
                anchor = idx
                break
        start = max(0, anchor - margin)
        end = min(len(self.labels) - 1, anchor + margin)
        return list(range(start, end + 1))

    def update_webtoon_visible_images(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        margin = 4 if self.webtoon_auto_scroll_active else 2
        for idx in self.visible_webtoon_indices(margin=margin):
            if idx in self.webtoon_loaded:
                continue
            label, path = self.labels[idx]
            if label.property("decode_generation") == self.render_generation:
                continue
            label.setProperty("decode_generation", self.render_generation)
            self.queue_viewer_decode(label, path, self.render_generation, priority=10)

    def load_next_webtoon_idle_image(self):
        if self.viewer_mode not in ("webtoon", "webtoon_vertical") or not self.labels:
            self.webtoon_idle_timer.stop()
            return
        self.update_webtoon_visible_images(self.render_generation)
        visible_margin = 4 if self.webtoon_auto_scroll_active else 2
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
            base = pix.size()
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
        self.corner_filename_label.adjustSize()
        self.corner_filename_label.setGeometry(margin, margin, self.corner_filename_label.sizeHint().width(), self.corner_filename_label.sizeHint().height())
        self.corner_filename_label.setVisible(bool(self.current_file_name()) and not self.window().isFullScreen())
        if getattr(self, "current_is_video", False):
            hot_h = max(90, video_h + margin * 2)
            self.input_layer.setGeometry(0, max(0, self.central.height() - hot_h), self.central.width(), hot_h)
            self.input_layer.show()
            self.input_layer.raise_()
        else:
            self.input_layer.hide()
        self.viewer_overlay.raise_()
        self.rotation_overlay.raise_()
        self.video_overlay.raise_()
        self.webtoon_auto_scroll_overlay.raise_()
        self.corner_filename_label.raise_()

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

    def next_media(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(1)
            return
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        new_index = min(len(self.items) - 1, self.index + step)
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
        self.index = (self.index + step) % len(self.items)
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
        new_index = max(0, self.index - step)
        if new_index == self.index:
            return
        self.index = new_index
        self.show_current(reset=not self.zoom_locked)

    def first_media(self):
        if self.index == 0:
            return
        self.index = 0
        self.show_current(reset=not self.zoom_locked)

    def last_media(self):
        last_index = max(0, len(self.items) - 1)
        if self.index == last_index:
            return
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

    def zoom_in(self):
        self.force_manual_for_zoom()
        self.zoom_factor *= 1.15
        self.update_manual_zoom_text()
        self.schedule_image_update()

    def zoom_out(self):
        self.force_manual_for_zoom()
        self.zoom_factor /= 1.15
        self.update_manual_zoom_text()
        self.schedule_image_update()

    def rotate_right(self):
        self.rotation = (self.rotation + 90) % 360
        self.update_image_labels()

    def rotate_left(self):
        self.rotation = (self.rotation - 90) % 360
        self.update_image_labels()

    def reset_rotation(self):
        self.rotation = 0
        self.update_image_labels()

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
            if self.video_path is not None and (self.video_stopped_by_user or self.video_finished):
                media = self.vlc_instance.media_new(str(self.video_path))
                self.media_player.set_media(media)
                self.media_player.set_hwnd(int(self.video_frame.winId()))
            self.video_finished = False
            self.video_stopped_by_user = False
            self.media_player.set_time(0)
            self.media_player.play()
            self.media_player.audio_set_volume(self.volume_slider.value())
            for state in self.video_slot_states.values():
                if state.get("primary") and state.get("player") is self.media_player:
                    state["ended"] = False
                    state["restarting"] = False
            self.video_timer.start(250)
        except Exception:
            pass

    def set_video_volume(self, value):
        if self.media_player:
            try:
                self.media_player.audio_set_volume(value)
            except Exception:
                pass

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
        if not self.media_player or self._seeking_video:
            return
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
        self.stop_webtoon_auto_scroll()
        self.stop_media()
        self.shutdown_video_cleanup()
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
        self.explorer_geometry_before_viewer = None
        self.history = []
        self.history_index = -1
        self.entries = []
        self.archive_tempdirs = []
        self.archive_pool = QThreadPool(self)
        self.archive_pool.setMaxThreadCount(1)
        self.archive_task_refs = set()
        self.display_path = str(self.current_folder)
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.folder_cache = {}
        self.current_snapshot_key = ""
        self.explorer_dirty = False
        self.folder_scan_generation = 0
        self.folder_scan_pool = QThreadPool(self)
        self.folder_scan_pool.setMaxThreadCount(1)
        self.folder_scan_pool.setThreadPriority(QThread.LowPriority)
        self.folder_scan_task_refs = set()
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
        self.thumbnail_idle_cursor = 0
        self.thumbnail_task_refs = set()
        self.thumbnail_queue = []
        self.thumbnail_queue_set = set()
        self.thumbnail_cycle_started = False
        self.generic_media_icon = None
        self.entry_by_path = {}
        self.view_render_keys = {"list": None, "details": None}
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
            QTreeView::item, QListWidget::item, QTableWidget::item {{
                border: none; padding: 4px; border-radius: 5px;
            }}
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
        self.folder_cache[key] = FolderSnapshot(folder, entries, signature)
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
        self.tree_sync_timer.start(180)
        startup = str(self.startup_media_path)
        self.media_paths = [startup]
        self.update_current_tab()

    def start_startup_media_scan(self):
        if not self.startup_media_path:
            return
        if self.startup_media_scan_timer.isActive():
            self.startup_media_scan_timer.stop()
        try:
            self.startup_media_scan_iter = iter(Path(self.current_folder).iterdir())
        except (PermissionError, FileNotFoundError, OSError):
            self.startup_media_scan_iter = None
            return
        self.startup_media_scan_paths = []
        self.startup_media_scan_seen = set()
        self.startup_media_scan_target = str(self.startup_media_path)
        self.startup_media_scan_timer.start()

    def process_startup_media_scan(self):
        if self.startup_media_scan_iter is None:
            self.startup_media_scan_timer.stop()
            return
        changed = False
        finished = False
        count = 0
        started = time.monotonic()
        while count < 160 and time.monotonic() - started < 0.008:
            try:
                child = next(self.startup_media_scan_iter)
            except StopIteration:
                finished = True
                break
            except (PermissionError, FileNotFoundError, OSError):
                continue
            count += 1
            try:
                if not child.is_file() or not is_media(child):
                    continue
            except OSError:
                continue
            path_text = str(child)
            if path_text in self.startup_media_scan_seen:
                continue
            self.startup_media_scan_seen.add(path_text)
            self.startup_media_scan_paths.append(path_text)
            changed = True
        if changed or finished:
            self.apply_startup_media_scan_paths(final=finished)
        if finished:
            self.startup_media_scan_timer.stop()
            self.startup_media_scan_iter = None

    def apply_startup_media_scan_paths(self, final=False):
        target = self.startup_media_scan_target or (str(self.startup_media_path) if self.startup_media_path else "")
        if not target:
            return
        paths = list(self.startup_media_scan_paths)
        if target not in paths:
            paths.insert(0, target)
        if paths == self.media_paths:
            return
        current = target
        if self.viewer and self.viewer.items:
            current = str(self.viewer.items[self.viewer.index])
        self.media_paths = paths
        if not self.viewer:
            return
        self.viewer.items = [Path(path) for path in self.media_paths if is_media(path)]
        if not self.viewer.items:
            return
        if current in self.media_paths:
            self.viewer.index = self.media_paths.index(current)
        else:
            self.viewer.index = min(self.viewer.index, len(self.viewer.items) - 1)
        if final and self.viewer.viewer_mode in ("webtoon", "webtoon_vertical"):
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

    def load_folder(self, folder, add_history=True, display_path=None, force=False, sync_tree=True):
        folder = Path(folder)
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.current_folder = folder
        self.display_path = display_path or str(folder)
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

    def sync_tree_selection(self):
        path = self.pending_tree_path
        if not path or path != str(self.current_folder):
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
        self.folder_cache[snapshot_key] = FolderSnapshot(Path(folder), list(entries), signature)
        self.apply_folder_entries(list(entries), snapshot_key, lightweight=lightweight)

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
        self.render_entries(entries, lightweight=lightweight)

    def render_entries(self, entries=None, lightweight=True, preserve_scroll=False):
        entries = list(self.entries if entries is None else entries)
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
            for entry in entries:
                item = QListWidgetItem(entry.display_name)
                item.setData(Qt.UserRole, str(entry.path))
                item.setToolTip(str(entry.path))
                item.setIcon(self.entry_icon(entry, lightweight=lightweight))
                color = type_color(entry.path, entry.is_dir)
                if color is not None:
                    item.setBackground(color)
                self.list.addItem(item)
                self.list_item_by_path[str(entry.path)] = item
        self.view_render_keys[view_name] = render_key
        self.list.setUpdatesEnabled(True)
        self.details.setUpdatesEnabled(True)
        if preserve_scroll:
            self.list.verticalScrollBar().setValue(list_scroll)
            self.details.verticalScrollBar().setValue(details_scroll)
        self.update_command_buttons()
        if lightweight:
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
        self.performance_profile = dict(profile)
        self.thumbnail_start_ms = int(profile["thumbnail_start_ms"])
        self.thumbnail_gap_ms = int(profile["thumbnail_gap_ms"])
        self.thumbnail_pool.setMaxThreadCount(int(profile["thumbnail_workers"]))
        self.thumbnail_pool.setThreadPriority(QThread.IdlePriority)
        if hasattr(self, "thumbnail_timer") and self.thumbnail_timer.isActive():
            self.thumbnail_timer.stop()
            if self.thumbnail_queue and not self.thumbnail_paused:
                self.thumbnail_timer.start(self.thumbnail_gap_ms)

    def schedule_settings_save(self):
        self.settings_save_timer.start()

    def current_render_key(self, entries=None):
        entries = self.entries if entries is None else entries
        folder_key = self.current_snapshot_key or os.path.normcase(os.path.abspath(str(self.current_folder)))
        return (
            folder_key,
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
            self.thumbnail_queue = []
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
        ordered = list(dict.fromkeys(priority_paths + self.thumbnail_queue + media_order))
        self.thumbnail_queue = [
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
        ]
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
            for row in range(self.list.count()):
                item = self.list.item(row)
                if self.list.visualItemRect(item).intersects(rect):
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
            or self.thumbnail_cache_bytes > THUMBNAIL_CACHE_LIMIT_BYTES
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
            return item.display_name.lower()

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
            "type": lambda x: (x.kind, x.path.suffix.lower(), x.path.name.lower()),
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
            watchable = not self.virtual_unc_server and not folder_text.startswith("\\\\") and self.safe_is_dir(self.current_folder)
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

    def open_location(self, text, add_history=True):
        text = str(text).strip().strip('"')
        if not text:
            return False
        server = unc_server_name(text)
        if server:
            return self.load_unc_server(server, add_history=add_history)
        if "::" in str(text):
            archive = str(text).split("::", 1)[0]
            return self.open_archive(archive, add_history=add_history)
        path = Path(text)
        if path.is_file() and is_archive(path):
            return self.open_archive(path, add_history=add_history)
        return self.load_folder(path, add_history=add_history)

    def load_unc_server(self, server, add_history=True):
        display = f"\\\\{server}"
        shares = unc_share_paths(server)
        if not shares:
            QMessageBox.warning(self, "Invalid path", f"Cannot open SMB path or no shared folders were found:\n{display}")
            return False
        self.virtual_unc_server = server
        self.virtual_entries = shares
        self.display_path = display
        self.path_edit.setText(display)
        if add_history:
            self.history = self.history[: self.history_index + 1]
            self.history.append(display)
            self.history_index = len(self.history) - 1
        self.populate_list()
        self.update_current_tab()
        return True

    def open_path(self, path):
        p = Path(path)
        if p.is_dir():
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

    def open_archive(self, archive_path, add_history=True):
        archive_path = Path(archive_path)
        if not archive_path.exists():
            QMessageBox.warning(self, "Archive not found", f"Cannot open:\n{archive_path}")
            return False
        task = ArchiveExtractTask(archive_path, add_history=add_history)
        self.archive_task_refs.add(task)
        task.signals.finished.connect(lambda result, ref=task: self.archive_ready(result, ref))
        self.archive_pool.start(task)
        return True

    def archive_ready(self, result, task):
        self.archive_task_refs.discard(task)
        if self.closing or result.get("cancelled"):
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
            return
        if not result.get("count") or result.get("tempdir") is None:
            QMessageBox.information(self, "Archive", "No image files found in this zip.")
            return
        self.archive_tempdirs.append(result["tempdir"])
        root = Path(result["root"])
        snapshot_key = os.path.normcase(os.path.abspath(str(root)))
        self.folder_cache[snapshot_key] = FolderSnapshot(
            root,
            list(result.get("entries") or []),
            self.folder_signature(root),
        )
        self.load_folder(
            root,
            add_history=result.get("add_history", True),
            display_path=f"{archive_path}::",
            force=False,
        )

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
        copied = []
        for source in sources:
            if not source.exists():
                continue
            try:
                target = unique_copy_target(target_folder / source.name)
                if source.is_dir() and path_contains(source, target):
                    QMessageBox.warning(self, "Paste failed", f"Cannot paste a folder into itself:\n{source}")
                    continue
                if move_mode:
                    shutil.move(str(source), str(target))
                elif source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
                copied.append(str(target))
            except Exception as exc:
                QMessageBox.warning(self, "Paste failed", f"Could not paste:\n{source}\n\n{exc}")
                break
        if move_mode:
            self.cut_clipboard_paths = set()
        self.invalidate_folder_cache(target_folder)
        self.populate_list(force=True)
        if active_viewer and self.viewer:
            current = str(self.viewer.items[self.viewer.index]) if self.viewer.items else ""
            self.viewer.items = [Path(p) for p in self.media_paths]
            if self.viewer.items:
                if current in self.media_paths:
                    self.viewer.index = self.media_paths.index(current)
                else:
                    self.viewer.index = min(self.viewer.index, len(self.viewer.items) - 1)
                self.viewer.show_current(reset=False)
            self.viewer.setFocus()
        elif copied:
            self.select_path(copied[0])

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
        self.current_folder = path.parent
        self.startup_media_path = path
        self.prepare_startup_media_folder()
        if self.open_viewer_for(path):
            QTimer.singleShot(0, self.start_startup_media_scan)
            return True
        return False

    def open_viewer_for(self, path):
        if not self.media_paths:
            return False
        path = str(path)
        try:
            idx = self.media_paths.index(path)
        except ValueError:
            idx = 0
        self.pause_thumbnail_work(cancel_pending=True)
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
        self.viewer.item_signatures = {str(entry.path): (entry.size, entry.mtime) for entry in self.entries}
        thumbnail_icon = self.thumbnail_cache.get(path)
        self.viewer.opening_placeholder = (
            thumbnail_icon.pixmap(QSize(512, 512)) if thumbnail_icon is not None else QPixmap()
        )
        self.viewer.update_mode_button()
        self.nav_toolbar.hide()
        self.main_stack.setCurrentWidget(self.viewer)
        if self.settings.get("viewer_start_mode", "fullscreen") == "window":
            self.showNormal()
            reader = QImageReader(path)
            source_size = reader.size()
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

    def delete_from_viewer(self, path):
        if not self.viewer:
            return
        path = Path(path)
        deleted_path = str(path)
        deleted_index = self.viewer.index
        if path.exists():
            try:
                send_to_recycle_bin(path)
            except Exception:
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
        visible_count = self.details.rowCount() if self.view_combo.currentText() == "details" else self.list.count()
        if not self.entries and visible_count == 0 and self.media_paths:
            immediate_entries = []
            for media_path in self.media_paths:
                path = Path(media_path)
                if path.parent != Path(self.current_folder) or not is_media(path):
                    continue
                try:
                    stat = path.stat()
                    immediate_entries.append(MediaItem(path, False, size=int(stat.st_size), mtime=float(stat.st_mtime)))
                except OSError:
                    immediate_entries.append(MediaItem(path, False))
            if immediate_entries:
                self.entries = self.sorted_entries(
                    immediate_entries,
                    self.settings.get("sort_mode", "name"),
                    self.settings.get("sort_ascending", True),
                )
                self.render_entries(self.entries, lightweight=True)
                visible_count = self.details.rowCount() if self.view_combo.currentText() == "details" else self.list.count()
                self.populate_list(lightweight=True, force=False, preserve_existing=True)
        if refresh or self.explorer_dirty:
            self.populate_list(lightweight=True, force=True, preserve_existing=True)
        elif self.entries:
            if visible_count == 0:
                self.render_entries(self.entries, lightweight=True)
        if current:
            self.select_path(current, scroll=False)
        self.thumbnail_paused = True
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
        parent = self.current_folder.parent
        if parent != self.current_folder:
            self.load_folder(parent)

    def go_back(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.open_location(self.history[self.history_index], add_history=False)

    def go_forward(self):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self.open_location(self.history[self.history_index], add_history=False)

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
        for path in paths:
            try:
                send_to_recycle_bin(path)
            except Exception:
                QMessageBox.warning(self, "Delete failed", f"Could not move to recycle bin:\n{path}")
        self.invalidate_folder_cache(self.current_folder)
        self.populate_list(force=True)

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
        ):
            if pool is not None:
                pool.clear()
        if self.viewer:
            self.viewer.deactivate()
            self.viewer.decode_pool.clear()
            self.viewer.preload_decode_pool.clear()
        for tempdir in getattr(self, "archive_tempdirs", []):
            try:
                tempdir.cleanup()
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
    existing = [Path(path) for path in paths if Path(path).exists()]
    if not existing:
        return
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in existing])
    mime.setText("\n".join(str(path) for path in existing))
    QApplication.clipboard().setMimeData(mime)


def windows_shell_thumbnail_image(path, size=512):
    if sys.platform != "win32":
        return None
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
        factory = ctypes.c_void_p()
        shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHCreateItemFromParsingName.restype = ctypes.HRESULT
        if shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(iid), ctypes.byref(factory)) < 0 or not factory:
            return None
        obj = ctypes.cast(factory, ctypes.POINTER(IShellItemImageFactory))
        hbitmap = wintypes.HBITMAP()
        flags = 0x1
        hr = obj.contents.lpVtbl.contents.GetImage(factory, SIZE(int(size), int(size)), flags, ctypes.byref(hbitmap))
        obj.contents.lpVtbl.contents.Release(factory)
        if hr < 0 or not hbitmap:
            return None

        bitmap = BITMAP()
        gdi32.GetObjectW(hbitmap, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        width = int(bitmap.bmWidth)
        height = int(bitmap.bmHeight)
        if width <= 0 or height <= 0:
            gdi32.DeleteObject(hbitmap)
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
            return None
        image = QImage(bytes(buffer), width, height, QImage.Format_ARGB32).copy()
        return image if not image.isNull() else None
    except Exception:
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
