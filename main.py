import json
import os
import shutil
import sys
import ctypes
import tempfile
import zipfile
from io import BytesIO
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Portable Media Viewer"
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
from PySide6.QtCore import QAbstractNativeEventFilter, QDir, QEvent, QFileInfo, QFileSystemWatcher, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QMovie, QPainter, QPixmap, QShortcut
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
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff",
    ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".jfif",
}
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v",
    ".mpeg", ".mpg", ".ts", ".m2ts", ".3gp", ".ogv",
}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS
ARCHIVE_EXTS = {".zip"}


DEFAULT_SETTINGS = {
    "last_folder": str(DEFAULT_START_FOLDER),
    "view_mode": "large",
    "sort_mode": "name_asc",
    "viewer_mode": "single",
    "viewer_step": "page",
    "default_fit": "fit_height",
    "zoom_locked": True,
    "theme": "dark",
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


class DetailsTable(QTableWidget):
    openRequested = Signal(str)
    previewRequested = Signal(str)
    sortedRequested = Signal(str, bool)

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

    def load_entries(self, entries, icon_provider, make_icon):
        self.setRowCount(0)
        for row, entry in enumerate(entries):
            self.insertRow(row)
            values = self.row_values(entry)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, str(entry.path))
                if col == 0:
                    item.setIcon(make_icon(entry))
                if col == 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                color = type_color(entry.path)
                if color is not None:
                    item.setBackground(color)
                self.setItem(row, col, item)

    def row_values(self, entry):
        if entry.is_dir:
            return [entry.display_name, "", "Folder", "", fmt_modified(entry.path), "", "", "", ""]
        size_kb = entry.path.stat().st_size // 1024
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
        if not viewer or not viewer.is_active_viewer():
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
        self.movie = None
        self._app_filter_installed = False
        self._seeking_video = False
        self.video_path = None
        self.video_finished = False
        self.video_stopped_by_user = False
        self.webtoon_scroll = None

        self.setWindowTitle(APP_NAME + " - Viewer")
        self.setMinimumSize(900, 640)
        self._build_ui()
        self._build_shortcuts()
        self._init_vlc()

    def _build_ui(self):
        self.central = QWidget()
        self.central.setMouseTracking(True)
        self.grid = QGridLayout(self.central)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.setCentralWidget(self.central)
        self.labels = []
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background: #000;")
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.setMouseTracking(True)
        self.central.setFocusPolicy(Qt.StrongFocus)
        self.video_frame.installEventFilter(self)
        self.central.installEventFilter(self)

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
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.update_video_controls)
        self.input_layer = QWidget(self.central)
        self.input_layer.setMouseTracking(True)
        self.input_layer.setStyleSheet("background: transparent;")
        self.input_layer.installEventFilter(self)
        self.input_layer.raise_()

    def build_mode_menu(self):
        menu = QMenu(self.mode_btn)
        menu.addAction("single", lambda: self.set_viewer_mode("single"))
        double_menu = menu.addMenu("double")
        double_menu.addAction("page", lambda: self.set_viewer_mode("double", "page"))
        double_menu.addAction("slide", lambda: self.set_viewer_mode("double", "slide"))
        triple_menu = menu.addMenu("triple")
        triple_menu.addAction("page", lambda: self.set_viewer_mode("triple", "page"))
        triple_menu.addAction("slide", lambda: self.set_viewer_mode("triple", "slide"))
        menu.addAction("webtoon", lambda: self.set_viewer_mode("webtoon_vertical"))
        return menu

    def update_mode_button(self):
        if self.viewer_mode in ("double", "triple"):
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
        return self.items[self.index:self.index + size]

    def clear_grid(self):
        self.stop_media()
        self.webtoon_scroll = None
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        self.labels = []

    def show_current(self, reset=False):
        if reset:
            self.fit_mode = self.settings.get("default_fit", "fit_height")
            self.fit_combo.setCurrentText(self.fit_mode)
            self.zoom_factor = 1.0
            self.update_manual_zoom_controls()
        self.clear_grid()
        group = self.current_group()
        if not group:
            label = QLabel("No media")
            label.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(label, 0, 0)
            return

        self.current_is_video = len(group) == 1 and is_video(group[0])
        if self.current_is_video:
            self.grid.addWidget(self.video_frame, 0, 0)
            self.play_video(group[0])
        elif self.viewer_mode in ("webtoon", "webtoon_vertical"):
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            for path in group:
                if is_image(path):
                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    layout.addWidget(label)
                    self.labels.append((label, path))
            layout.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(container)
            scroll.setStyleSheet("background: #050505;")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.webtoon_scroll = scroll
            self.grid.addWidget(scroll, 0, 0)
            self.schedule_image_update()
        else:
            for col, path in enumerate(group):
                if is_video(path):
                    label = QLabel("Video\n" + path.name)
                    label.setAlignment(Qt.AlignCenter)
                    label.setStyleSheet("background: #050505; color: white;")
                    self.grid.addWidget(label, 0, col)
                else:
                    label = QLabel()
                    label.setAlignment(Qt.AlignCenter)
                    label.setStyleSheet("background: #050505;")
                    self.grid.addWidget(label, 0, col)
                    self.labels.append((label, path))
            self.schedule_image_update()
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            title_name = "webtoon"
        else:
            title_name = self.items[self.index].name
        self.setWindowTitle(f"{APP_NAME} - {self.index + 1}/{len(self.items)} - {title_name}")
        self.update_filename_labels()
        self.position_overlays()

    def current_file_name(self):
        if not self.items:
            return ""
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            return f"webtoon ({len([p for p in self.items if is_image(p)])} images)"
        return self.items[self.index].name

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

    def schedule_image_update(self):
        QTimer.singleShot(0, self.update_image_labels)
        QTimer.singleShot(40, self.update_image_labels)

    def play_video(self, path):
        if not self.media_player or not self.vlc_instance:
            label = QLabel("VLC runtime not available\n" + path.name)
            label.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(label, 0, 0)
            return
        self.video_path = Path(path)
        self.video_finished = False
        self.video_stopped_by_user = False
        media = self.vlc_instance.media_new(str(path))
        self.media_player.set_media(media)
        self.media_player.set_hwnd(int(self.video_frame.winId()))
        try:
            self.media_player.video_set_mouse_input(False)
            self.media_player.video_set_key_input(False)
        except Exception:
            pass
        self.media_player.play()
        self.media_player.audio_set_volume(self.volume_slider.value())
        self.video_timer.start(250)
        self.video_frame.setFocus()

    def stop_media(self):
        self.movie = None
        self.video_stopped_by_user = True
        self.video_finished = False
        if hasattr(self, "video_timer"):
            self.video_timer.stop()
        if self.media_player:
            try:
                self.media_player.stop()
            except Exception:
                pass
        if hasattr(self, "seek_slider"):
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(0)
            self.seek_slider.blockSignals(False)
            self.time_label.setText("00:00 / 00:00")

    def update_image_labels(self):
        for label, path in self.labels:
            if path.suffix.lower() == ".gif" and self.viewer_mode == "single":
                movie = QMovie(str(path))
                if movie.isValid():
                    self.movie = movie
                    label.setMovie(movie)
                    movie.start()
                    continue
            pix = QPixmap(str(path))
            if pix.isNull():
                label.setText(path.name)
                continue
            if self.rotation:
                from PySide6.QtGui import QTransform
                pix = pix.transformed(QTransform().rotate(self.rotation), Qt.SmoothTransformation)
            target = self.target_size(label, pix)
            label.setPixmap(pix.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def target_size(self, label, pix):
        area = self.viewer_area()
        if self.viewer_mode in ("webtoon", "webtoon_vertical"):
            if self.fit_mode == "actual":
                return pix.size()
            if self.fit_mode == "manual":
                return QSize(max(1, int(pix.width() * self.zoom_factor)), max(1, int(pix.height() * self.zoom_factor)))
            width = area.width()
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
        elif event.key() == Qt.Key_Space:
            self.handle_space()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if not self.is_active_viewer():
            return super().eventFilter(obj, event)
        if event.type() == QEvent.KeyPress:
            if event.matches(QKeySequence.Copy):
                self.copy_current()
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
        if self.step_mode == "page":
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
        if self.step_mode == "page":
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
        if self.step_mode == "page":
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
        overlays = [self.viewer_overlay, self.rotation_overlay, self.video_overlay]
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
        self.settings["last_folder"] = str(DEFAULT_START_FOLDER)
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
        self.tabs = []
        self.current_tab = 0
        self._loading_tab = False
        self.folder_watcher = QFileSystemWatcher(self)
        self.folder_watcher.directoryChanged.connect(self.on_watched_folder_changed)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.reload_current_if_available)
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
        self.load_folder(self.current_folder)
        if self.startup_media_path:
            QTimer.singleShot(0, self.open_startup_media)

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
        self.list.installEventFilter(self)
        self.list.viewport().installEventFilter(self)

        self.details = DetailsTable()
        self.details.openRequested.connect(self.open_path)
        self.details.previewRequested.connect(self.preview.show_path)
        self.details.sortedRequested.connect(self.set_sort_from_header)
        self.details.setContextMenuPolicy(Qt.CustomContextMenu)
        self.details.customContextMenuRequested.connect(self.details_menu)
        self.details.installEventFilter(self)
        self.details.viewport().installEventFilter(self)
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
        command_row.addWidget(self.make_icon_button("<", self.go_back))
        command_row.addWidget(self.make_icon_button(">", self.go_forward))
        command_row.addWidget(self.make_icon_button("^", self.go_up))
        command_row.addSpacing(8)
        command_row.addWidget(self.make_sort_button())
        command_row.addWidget(self.make_view_button())
        command_row.addWidget(self.make_menu_button("Select", [("Select All", self.select_all_items)]))
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
                QTreeView, QListWidget, QTableWidget { background: #ffffff; color: #151515; selection-background-color: #7d4aa3; selection-color: white; }
                QHeaderView::section { background: #e2e2e2; color: #151515; border: 1px solid #c8c8c8; padding: 4px; }
                QLineEdit { background: #ffffff; color: #151515; border: 1px solid #b8b8b8; padding: 5px 8px; }
                QToolButton, QPushButton, QComboBox { background: #e4e4e4; color: #151515; border: 1px solid #b8b8b8; padding: 4px 9px; }
                QTabBar::tab { padding: 5px 16px; background: #e3e3e3; color: #333; border: 1px solid #bdbdbd; }
                QTabBar::tab:selected { background: #ffffff; color: #111; border-bottom: 2px solid #327bd1; font-weight: 700; }
            """)
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background: #1e1e1e; color: #f0f0f0; }
                QTreeView, QListWidget, QTableWidget { background: #242424; color: #f0f0f0; selection-background-color: #5a1470; selection-color: white; }
                QHeaderView::section { background: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 4px; }
                QLineEdit { background: #262626; color: #f0f0f0; border: 1px solid #444; padding: 5px 8px; }
                QToolButton, QPushButton, QComboBox { background: #3a3a3a; color: #f0f0f0; border: 1px solid #555; padding: 4px 9px; }
                QTabBar::tab { padding: 5px 16px; background: #2d2d2d; color: #bbbbbb; border: 1px solid #3f3f3f; }
                QTabBar::tab:selected { background: #4a4a4a; color: white; border-bottom: 2px solid #7fb7ff; font-weight: 700; }
            """)

    def make_menu_button(self, text, entries):
        button = QToolButton()
        button.setText(text)
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

    def make_view_button(self):
        entries = []
        for mode in ["large", "medium", "small", "list", "details"]:
            entries.append((mode, lambda m=mode: self.view_combo.setCurrentText(m)))
        return self.make_menu_button("View", entries)

    def make_sort_button(self):
        entries = [
            ("Filename", lambda: self.set_sort_from_header("name", True)),
            ("Size (KB)", lambda: self.set_sort_from_header("size", True)),
            ("Image Type", lambda: self.set_sort_from_header("type", True)),
            ("Modified Date", lambda: self.set_sort_from_header("modified", True)),
            ("Image Properties", lambda: self.set_sort_from_header("properties", True)),
        ]
        return self.make_menu_button("Sort", entries)

    def select_all_items(self):
        if self.view_combo.currentText() == "details":
            self.details.selectAll()
        else:
            self.list.selectAll()

    def apply_quick_search(self):
        self.populate_list()

    def go_home(self):
        self.load_folder(DEFAULT_START_FOLDER)

    def ensure_folder_tab(self):
        if self.tabs:
            return
        path = self.current_folder
        self.tabs.append({"path": path, "display": str(path), "history": [str(path)], "history_index": 0})
        self.folder_tabs.addTab(path.name or str(path))
        self.folder_tabs.setCurrentIndex(0)

    def add_folder_tab(self):
        self.save_current_tab()
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
            sort_menu.addAction(label, lambda checked=False, k=key: self.set_sort_from_header(k, True))
        sort_button = QPushButton("Sort")
        sort_button.setMenu(sort_menu)
        self.nav_toolbar.addWidget(sort_button)

        shortcut_map = {
            "open_viewer": self.open_selected_viewer,
            "back": self.go_back,
            "forward": self.go_forward,
            "rename": self.rename_selected,
            "delete": self.delete_selected,
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
        text, ok = QInputDialog.getText(self, "Rename Shortcut", "Name", text=item.text())
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
        menu.addAction("Rename", self.rename_quick_path)
        menu.addAction("Remove", self.remove_quick_path)
        menu.exec(self.quick_paths.mapToGlobal(pos))

    def safe_is_dir(self, folder):
        try:
            return Path(folder).exists() and Path(folder).is_dir()
        except OSError:
            return False

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

    def populate_list(self):
        self.list.clear()
        self.details.setRowCount(0)
        if self.virtual_unc_server:
            entries = [MediaItem(path, True, label) for label, path in self.virtual_entries]
            self.entries = entries
            self.media_paths = []
            self.details.load_entries(entries, self.icon_provider, self.make_icon)
            if self.view_combo.currentText() != "details":
                for entry in entries:
                    item = QListWidgetItem(entry.path.name)
                    item.setData(Qt.UserRole, str(entry.path))
                    item.setToolTip(str(entry.path))
                    item.setIcon(self.make_icon(entry))
                    self.list.addItem(item)
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
        self.details.load_entries(entries, self.icon_provider, self.make_icon)
        if self.view_combo.currentText() == "details":
            return
        for entry in entries:
            item = QListWidgetItem(entry.display_name)
            item.setData(Qt.UserRole, str(entry.path))
            item.setToolTip(str(entry.path))
            item.setIcon(self.make_icon(entry))
            color = type_color(entry.path)
            if color is not None:
                item.setBackground(color)
            self.list.addItem(item)

    def sorted_entries(self, entries, sort_mode, ascending):
        def key_name(item):
            return item.path.name.lower()

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

    def set_sort_from_header(self, key, ascending):
        self.settings["sort_mode"] = key
        self.settings["sort_ascending"] = ascending
        save_settings(self.settings)
        self.populate_list()

    def make_icon(self, entry):
        if entry.is_dir:
            return self.icon_provider.icon(QFileInfo(str(entry.path)))
        if is_video(entry.path):
            return self.style().standardIcon(QStyle.SP_MediaPlay)
        try:
            with Image.open(entry.path) as img:
                img.thumbnail((192, 192))
                data = BytesIO()
                img.convert("RGBA").save(data, format="PNG")
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
            self.open_viewer_for(self.startup_media_path)

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
        return [Path(i.data(Qt.UserRole)) for i in self.list.selectedItems()]

    def copy_selected(self):
        if self.main_stack.currentWidget() != self.explorer_root:
            return
        focus = QApplication.focusWidget()
        if focus in (self.path_edit, getattr(self, "quick_search", None)):
            return
        paths = self.selected_paths()
        if paths:
            copy_files_to_clipboard(paths)

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

    def open_viewer_for(self, path):
        if not self.media_paths:
            return
        path = str(path)
        try:
            idx = self.media_paths.index(path)
        except ValueError:
            idx = 0
        self.viewer = ViewerWindow(self.settings, self)
        self.viewer.exitRequested.connect(self.exit_viewer_mode)
        self.viewer.deleteRequested.connect(self.delete_from_viewer)
        self.viewer.copyRequested.connect(self.copy_from_viewer)
        self.viewer.load(self.media_paths, idx)
        self.main_stack.addWidget(self.viewer)
        self.nav_toolbar.hide()
        self.main_stack.setCurrentWidget(self.viewer)
        self.showFullScreen()
        self.viewer.setFocus()

    def copy_from_viewer(self, path):
        copy_files_to_clipboard([Path(path)])
        if self.viewer:
            self.viewer.setFocus()

    def delete_from_viewer(self, path):
        if not self.viewer:
            return
        path = Path(path)
        if not path.exists():
            self.viewer.remove_current_after_delete(str(path))
            self.populate_list()
            return
        answer = QMessageBox.question(
            self,
            "Delete",
            f"Move this file to recycle bin?\n\nFile: {path.name}\nPath: {path}",
        )
        if answer != QMessageBox.Yes:
            self.viewer.setFocus()
            return
        try:
            send_to_recycle_bin(path)
        except Exception:
            QMessageBox.warning(self, "Delete failed", f"Could not move to recycle bin:\n{path}")
            self.viewer.setFocus()
            return
        self.media_paths = [p for p in self.media_paths if p != str(path)]
        self.viewer.remove_current_after_delete(str(path))
        self.populate_list()
        if self.viewer:
            self.viewer.setFocus()

    def exit_viewer_mode(self):
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
        self.populate_list()
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
                if event.key() == Qt.Key_Backspace:
                    self.go_back()
                    return True
        return super().eventFilter(obj, event)

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name")
        if ok and name.strip():
            (self.current_folder / name.strip()).mkdir(exist_ok=True)
            self.populate_list()

    def rename_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        path = paths[0]
        name, ok = QInputDialog.getText(self, "Rename", "New name", text=path.name)
        if ok and name.strip() and name.strip() != path.name:
            path.rename(path.with_name(name.strip()))
            self.populate_list()

    def delete_selected(self):
        paths = self.selected_paths()
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

    def list_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Open Viewer", self.open_selected_viewer)
        selected_dirs = [p for p in self.selected_paths() if p.is_dir()]
        if selected_dirs:
            menu.addAction("Add Folder to Shortcuts", lambda p=selected_dirs[0]: self.add_quick_path(str(p)))
            menu.addSeparator()
        menu.addAction("Rename", self.rename_selected)
        menu.addAction("Delete", self.delete_selected)
        menu.addAction("New Folder", self.new_folder)
        menu.addAction("Open in Explorer", self.open_in_explorer)
        menu.exec(self.list.mapToGlobal(pos))

    def details_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Open Viewer", self.open_selected_viewer)
        selected_dirs = [p for p in self.selected_paths() if p.is_dir()]
        if selected_dirs:
            menu.addAction("Add Folder to Shortcuts", lambda p=selected_dirs[0]: self.add_quick_path(str(p)))
            menu.addSeparator()
        menu.addAction("Rename", self.rename_selected)
        menu.addAction("Delete", self.delete_selected)
        menu.addAction("New Folder", self.new_folder)
        menu.addAction("Open in Explorer", self.open_in_explorer)
        menu.exec(self.details.mapToGlobal(pos))

    def tree_menu(self, pos):
        menu = QMenu(self)
        index = self.tree.indexAt(pos)
        path = Path(self.tree_model.filePath(index)) if index.isValid() else self.current_folder
        if path.exists() and path.is_dir():
            menu.addAction("Add to Shortcuts", lambda p=path: self.add_quick_path(str(p)))
            menu.addSeparator()
        menu.addAction("New Folder", self.new_folder)
        menu.addAction("Open in Explorer", self.open_in_explorer)
        menu.exec(self.tree.mapToGlobal(pos))

    def open_in_explorer(self):
        os.startfile(str(self.current_folder))

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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    startup_path = sys.argv[1] if len(sys.argv) > 1 else None
    win = MainWindow(startup_path=startup_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
