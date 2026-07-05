import json
import os
import shutil
import subprocess
import sys
import ctypes
import tempfile
import time
import zipfile
from io import BytesIO
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Portable Photo Viewer"
INSTANCE_SERVER_NAME = "StynerPark_PortableMediaViewer_Instance"
DEFAULT_LAST_FOLDER_SETTING = r"%USERPROFILE%\Documents"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUN_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
SETTINGS_PATH = RUN_DIR / "settings.json"
VLC_DIR = RUN_DIR / "vlc"
if not VLC_DIR.exists():
    VLC_DIR = BASE_DIR / "vlc"

if VLC_DIR.exists():
    os.environ["PATH"] = str(VLC_DIR) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(VLC_DIR))

DEFAULT_START_FOLDER = Path.home() / "Documents"
if not DEFAULT_START_FOLDER.exists():
    DEFAULT_START_FOLDER = Path.home()

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QAbstractNativeEventFilter, QDir, QEvent, QFileInfo, QFileSystemWatcher, QMimeData, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QImageReader, QIntValidator, QKeySequence, QMovie, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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


DEFAULT_SETTINGS = {
    "last_folder": DEFAULT_LAST_FOLDER_SETTING,
    "view_mode": "large",
    "sort_mode": "name_asc",
    "viewer_mode": "single",
    "viewer_step": "page",
    "default_fit": "fit_height",
    "zoom_locked": True,
    "theme": "dark",
    "instance_mode": "multi",
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
        "zoom_in": ["Ctrl++"],
        "zoom_out": ["Ctrl+-"],
        "fit_height": ["H"],
        "fit_width": ["W"],
        "actual_size": ["1"],
        "toggle_zoom_lock": ["L"],
        "toggle_play": [],
        "rotate_right": ["R"],
        "rotate_left": ["Shift+R"],
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


def type_color(path):
    if Path(path).is_dir() or is_archive(path):
        return None
    ext = Path(path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".jfif"}:
        return QColor("#3f4320")
    if ext == ".png":
        return QColor("#4a2f2a")
    if ext == ".webp":
        return QColor("#34391c")
    if ext == ".gif":
        return QColor("#143d1d")
    if ext in {".mp4", ".avi", ".mkv", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".mpeg", ".mpg", ".ts", ".m2ts", ".3gp", ".ogv"}:
        return QColor("#173d46")
    if ext in {".bmp", ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".pbm", ".pnm"}:
        return QColor("#3f3320")
    return QColor("#303030")


def fmt_modified(path):
    try:
        from datetime import datetime
        return datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def app_icon():
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


class ThumbList(QListWidget):
    openRequested = Signal(str)
    previewRequested = Signal(str)
    copyRequested = Signal()
    deleteRequested = Signal()
    pasteRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemDoubleClicked.connect(self._open_item)
        self.itemSelectionChanged.connect(self._preview_selected)
        self.icon_provider = QFileIconProvider()
        self.setSpacing(8)
        self.setStyleSheet("""
            QListWidget { background: #050505; }
            QListWidget::item { background: #050505; color: #f0f0f0; padding: 4px; }
            QListWidget::item:selected { background: #8f72b8; color: #ffffff; border: 1px solid #c7b5e8; }
            QListWidget::item:hover { background: #303030; }
        """)

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
        "Date Taken",
        "Modified Date",
        "Image Properties",
        "Caption",
        "Rating",
        "Tagged",
    ]

    SORT_KEYS = {
        0: "name",
        1: "size",
        2: "type",
        3: "date_taken",
        4: "modified",
        5: "properties",
        6: "caption",
        7: "rating",
        8: "tagged",
    }

    def __init__(self):
        super().__init__(0, len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(self.HEADERS)):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.cellDoubleClicked.connect(self._open_row)
        self.itemSelectionChanged.connect(self._preview_selected)
        self.horizontalHeader().sectionClicked.connect(self._sort_clicked)
        self.sort_column = 0
        self.sort_ascending = True
        self.setStyleSheet("""
            QTableWidget::item:selected { background: #8f72b8; color: #ffffff; }
        """)

    def load_entries(self, entries, icon_provider, make_icon, lightweight=False):
        self.setRowCount(0)
        for row, entry in enumerate(entries):
            self.insertRow(row)
            values = self.row_values(entry, lightweight=lightweight)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(entry.path))
                if col == 0:
                    item.setIcon(icon_provider.icon(QFileInfo(str(entry.path))) if lightweight else make_icon(entry))
                if col == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                color = type_color(entry.path)
                if color is not None:
                    item.setBackground(color)
                self.setItem(row, col, item)

    def row_values(self, entry, lightweight=False):
        if entry.is_dir:
            return [entry.display_name, "", "Folder", "", fmt_modified(entry.path), "", "", "", ""]
        size_kb = entry.path.stat().st_size // 1024
        if lightweight:
            kind = "Video" if is_video(entry.path) else entry.path.suffix.upper().strip(".")
            return [
                entry.display_name,
                f"{size_kb:,}",
                kind,
                "",
                fmt_modified(entry.path),
                "",
                "",
                "",
                "No",
            ]
        return [
            entry.display_name,
            f"{size_kb:,}",
            image_type(entry.path),
            "",
            fmt_modified(entry.path),
            image_properties(entry.path),
            "",
            "",
            "No",
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
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(160)
        self.setFrameShape(QFrame.StyledPanel)
        self.movie = None

    def show_path(self, path):
        self.movie = None
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
        pix = QPixmap(path)
        if pix.isNull():
            self.setText(file_label(path))
            self.setPixmap(QPixmap())
        else:
            self.setText("")
            self.setPixmap(pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)


class PannableImageLabel(QLabel):
    def __init__(self):
        super().__init__()
        self._viewer_pixmap = QPixmap()
        self._pan_offset = QPoint(0, 0)
        self._dragging = False
        self._drag_start_pos = QPoint(0, 0)
        self._drag_start_offset = QPoint(0, 0)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

    def setText(self, text):
        if text:
            self._viewer_pixmap = QPixmap()
            self._pan_offset = QPoint(0, 0)
            self.unsetCursor()
        super().setText(text)

    def setPixmap(self, pixmap):
        self._viewer_pixmap = QPixmap(pixmap) if pixmap is not None and not pixmap.isNull() else QPixmap()
        super().setPixmap(QPixmap())
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
        if self._dragging:
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.can_pan():
            self._dragging = True
            self._drag_start_pos = event.position().toPoint()
            self._drag_start_offset = QPoint(self._pan_offset)
            self.update_pan_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            delta = event.position().toPoint() - self._drag_start_pos
            self._pan_offset = self.clamped_pan_offset(self._drag_start_offset + delta)
            self.update()
            event.accept()
            return
        self.update_pan_cursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
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
    pasteRequested = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.items = []
        self.index = 0
        self.zoom_factor = 1.0
        self.fit_mode = settings.get("default_fit", "fit_height")
        self.zoom_locked = settings.get("zoom_locked", True)
        self.viewer_mode = settings.get("viewer_mode", "single")
        if self.viewer_mode == "webtoon" or str(self.viewer_mode).startswith("webtoon_") and self.viewer_mode != "webtoon_vertical":
            self.viewer_mode = "webtoon_vertical"
        self.step_mode = settings.get("viewer_step", "page")
        self.rotation = 0
        self.media_player = None
        self.vlc_instance = None
        self.extra_media_players = []
        self.movie = None
        self._app_filter_installed = False
        self._seeking_video = False
        self.video_path = None
        self.video_finished = False
        self.video_stopped_by_user = False
        self.webtoon_scroll = None
        self.webtoon_loaded = set()
        self.webtoon_idle_index = 0
        self.webtoon_target_width = None
        self.webtoon_pixmap_cache = {}
        self.webtoon_pixmap_cache_order = []
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

        self.setWindowTitle(APP_NAME + " - Viewer")
        self.setMinimumSize(900, 640)
        self._build_ui()
        self._build_shortcuts()
        self._init_vlc()

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
            #viewerOverlay { background: rgba(18,20,24,220); border: 1px solid rgba(255,255,255,60); border-radius: 6px; color: white; }
            QPushButton, QComboBox, QToolButton, QLineEdit { background: #343842; color: #f2f2f2; border: 1px solid #5b6270; padding: 5px 10px; }
            QPushButton:checked { background: #2f7dd3; border-color: #85bcff; color: white; font-weight: 700; }
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
            #cornerFilenameLabel { background: rgba(12,14,18,210); color: white; border: 1px solid rgba(255,255,255,55); border-radius: 5px; padding: 6px 10px; }
        """)
        self.corner_filename_label.hide()

        self.rotation_overlay = QFrame(self.central)
        self.rotation_overlay.setObjectName("rotationOverlay")
        self.rotation_overlay.setStyleSheet("""
            #rotationOverlay { background: rgba(18,20,24,220); border: 1px solid rgba(255,255,255,60); border-radius: 6px; color: white; }
            QPushButton { background: #343842; color: #f2f2f2; border: 1px solid #5b6270; padding: 5px 12px; }
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
            #videoOverlay { background: rgba(12,14,18,230); border: 1px solid rgba(255,255,255,70); border-radius: 6px; color: white; }
            QPushButton { background: #343842; color: #f2f2f2; border: 1px solid #5b6270; padding: 5px 10px; }
            QPushButton:checked { background: #2f7dd3; border-color: #85bcff; color: white; font-weight: 700; }
            QSlider::groove:horizontal { height: 5px; background: #555b66; border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #d7e9ff; }
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
        video_layout.addWidget(self.time_label)
        video_layout.addWidget(self.seek_slider, 1)
        video_layout.addWidget(QLabel("Vol"))
        video_layout.addWidget(self.volume_slider)
        self.video_overlay.hide()

        self.webtoon_auto_scroll_overlay = QFrame(self.central)
        self.webtoon_auto_scroll_overlay.setObjectName("webtoonAutoScrollOverlay")
        self.webtoon_auto_scroll_overlay.setStyleSheet("""
            #webtoonAutoScrollOverlay { background: rgba(12,14,18,225); border: 1px solid rgba(255,255,255,70); border-radius: 6px; color: white; }
            QPushButton, QLineEdit { background: #343842; color: #f2f2f2; border: 1px solid #5b6270; padding: 5px 8px; }
            QPushButton:checked { background: #2f7dd3; border-color: #85bcff; color: white; font-weight: 700; }
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
            "actual_size": lambda: self.set_fit_mode("actual"),
            "toggle_zoom_lock": self.toggle_zoom_lock,
            "toggle_play": self.toggle_play,
            "toggle_fullscreen": self.toggle_fullscreen,
            "rotate_right": self.rotate_right,
            "rotate_left": self.rotate_left,
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
        for seq, callback in [
            (Qt.Key_Plus, self.zoom_in),
            (Qt.Key_Equal, self.zoom_in),
            (Qt.Key_Minus, self.zoom_out),
        ]:
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(callback)
        self.webtoon_auto_scroll_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self.webtoon_auto_scroll_shortcut.setContext(Qt.ApplicationShortcut)
        self.webtoon_auto_scroll_shortcut.activated.connect(self.toggle_webtoon_auto_scroll)

    def _init_vlc(self):
        if vlc is None:
            return
        try:
            self.vlc_instance = vlc.Instance("--quiet")
            self.media_player = self.vlc_instance.media_player_new()
            try:
                self.media_player.video_set_mouse_input(False)
                self.media_player.video_set_key_input(False)
            except Exception:
                pass
            self.media_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self._video_ended)
        except Exception:
            self.media_player = None

    def _video_ended(self, event):
        self.video_finished = True

    def load(self, items, index):
        self.items = [Path(p) for p in items if is_media(p)]
        self.index = max(0, min(index, len(self.items) - 1))
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
        self.stop_media()
        self.stop_webtoon_auto_scroll()
        self.webtoon_scroll = None
        self.webtoon_loaded = set()
        self.webtoon_idle_index = 0
        if hasattr(self, "webtoon_idle_timer"):
            self.webtoon_idle_timer.stop()
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
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
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
        self.viewer_pixmap_cache[key] = pix
        self.viewer_pixmap_cache_order.append(key)
        while len(self.viewer_pixmap_cache_order) > 64:
            old_key = self.viewer_pixmap_cache_order.pop(0)
            self.viewer_pixmap_cache.pop(old_key, None)
        return pix

    def build_prepared_viewer_items(self, group, active_video_slots):
        prepared = []
        for col, path in enumerate(group):
            if col in active_video_slots:
                pix = QPixmap()
            elif is_video(path):
                pix = self.render_viewer_preview_pixmap(path, fast_video=True)
            elif is_image(path):
                pix = self.cached_viewer_preview_pixmap(path)
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

    def queue_viewer_preloads(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical") or not self.items:
            return
        offsets = []
        for distance in range(1, 6):
            offsets.extend([distance, -distance])
        queue = []
        for offset in offsets:
            idx = self.index + offset
            if 0 <= idx < len(self.items):
                path = self.items[idx]
                if is_image(path):
                    key = self.viewer_pixmap_cache_key(path)
                    if key not in self.viewer_pixmap_cache:
                        queue.append(path)
        self.viewer_preload_queue = queue
        self.viewer_preload_queued = {str(path) for path in queue}
        if queue and not self.viewer_preload_timer.isActive():
            self.viewer_preload_timer.start()

    def process_next_viewer_preload(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.viewer_preload_timer.stop()
            return
        while self.viewer_preload_queue:
            path = self.viewer_preload_queue.pop(0)
            self.viewer_preload_queued.discard(str(path))
            if Path(path).exists() and is_image(path):
                self.cached_viewer_preview_pixmap(path)
                return
        self.viewer_preload_timer.stop()

    def show_current(self, reset=False):
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
            for path in group:
                if is_image(path):
                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    label.setAttribute(Qt.WA_StyledBackground, True)
                    label.setAutoFillBackground(True)
                    label.setMinimumHeight(120)
                    label.setStyleSheet("background: #050505; color: #777;")
                    label.setText(path.name)
                    layout.addWidget(label)
                    self.labels.append((label, path))
            layout.addStretch(1)
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
        else:
            for item in prepared_items or []:
                col = item["col"]
                path = item["path"]
                if item["active_video"]:
                    frame = self.video_frame if not self.media_player or self.video_path is None else self.create_video_frame()
                    self.grid.addWidget(frame, 0, col)
                    self.play_video(path, frame=frame, primary=(self.video_path is None))
                elif item["video"]:
                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    label.setAttribute(Qt.WA_StyledBackground, True)
                    label.setAutoFillBackground(True)
                    label.setStyleSheet("background: #050505;")
                    label.setPixmap(item["pix"])
                    label.setToolTip(Path(path).name)
                    self.grid.addWidget(label, 0, col)
                    QTimer.singleShot(80, lambda lbl=label, p=Path(path), g=generation: self.update_video_preview_label(lbl, p, g))
                else:
                    label = PannableImageLabel()
                    label.setAttribute(Qt.WA_StyledBackground, True)
                    label.setAutoFillBackground(True)
                    label.setStyleSheet("background: #050505;")
                    if not item["pix"].isNull():
                        label.setPixmap(item["pix"])
                    self.grid.addWidget(label, 0, col)
                    self.labels.append((label, path))
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
        self.webtoon_pixmap_cache[key] = pix
        self.webtoon_pixmap_cache_order.append(key)
        while len(self.webtoon_pixmap_cache_order) > 48:
            old_key = self.webtoon_pixmap_cache_order.pop(0)
            self.webtoon_pixmap_cache.pop(old_key, None)
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

    def play_video(self, path, frame=None, primary=True):
        if not self.vlc_instance:
            label = QLabel("VLC runtime not available\n" + path.name)
            label.setAlignment(Qt.AlignCenter)
            label.setAttribute(Qt.WA_StyledBackground, True)
            label.setStyleSheet("background: #050505; color: #f0f0f0;")
            self.grid.addWidget(label, 0, 0)
            return
        frame = frame or self.video_frame
        player = self.media_player if primary else self.vlc_instance.media_player_new()
        if not player:
            return
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
        media = self.vlc_instance.media_new(str(path))
        player.set_media(media)
        player.set_hwnd(int(frame.winId()))
        try:
            player.video_set_mouse_input(False)
            player.video_set_key_input(False)
        except Exception:
            pass
        player.play()
        player.audio_set_volume(self.volume_slider.value())
        if primary:
            self.video_timer.start(250)
            frame.setFocus()

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

    def stop_media(self):
        self.movie = None
        self.stop_animated_image()
        self.video_stopped_by_user = True
        self.video_finished = False
        if hasattr(self, "video_timer"):
            self.video_timer.stop()
        for player in getattr(self, "extra_media_players", []):
            try:
                player.stop()
            except Exception:
                pass
        self.extra_media_players = []
        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass
        self.video_path = None
        if hasattr(self, "seek_slider"):
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)
            self.time_label.setText("00:00 / 00:00")

    def stop_animated_image(self):
        if hasattr(self, "animated_image_timer"):
            self.animated_image_timer.stop()
        for state in getattr(self, "animated_image_states", {}).values():
            try:
                state["reader"].close()
            except Exception:
                pass
        self.animated_image_states = {}
        if self.animated_image_reader is not None:
            try:
                self.animated_image_reader.close()
            except Exception:
                pass
        self.animated_image_reader = None
        self.animated_image_frame_count = 0
        self.animated_image_index = 0
        self.animated_image_label = None
        self.animated_image_path = None

    def try_start_animated_image(self, label, path):
        path = Path(path)
        if path.suffix.lower() not in (".gif", ".webp"):
            return False
        key = id(label)
        existing = self.animated_image_states.get(key)
        if existing and existing.get("path") == path and existing.get("label") is label:
            self.render_animated_image_frame(existing)
            return True
        reader = None
        try:
            reader = Image.open(path)
            if not getattr(reader, "is_animated", False) or getattr(reader, "n_frames", 1) <= 1:
                reader.close()
                return False
        except Exception:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            return False
        if existing:
            try:
                existing["reader"].close()
            except Exception:
                pass
        state = {
            "reader": reader,
            "frame_count": max(1, int(getattr(reader, "n_frames", 1))),
            "index": 0,
            "label": label,
            "path": path,
            "next_due": 0.0,
        }
        self.animated_image_states[key] = state
        self.animated_image_reader = reader
        self.animated_image_frame_count = state["frame_count"]
        self.animated_image_index = 0
        self.animated_image_label = label
        self.animated_image_path = path
        duration = self.render_animated_image_frame(state)
        state["next_due"] = time.monotonic() + (duration / 1000.0)
        if not self.animated_image_timer.isActive():
            self.animated_image_timer.start(30)
        return True

    def render_animated_image_frame(self, state=None):
        if state is None:
            if not self.animated_image_states:
                return 80
            state = next(iter(self.animated_image_states.values()))
        label = state.get("label")
        reader = state.get("reader")
        if label is None:
            return 80
        if reader is None:
            return 80
        try:
            reader.seek(state["index"])
            duration = reader.info.get("duration", 80)
            duration = max(20, int(duration or 80))
            pix = QPixmap.fromImage(ImageQt(reader.convert("RGBA")))
        except Exception:
            return 80
        if pix.isNull():
            return duration
        if self.rotation:
            from PySide6.QtGui import QTransform
            pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
        target = self.target_size(label, pix)
        label.setPixmap(pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return duration

    def advance_animated_image(self):
        if not self.animated_image_states:
            self.stop_animated_image()
            return
        now = time.monotonic()
        for key, state in list(self.animated_image_states.items()):
            label = state.get("label")
            reader = state.get("reader")
            if label is None or reader is None or label.parent() is None:
                try:
                    if reader is not None:
                        reader.close()
                except Exception:
                    pass
                self.animated_image_states.pop(key, None)
                continue
            if now < state.get("next_due", 0.0):
                continue
            state["index"] = (state["index"] + 1) % state["frame_count"]
            duration = self.render_animated_image_frame(state)
            state["next_due"] = now + (duration / 1000.0)
        if not self.animated_image_states:
            self.animated_image_timer.stop()

    def update_image_labels(self, generation=None):
        if generation is not None and generation != self.render_generation:
            return
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.webtoon_loaded = set()
            self.update_webtoon_visible_images(generation)
            return
        for label, path in self.labels:
            self.load_image_label(label, path)

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
            label.setMinimumHeight(0)
            label.setText("")
            label.setPixmap(pix)
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
            if self.load_image_label(label, path):
                self.webtoon_loaded.add(idx)

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
            if self.load_image_label(label, path):
                self.webtoon_loaded.add(idx)
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
        self.stop_media()
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        self.index = min(len(self.items) - 1, self.index + step)
        self.show_current(reset=not self.zoom_locked)

    def next_media_wrap(self):
        if not self.items:
            return
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(1)
            return
        self.stop_media()
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

    def remove_current_after_delete(self, deleted_path):
        deleted_path = str(deleted_path)
        self.stop_media()
        self.items = [p for p in self.items if str(p) != deleted_path]
        if not self.items:
            self.exitRequested.emit()
            return
        self.index = min(self.index, len(self.items) - 1)
        self.show_current(reset=not self.zoom_locked)

    def previous_media(self):
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            self.scroll_webtoon_page(-1)
            return
        self.stop_media()
        step = 1
        if self.step_mode in ("page", "manga_page"):
            step = {"double": 2, "triple": 3}.get(self.viewer_mode, 1)
        self.index = max(0, self.index - step)
        self.show_current(reset=not self.zoom_locked)

    def first_media(self):
        self.stop_media()
        self.index = 0
        self.show_current(reset=not self.zoom_locked)

    def last_media(self):
        self.stop_media()
        self.index = max(0, len(self.items) - 1)
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

    def current_display_scale(self):
        for _, path in self.labels:
            if self.viewer_mode in ("webtoon", "webtoon_vertical"):
                size = self.image_pixel_size(path)
                if size.isValid() and size.width() > 0:
                    width = self.webtoon_target_width or self.compute_webtoon_target_width(path)
                    return max(0.05, min(10.0, width / size.width()))
            pix = QPixmap(str(path))
            if pix.isNull():
                continue
            if self.rotation:
                from PySide6.QtGui import QTransform
                pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
            target = self.target_size(None, pix)
            if pix.width() > 0:
                return max(0.05, min(10.0, target.width() / pix.width()))
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
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._app_filter_installed = False
        self.closed.emit()
        super().closeEvent(event)


class ShortcutDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Shortcut Settings")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)
        self.rows = {}
        form = QFormLayout()
        layout.addLayout(form)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(settings.get("theme", "dark"))
        self.theme_combo.currentTextChanged.connect(self.set_theme)
        form.addRow("theme", self.theme_combo)
        self.instance_combo = QComboBox()
        self.instance_combo.addItems(["multi", "single"])
        self.instance_combo.setCurrentText(settings.get("instance_mode", "multi"))
        self.instance_combo.currentTextChanged.connect(self.set_instance_mode)
        form.addRow("instance mode", self.instance_combo)
        for action, values in sorted(settings.get("shortcuts", {}).items()):
            edit_btn = QPushButton(", ".join(values))
            edit_btn.clicked.connect(lambda checked=False, a=action: self.edit_action(a))
            self.rows[action] = edit_btn
            form.addRow(action, edit_btn)
        close = QPushButton("Save")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def edit_action(self, action):
        current = ", ".join(self.settings["shortcuts"].get(action, []))
        text, ok = QInputDialog.getText(
            self,
            "Shortcut",
            "Comma separated shortcuts. Mouse tokens: MouseMiddle, MouseBack, MouseForward, WheelUp, WheelDown",
            text=current,
        )
        if ok:
            values = [v.strip() for v in text.split(",") if v.strip()]
            self.settings["shortcuts"][action] = values
            self.rows[action].setText(", ".join(values))
            save_settings(self.settings)

    def set_theme(self, theme):
        self.settings["theme"] = theme
        save_settings(self.settings)

    def set_instance_mode(self, mode):
        self.settings["instance_mode"] = mode
        save_settings(self.settings)


class MainWindow(QMainWindow):
    def __init__(self, startup_path=None):
        super().__init__()
        self.settings = load_settings()
        startup_path = Path(startup_path) if startup_path else None
        self.startup_media_path = None
        if startup_path and startup_path.is_file() and is_media(startup_path):
            self.current_folder = startup_path.parent
            self.startup_media_path = startup_path
        elif startup_path and startup_path.is_dir():
            self.current_folder = startup_path
        else:
            self.current_folder = DEFAULT_START_FOLDER
        if not self.safe_is_dir(self.current_folder):
            self.current_folder = DEFAULT_START_FOLDER
        self.settings["last_folder"] = DEFAULT_LAST_FOLDER_SETTING
        save_settings(self.settings)
        self.media_paths = []
        self.viewer = None
        self.history = []
        self.history_index = -1
        self.entries = []
        self.archive_tempdirs = []
        self.display_path = str(self.current_folder)
        self.virtual_unc_server = ""
        self.virtual_entries = []
        self.thumbnail_cache = {}
        self.thumbnail_queue = []
        self.thumbnail_queued = set()
        self.thumbnail_visible_batch = 4
        self.thumbnail_idle_batch = 2
        self.cut_clipboard_paths = set()
        self.tabs = []
        self.current_tab = 0
        self._loading_tab = False
        self.folder_watcher = QFileSystemWatcher(self)
        self.folder_watcher.directoryChanged.connect(self.on_watched_folder_changed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.reload_current_if_available)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setInterval(35)
        self.thumbnail_timer.timeout.connect(self.process_next_thumbnail)
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
        left_tabs.addTab(self.tree, "Folders")
        left_tabs.addTab(self.quick_paths, "Shortcuts")

        left = QSplitter(Qt.Vertical)
        left.addWidget(left_tabs)
        left.addWidget(self.preview)
        left.setSizes([620, 220])

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
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(3)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        self.folder_tabs = QTabBar()
        self.folder_tabs.setMovable(True)
        self.folder_tabs.setTabsClosable(True)
        self.folder_tabs.currentChanged.connect(self.on_folder_tab_changed)
        self.folder_tabs.tabCloseRequested.connect(self.close_folder_tab)
        self.add_tab_btn = self.make_icon_button("+", self.add_folder_tab)
        tab_row.addWidget(self.folder_tabs)
        tab_row.addWidget(self.add_tab_btn)
        tab_row.addStretch(1)
        header_layout.addLayout(tab_row)

        crumb_row = QHBoxLayout()
        crumb_row.setContentsMargins(0, 0, 0, 0)
        self.refresh_btn = self.make_icon_button("Refresh", self.reload_current)
        self.quick_search = QLineEdit()
        self.quick_search.setPlaceholderText("Quick Search")
        self.quick_search.textChanged.connect(self.apply_quick_search)
        crumb_row.addWidget(QLabel("PC"))
        crumb_row.addWidget(self.path_edit, 1)
        crumb_row.addWidget(self.refresh_btn)
        crumb_row.addWidget(self.quick_search)
        header_layout.addLayout(crumb_row)

        command_row = QHBoxLayout()
        command_row.setContentsMargins(0, 0, 0, 0)
        self.select_button = QToolButton()
        self.select_button.setCheckable(True)
        self.select_button.setAutoRaise(True)
        self.select_button.clicked.connect(self.toggle_select_all)
        command_row.addWidget(self.select_button)
        command_row.addSpacing(6)
        command_row.addWidget(self.make_icon_button("<", self.go_back))
        command_row.addWidget(self.make_icon_button(">", self.go_forward))
        command_row.addWidget(self.make_icon_button("^", self.go_up))
        command_row.addSpacing(8)
        self.sort_button = self.make_sort_button()
        self.view_button = self.make_view_button()
        command_row.addWidget(QLabel("Sort:"))
        command_row.addWidget(self.sort_button)
        command_row.addSpacing(8)
        command_row.addWidget(QLabel("View:"))
        command_row.addWidget(self.view_button)
        command_row.addStretch(1)
        header_layout.addLayout(command_row)

        right_layout.addWidget(header)
        right_layout.addWidget(self.view_stack, 1)

        self.explorer_root = QSplitter(Qt.Horizontal)
        self.explorer_root.addWidget(left)
        self.explorer_root.addWidget(right_widget)
        self.explorer_root.setSizes([320, 960])
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.explorer_root)
        self.setCentralWidget(self.main_stack)
        self.list.set_view_mode_name(self.view_combo.currentText())
        self.view_stack.setCurrentWidget(self.details if self.view_combo.currentText() == "details" else self.list)
        self.update_command_buttons()

    def make_icon_button(self, text, callback):
        button = QToolButton()
        button.setText(text)
        button.setAutoRaise(True)
        button.clicked.connect(callback)
        return button

    def apply_theme(self):
        if self.settings.get("theme", "dark") == "light":
            self.setStyleSheet("""
                QMainWindow, QWidget { background: #f2f2f2; color: #161616; }
            QTreeView, QListWidget, QTableWidget { background: #ffffff; color: #151515; selection-background-color: #bda7dc; selection-color: white; }
            QListWidget::item:selected, QTableWidget::item:selected { background: #bda7dc; color: white; border: 1px solid #d7c8f0; }
                QHeaderView::section { background: #e2e2e2; color: #151515; border: 1px solid #c8c8c8; padding: 4px; }
                QLineEdit { background: #ffffff; color: #151515; border: 1px solid #b8b8b8; padding: 5px 8px; }
                QToolButton, QPushButton, QComboBox { background: #e4e4e4; color: #151515; border: 1px solid #b8b8b8; padding: 4px 9px; }
                QTabBar::tab { padding: 5px 16px; background: #e3e3e3; color: #333; border: 1px solid #bdbdbd; }
                QTabBar::tab:selected { background: #ffffff; color: #111; border-bottom: 2px solid #327bd1; font-weight: 700; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background: #1e1e1e; color: #f0f0f0; }
            QTreeView, QListWidget, QTableWidget { background: #242424; color: #f0f0f0; selection-background-color: #8f72b8; selection-color: white; }
            QListWidget::item:selected, QTableWidget::item:selected { background: #8f72b8; color: white; border: 1px solid #c7b5e8; }
                QHeaderView::section { background: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 4px; }
                QLineEdit { background: #262626; color: #f0f0f0; border: 1px solid #444; padding: 5px 8px; }
                QToolButton, QPushButton, QComboBox { background: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 4px 9px; }
                QTabBar::tab { padding: 5px 16px; background: #2d2d2d; color: #bbbbbb; border: 1px solid #3f3f3f; }
                QTabBar::tab:selected { background: #4a4a4a; color: white; border-bottom: 2px solid #7fb7ff; font-weight: 700; }
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
            self.sort_button.setText(self.sort_label())
        if hasattr(self, "view_button"):
            self.view_button.setText(self.view_combo.currentText())
        if hasattr(self, "select_button"):
            checked = self.all_items_selected()
            self.select_button.setChecked(checked)
            self.select_button.setText(("V" if checked else "□") + " Select all")

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
        return f"{names.get(mode, mode.title())} {'^' if ascending else 'v'}"

    def make_view_button(self):
        entries = []
        for mode in ["large", "medium", "small", "list", "details"]:
            entries.append((mode, lambda m=mode: self.view_combo.setCurrentText(m)))
        return self.make_menu_button("View", entries, self.view_combo.currentText())

    def make_sort_button(self):
        entries = [
            ("Filename", lambda: self.set_sort_from_header("name")),
            ("Size (KB)", lambda: self.set_sort_from_header("size")),
            ("Image Type", lambda: self.set_sort_from_header("type")),
            ("Modified Date", lambda: self.set_sort_from_header("modified")),
            ("Image Properties", lambda: self.set_sort_from_header("properties")),
        ]
        return self.make_menu_button("Sort", entries, self.sort_label())

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
            self.folder_tabs.addTab(path.name or str(path))
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
        self.folder_tabs.setCurrentIndex(index)

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
            self.load_folder(tab["path"], add_history=False, display_path=tab.get("display"))
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
            self.load_folder(path)

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
            return Path(folder).exists() and Path(folder).is_dir()
        except OSError:
            return False

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
        model_index = self.tree_model.index(str(self.current_folder))
        if model_index.isValid():
            self.tree.setCurrentIndex(model_index)
        self.watch_current_folder()
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

    def load_folder(self, folder, add_history=True, display_path=None):
        folder = Path(folder)
        if not self.safe_is_dir(folder):
            QMessageBox.warning(self, "Invalid path", f"Cannot open this path:\n{folder}")
            return False
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
        save_settings(self.settings)
        self.path_edit.setText(self.display_path)
        model_index = self.tree_model.index(str(folder))
        if model_index.isValid():
            self.tree.setCurrentIndex(model_index)
        self.watch_current_folder()
        self.populate_list()
        self.update_current_tab()
        return True

    def populate_list(self, lightweight=True):
        self.thumbnail_timer.stop()
        self.thumbnail_queue = []
        self.thumbnail_queued = set()
        self.list.clear()
        self.details.setRowCount(0)
        if self.virtual_unc_server:
            entries = [MediaItem(path, True, label) for label, path in self.virtual_entries]
            self.entries = entries
            self.media_paths = []
            if self.view_combo.currentText() == "details":
                self.details.load_entries(entries, self.icon_provider, self.make_icon, lightweight=lightweight)
            else:
                for entry in entries:
                    item = QListWidgetItem(entry.display_name)
                    item.setData(Qt.UserRole, str(entry.path))
                    item.setToolTip(str(entry.path))
                    item.setIcon(self.entry_icon(entry, lightweight=lightweight))
                    self.list.addItem(item)
            self.update_command_buttons()
            if lightweight:
                self.start_thumbnail_loading()
            return
        entries = []
        if not self.safe_is_dir(self.current_folder):
            self.current_folder = DEFAULT_START_FOLDER
            self.path_edit.setText(str(self.current_folder))
        try:
            for child in self.current_folder.iterdir():
                if child.is_dir() or is_media(child) or is_archive(child):
                    entries.append(MediaItem(child, child.is_dir()))
        except (PermissionError, FileNotFoundError, OSError) as exc:
            self.path_edit.setText(str(self.current_folder))
            QMessageBox.warning(self, "Folder error", f"Cannot read folder:\n{self.current_folder}\n\n{exc}")
            return
        query = self.quick_search.text().strip().lower() if hasattr(self, "quick_search") else ""
        if query:
            entries = [entry for entry in entries if query in entry.path.name.lower()]

        sort_mode = self.settings.get("sort_mode", "name")
        ascending = self.settings.get("sort_ascending", True)
        self.settings["sort_mode"] = sort_mode
        save_settings(self.settings)
        entries = self.sorted_entries(entries, sort_mode, ascending)
        self.entries = entries

        self.media_paths = [str(e.path) for e in entries if not e.is_dir and is_media(e.path)]
        if self.view_combo.currentText() == "details":
            self.details.load_entries(entries, self.icon_provider, self.make_icon, lightweight=lightweight)
            self.update_command_buttons()
            if lightweight:
                self.start_thumbnail_loading()
            return
        for entry in entries:
            item = QListWidgetItem(entry.display_name)
            item.setData(Qt.UserRole, str(entry.path))
            item.setToolTip(str(entry.path))
            item.setIcon(self.entry_icon(entry, lightweight=lightweight))
            color = type_color(entry.path)
            if color is not None:
                item.setBackground(color)
            self.list.addItem(item)
        self.update_command_buttons()
        if lightweight:
            self.start_thumbnail_loading()

    def entry_icon(self, entry, lightweight=True):
        cached = self.thumbnail_cache.get(str(entry.path))
        if cached is not None:
            return cached
        if lightweight:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))
        return self.make_icon(entry)

    def start_thumbnail_loading(self):
        self.thumbnail_queue = []
        self.thumbnail_queued = set()
        QTimer.singleShot(0, self.prioritize_visible_thumbnails)

    def queue_thumbnail(self, path, front=False):
        path = str(path)
        if path in self.thumbnail_cache or path in self.thumbnail_queued:
            return
        p = Path(path)
        if not p.exists() or p.is_dir() or is_archive(p):
            return
        if not is_media(p):
            return
        self.thumbnail_queued.add(path)
        if front:
            self.thumbnail_queue.insert(0, path)
        else:
            self.thumbnail_queue.append(path)

    def prioritize_visible_thumbnails(self):
        if not hasattr(self, "entries"):
            return
        visible = self.visible_paths()
        if not visible:
            visible = [str(entry.path) for entry in self.entries[:24]]
        visible_set = {str(path) for path in visible}
        self.thumbnail_queue = [path for path in self.thumbnail_queue if path in visible_set]
        self.thumbnail_queued = {path for path in self.thumbnail_queued if path in visible_set}
        for path in reversed(visible):
            path = str(path)
            if path in self.thumbnail_queued:
                try:
                    self.thumbnail_queue.remove(path)
                except ValueError:
                    pass
                self.thumbnail_queue.insert(0, path)
            else:
                self.queue_thumbnail(path, front=True)
        if self.thumbnail_queue and not self.thumbnail_timer.isActive():
            self.thumbnail_timer.start()

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
        if not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            return
        visible_set = {str(path) for path in self.visible_paths()}
        batch = self.thumbnail_idle_batch
        if visible_set and any(path in visible_set for path in self.thumbnail_queue[: max(1, self.thumbnail_visible_batch * 2)]):
            batch = self.thumbnail_visible_batch
        processed = 0
        while self.thumbnail_queue and processed < batch:
            path = self.thumbnail_queue.pop(0)
            self.thumbnail_queued.discard(path)
            if processed > 0 and visible_set and path not in visible_set:
                self.thumbnail_queue.append(path)
                self.thumbnail_queued.add(path)
                if not any(next_path in visible_set for next_path in self.thumbnail_queue[: max(1, self.thumbnail_visible_batch * 2)]):
                    break
                continue
            if path in self.thumbnail_cache:
                icon = self.thumbnail_cache[path]
            else:
                p = Path(path)
                try:
                    icon = self.make_thumbnail_icon(MediaItem(p, p.is_dir()))
                except Exception:
                    icon = self.icon_provider.icon(QFileInfo(str(p)))
                self.thumbnail_cache[path] = icon
            self.apply_thumbnail_icon(path, icon)
            processed += 1
        if not self.thumbnail_queue:
            self.thumbnail_timer.stop()
            QTimer.singleShot(250, self.queue_idle_thumbnail)

    def queue_idle_thumbnail(self):
        if self.thumbnail_timer.isActive() or self.thumbnail_queue:
            return
        visible_set = {str(path) for path in self.visible_paths()}
        queued = 0
        for entry in self.entries:
            path = str(entry.path)
            if path in visible_set or path in self.thumbnail_cache:
                continue
            self.queue_thumbnail(path, front=False)
            queued += 1
            if queued >= self.thumbnail_idle_batch:
                break
        if self.thumbnail_queue:
            self.thumbnail_timer.start()

    def apply_thumbnail_icon(self, path, icon):
        path = str(path)
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item and item.data(Qt.UserRole) == path:
                item.setIcon(icon)
                break
        for row in range(self.details.rowCount()):
            item = self.details.item(row, 0)
            if item and item.data(Qt.UserRole) == path:
                item.setIcon(icon)
                break

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

        def stat_value(item, attr):
            try:
                return getattr(item.path.stat(), attr)
            except Exception:
                return 0

        if sort_mode.endswith("_desc"):
            ascending = False
        elif sort_mode.endswith("_asc"):
            ascending = True
        key_map = {
            "name": key_name,
            "name_asc": key_name,
            "name_desc": key_name,
            "size": lambda x: 0 if x.is_dir else stat_value(x, "st_size"),
            "size_asc": lambda x: 0 if x.is_dir else stat_value(x, "st_size"),
            "size_desc": lambda x: 0 if x.is_dir else stat_value(x, "st_size"),
            "type": lambda x: (x.kind, x.path.suffix.lower(), x.path.name.lower()),
            "modified": lambda x: stat_value(x, "st_mtime"),
            "date_desc": lambda x: stat_value(x, "st_mtime"),
            "date_asc": lambda x: stat_value(x, "st_mtime"),
            "properties": lambda x: image_properties(x.path),
        }
        entries.sort(key=key_map.get(sort_mode, key_name), reverse=not ascending)
        entries.sort(key=lambda x: not x.is_dir)
        return entries

    def set_sort_from_header(self, key, ascending=None):
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
        save_settings(self.settings)
        self.update_command_buttons()
        self.populate_list()

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
        self.settings["view_mode"] = mode
        save_settings(self.settings)
        self.list.set_view_mode_name(mode)
        self.view_stack.setCurrentWidget(self.details if mode == "details" else self.list)
        self.update_command_buttons()
        self.populate_list()

    def reload_current(self):
        self.populate_list()

    def watch_current_folder(self):
        try:
            watched = self.folder_watcher.directories()
            if watched:
                self.folder_watcher.removePaths(watched)
            if not self.virtual_unc_server and self.safe_is_dir(self.current_folder):
                self.folder_watcher.addPath(str(self.current_folder))
        except Exception:
            pass

    def on_watched_folder_changed(self, path):
        if Path(path) == self.current_folder:
            self.refresh_timer.start(250)

    def reload_current_if_available(self):
        if self.safe_is_dir(self.current_folder):
            self.populate_list()
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

    def activate_from_external_request(self):
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def open_external_request(self, path_text=None):
        self.activate_from_external_request()
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
        try:
            tempdir = tempfile.TemporaryDirectory(prefix="pmv_zip_")
            out_root = Path(tempdir.name)
            count = 0
            with zipfile.ZipFile(archive_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    inner = Path(info.filename)
                    if inner.suffix.lower() not in IMAGE_EXTS:
                        continue
                    target = out_root / inner.name
                    base = target.stem
                    suffix = target.suffix
                    n = 1
                    while target.exists():
                        target = out_root / f"{base}_{n}{suffix}"
                        n += 1
                    with zf.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    count += 1
        except Exception as exc:
            QMessageBox.warning(self, "Archive error", f"Cannot read archive:\n{archive_path}\n\n{exc}")
            return False
        if count == 0:
            tempdir.cleanup()
            QMessageBox.information(self, "Archive", "No image files found in this zip.")
            return False
        self.archive_tempdirs.append(tempdir)
        return self.load_folder(out_root, add_history=add_history, display_path=f"{archive_path}::")

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
        self.populate_list()
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
        self.viewer = ViewerWindow(self.settings, self)
        self.viewer.exitRequested.connect(self.exit_viewer_mode)
        self.viewer.deleteRequested.connect(self.delete_from_viewer)
        self.viewer.copyRequested.connect(self.copy_from_viewer)
        self.viewer.pasteRequested.connect(self.paste_from_clipboard)
        self.viewer.load(self.media_paths, idx)
        self.main_stack.addWidget(self.viewer)
        self.nav_toolbar.hide()
        self.main_stack.setCurrentWidget(self.viewer)
        self.showFullScreen()
        self.viewer.setFocus()
        return True

    def copy_from_viewer(self, path):
        self.copy_paths([Path(path)])
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
        if not path.exists():
            self.viewer.remove_current_after_delete(str(path))
            self.populate_list()
            return
        try:
            send_to_recycle_bin(path)
        except Exception:
            QMessageBox.warning(self, "Delete failed", f"Could not move to recycle bin:\n{path}")
            self.viewer.setFocus()
            return
        self.viewer.remove_current_after_delete(str(path))
        self.populate_list()
        if self.viewer:
            self.viewer.items = [Path(p) for p in self.media_paths]
            if self.viewer.items:
                self.viewer.index = min(self.viewer.index, len(self.viewer.items) - 1)
                self.viewer.show_current(reset=False)
            else:
                self.exit_viewer_mode()
                return
            self.viewer.setFocus()

    def exit_viewer_mode(self, refresh=True):
        if not self.viewer:
            return
        current = None
        if self.viewer.items:
            current = str(self.viewer.items[self.viewer.index])
        self.viewer.stop_media()
        if self.viewer._app_filter_installed:
            QApplication.instance().removeEventFilter(self.viewer)
            self.viewer._app_filter_installed = False
        self.main_stack.setCurrentWidget(self.explorer_root)
        self.main_stack.removeWidget(self.viewer)
        self.viewer.deleteLater()
        self.viewer = None
        self.nav_toolbar.hide()
        if self.isFullScreen():
            self.showNormal()
        if not refresh:
            return
        self.populate_list(lightweight=True)
        if current:
            self.select_path(current)

    def select_path(self, path):
        if self.view_combo.currentText() == "details":
            for row in range(self.details.rowCount()):
                item = self.details.item(row, 0)
                if item and item.data(Qt.UserRole) == path:
                    self.details.selectRow(row)
                    self.details.scrollToItem(item)
                    break
        else:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole) == path:
                    self.list.setCurrentItem(item)
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
            self.populate_list()

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
            self.populate_list()

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
        self.populate_list()

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
        dlg.exec()
        self.apply_theme()
        self.populate_list()
        QMessageBox.information(self, "Settings", "Shortcut changes are saved. Restart to rebuild keyboard bindings.")

    def closeEvent(self, event):
        if hasattr(self, "mouse_wheel_hook"):
            self.mouse_wheel_hook.uninstall()
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


def windows_shell_thumbnail(path, size=512):
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
        pix = QPixmap.fromImage(image)
        return pix if not pix.isNull() else None
    except Exception:
        return None


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
            connection._pmv_handled = False

            def read_request(conn=connection):
                if getattr(conn, "_pmv_handled", False):
                    return
                if conn.bytesAvailable() <= 0:
                    if conn.state() == QLocalSocket.UnconnectedState:
                        conn.deleteLater()
                    return
                conn._pmv_handled = True
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
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
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
