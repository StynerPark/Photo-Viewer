import copy
import os
import tempfile
import threading
import time
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QKeyEvent, QMouseEvent, QPalette, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem

import main


class RebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        widgets = list(self.app.allWidgets())
        for widget in widgets:
            if isinstance(widget, main.MainWindow):
                widget.close()
        for widget in widgets:
            if isinstance(widget, main.ViewerWindow):
                widget.deactivate()
                widget.shutdown_video_cleanup()
                widget.close()
        for widget in widgets:
            if isinstance(widget, main.MainWindow):
                for pool_name in ("folder_scan_pool", "thumbnail_pool", "archive_pool"):
                    pool = getattr(widget, pool_name, None)
                    if pool is not None:
                        pool.clear()
                        pool.waitForDone(5000)
            elif isinstance(widget, main.ViewerWindow):
                for pool_name in ("decode_pool", "preload_decode_pool", "animated_image_pool"):
                    pool = getattr(widget, pool_name, None)
                    if pool is not None:
                        pool.clear()
                        pool.waitForDone(5000)
                for thread_name in ("video_start_thread", "video_cleanup_thread"):
                    thread = getattr(widget, thread_name, None)
                    if thread is not None and thread.is_alive():
                        thread.join(timeout=1)
        for widget in widgets:
            if isinstance(widget, (main.MainWindow, main.ViewerWindow)):
                widget.deleteLater()
        for _ in range(5):
            self.app.processEvents()
        self.tempdir.cleanup()

    def make_media_folder(self, count=24):
        for index in range(count):
            image = Image.new("RGB", (320 + index, 240 + index), (index, 80, 140))
            image.save(self.root / f"image_{index:03d}.jpg", quality=80)
        (self.root / "folder_a").mkdir(exist_ok=True)
        return self.root

    def make_animated_gif(self, path, frame_count=10, size=(320, 180), duration=35):
        frames = []
        for index in range(frame_count):
            frame = Image.new("RGBA", size, (0, 0, 0, 0))
            left = (index * 19) % max(1, size[0] - 60)
            for x in range(left, min(size[0], left + 60)):
                for y in range(30, min(size[1], 120)):
                    frame.putpixel((x, y), (20 + index * 15, 90, 180, 255))
            frames.append(frame)
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            disposal=2,
            transparency=0,
        )
        return path

    def pump_events(self, milliseconds=150):
        deadline = time.monotonic() + milliseconds / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)

    def wait_for_video_start(self, viewer, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and (
            viewer.video_start_inflight
            or viewer.video_player_create_inflight
            or viewer.pending_video_requests
        ):
            self.app.processEvents()
            time.sleep(0.002)
        self.assertEqual(viewer.video_start_inflight, 0)
        self.assertFalse(viewer.pending_video_requests)

    def fake_vlc(self, delay=0.2, stop_delay=0, play_delay=0):
        state = {"players": [], "plays": 0, "instances": 0, "play_threads": []}

        class FakeEventManager:
            def __init__(self):
                self.callbacks = {}

            def event_detach(self, event_type, *_args):
                self.callbacks.pop(event_type, None)

            def event_attach(self, *_args):
                if len(_args) >= 2:
                    self.callbacks[_args[0]] = _args[1]
                return None

            def trigger(self, event_type):
                callback = self.callbacks.get(event_type)
                if callback is not None:
                    callback(None)

        class FakePlayer:
            def __init__(self):
                self.media = None
                self.hwnd = None
                self.stop_calls = 0
                self.release_calls = 0
                self.pause_calls = 0
                self.volume_values = []
                self.mute_values = []
                self.set_times = []
                self.rate_values = []
                self.scale_values = []
                self.aspect_values = []
                self.crop_values = []
                self.hwnd_values = []
                self.operations = []
                self.current_time = 0
                self.vout_count = 1
                self.play_state = "stopped"
                self.manager = FakeEventManager()
                state["players"].append(self)

            def video_set_mouse_input(self, _enabled):
                return None

            def video_set_key_input(self, _enabled):
                return None

            def video_get_size(self, _index=0):
                return (480, 854)

            def video_set_scale(self, value):
                self.scale_values.append(float(value))
                return None

            def video_set_aspect_ratio(self, value):
                self.aspect_values.append(value)
                return None

            def video_set_crop_geometry(self, value):
                self.crop_values.append(value)
                return None

            def event_manager(self):
                return self.manager

            def set_media(self, media):
                self.media = media
                self.current_time = 0
                self.operations.append(("media", media))

            def get_media(self):
                return self.media

            def set_hwnd(self, hwnd):
                self.hwnd = hwnd
                self.hwnd_values.append(hwnd)
                self.operations.append(("hwnd", hwnd))

            def play(self):
                state["play_threads"].append(threading.get_ident())
                if play_delay:
                    time.sleep(play_delay)
                state["plays"] += 1
                self.play_state = "playing"
                return 0

            def audio_set_volume(self, value):
                self.volume_values.append(value)
                return None

            def audio_set_mute(self, muted):
                self.mute_values.append(bool(muted))
                return None

            def set_pause(self, paused):
                self.pause_calls += 1
                self.play_state = "paused" if paused else "playing"
                self.operations.append(("pause", int(bool(paused))))
                return None

            def pause(self):
                self.pause_calls += 1
                self.play_state = "paused"
                return None

            def set_time(self, value):
                self.set_times.append(value)
                self.current_time = int(value)
                return None

            def set_position(self, _value):
                self.play_state = "ended"
                self.vout_count = 0
                return None

            def get_time(self):
                return self.current_time

            def has_vout(self):
                return self.vout_count

            def get_state(self):
                return self.play_state

            def set_rate(self, value):
                self.rate_values.append(float(value))
                return 0

            def stop(self):
                if stop_delay:
                    time.sleep(stop_delay)
                self.stop_calls += 1
                self.play_state = "stopped"
                self.operations.append(("stop", None))
                return None

            def release(self):
                self.release_calls += 1
                self.operations.append(("release", None))
                return None

        class FakeInstance:
            def media_player_new(self):
                return FakePlayer()

            def media_new(self, path):
                return str(path)

            def release(self):
                return None

        class FakeVlc:
            class EventType:
                MediaPlayerEndReached = object()
                MediaPlayerVout = object()
                MediaPlayerTimeChanged = object()

            class State:
                Playing = "playing"
                Paused = "paused"
                Stopped = "stopped"
                Ended = "ended"
                Error = "error"

            @staticmethod
            def Instance(*_args):
                state["instances"] += 1
                time.sleep(delay)
                return FakeInstance()

        return FakeVlc, state

    def test_media_boundaries_are_true_noops(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.items = [Path("first.jpg"), Path("last.jpg")]
        viewer.viewer_mode = "single"
        calls = {"stop": 0, "show": 0}
        viewer.stop_media = lambda: calls.__setitem__("stop", calls["stop"] + 1)
        viewer.show_current = lambda reset=False: calls.__setitem__("show", calls["show"] + 1)
        viewer.index = 0
        viewer.previous_media()
        viewer.first_media()
        viewer.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_PageUp, Qt.NoModifier))
        viewer.handle_wheel_delta(120)
        self.assertEqual(calls, {"stop": 0, "show": 0})
        viewer.index = 1
        viewer.next_media()
        viewer.last_media()
        viewer.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_PageDown, Qt.NoModifier))
        viewer.handle_wheel_delta(-120)
        self.assertEqual(calls, {"stop": 0, "show": 0})
        viewer.handle_space()
        self.assertEqual(viewer.index, 0)
        self.assertEqual(calls, {"stop": 0, "show": 1})
        viewer.close()

    def test_sort_view_and_cached_reentry_do_not_rescan(self):
        media_folder = self.make_media_folder()
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and len(window.entries) < 25:
                self.app.processEvents()
                time.sleep(0.002)
            scans = 0
            original_scan = window.scan_folder_entries

            def counted_scan(folder, cancel_check=None):
                nonlocal scans
                scans += 1
                return original_scan(folder, cancel_check=cancel_check)

            window.scan_folder_entries = counted_scan
            window.load_folder(media_folder, add_history=False)
            window.set_sort_from_header("name", ascending=False)
            window.change_view_mode("details")
            window.change_view_mode("large")
            self.assertEqual(scans, 0)
            window.close()
            window.thumbnail_pool.clear()
            window.thumbnail_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)

    def test_numeric_filenames_use_natural_order_in_folder_zip_and_viewer_lists(self):
        names = ["1.jpg", "10.jpg", "11.jpg", "2.jpg", "20.jpg", "3.jpg"]
        entries = [main.MediaItem(Path(name)) for name in names]

        ordered = main.MainWindow.sorted_entries(None, entries, "name", True)

        self.assertEqual(
            [entry.display_name for entry in ordered],
            ["1.jpg", "2.jpg", "3.jpg", "10.jpg", "11.jpg", "20.jpg"],
        )
        self.assertEqual(
            [str(entry.path) for entry in ordered if main.is_media(entry.path)],
            ["1.jpg", "2.jpg", "3.jpg", "10.jpg", "11.jpg", "20.jpg"],
        )

    def test_natural_order_handles_mixed_zero_padding_and_text(self):
        names = ["page10.jpg", "page002.jpg", "page2.jpg", "page01.jpg", "page1.jpg"]

        self.assertEqual(
            sorted(names, key=main.natural_sort_key),
            ["page1.jpg", "page01.jpg", "page2.jpg", "page002.jpg", "page10.jpg"],
        )

    def test_preview_and_viewer_entry_do_not_decode_on_ui_thread(self):
        image_path = self.root / "large.jpg"
        Image.new("RGB", (6000, 4000), (20, 40, 60)).save(image_path, quality=82)
        preview = main.PreviewPanel()
        started = time.perf_counter()
        preview.show_path(str(image_path))
        self.assertLess(time.perf_counter() - started, 0.05)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1280, 720)
        viewer.items = [image_path]
        stat = image_path.stat()
        viewer.item_signatures[str(image_path)] = (stat.st_size, stat.st_mtime)
        started = time.perf_counter()
        viewer.show_current()
        self.assertLess(time.perf_counter() - started, 0.08)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.app.processEvents()
            if viewer.labels and not viewer.labels[0][0]._viewer_pixmap.isNull():
                break
            time.sleep(0.002)
        self.assertTrue(viewer.labels)
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        viewer.deactivate()
        viewer.close()
        preview._pool.clear()
        preview._pool.waitForDone(5000)
        viewer.decode_pool.waitForDone(5000)
        viewer.preload_decode_pool.waitForDone(5000)

    def test_rapid_navigation_keeps_a_frame_and_prioritizes_the_final_image(self):
        paths = []
        for index in range(7):
            path = self.root / f"rapid_{index}.jpg"
            Image.new("RGB", (3600, 2400), (20 + index * 12, 60, 110)).save(path, quality=91)
            paths.append(path)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1280, 720)
        viewer.show()
        viewer.load(paths, 0)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if viewer.labels and not viewer.labels[0][0]._viewer_pixmap.isNull():
                break
            time.sleep(0.002)
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        for _ in range(len(paths) - 1):
            viewer.next_media()
        self.assertEqual(viewer.index, len(paths) - 1)
        self.assertTrue(viewer.labels)
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        final_key = viewer.viewer_pixmap_cache_key(paths[-1])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and final_key not in viewer.viewer_pixmap_cache:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIn(final_key, viewer.viewer_pixmap_cache)
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        viewer.deactivate()
        viewer.close()
        viewer.decode_pool.waitForDone(5000)
        viewer.preload_decode_pool.waitForDone(5000)

    def test_static_image_navigation_reuses_the_painted_label(self):
        paths = []
        for index, color in enumerate(((18, 36, 54), (72, 90, 108), (126, 144, 162))):
            path = self.root / f"steady_{index}.jpg"
            Image.new("RGB", (960, 540), color).save(path, quality=90)
            paths.append(path)
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["performance_profile"] = "conservative"
        viewer = main.ViewerWindow(settings)
        viewer.resize(1000, 700)
        viewer.show()
        viewer.load(paths, 0)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.app.processEvents()
            if viewer.labels and not viewer.labels[0][0]._viewer_pixmap.isNull():
                break
            time.sleep(0.002)
        original_label = viewer.labels[0][0]
        self.assertFalse(original_label._viewer_pixmap.isNull())

        viewer.next_media()

        self.assertIs(viewer.labels[0][0], original_label)
        self.assertEqual(viewer.labels[0][1], paths[1])
        self.assertFalse(original_label._viewer_pixmap.isNull())
        self.assertTrue(viewer.central.updatesEnabled())
        deadline = time.monotonic() + 2
        target_key = viewer.viewer_pixmap_cache_key(paths[1])
        while time.monotonic() < deadline and target_key not in viewer.viewer_pixmap_cache:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIn(target_key, viewer.viewer_pixmap_cache)
        self.assertIs(viewer.labels[0][0], original_label)
        viewer.deactivate()
        viewer.close()
        viewer.decode_pool.waitForDone(5000)
        viewer.preload_decode_pool.waitForDone(5000)

    def test_webtoon_labels_keep_each_images_full_aspect_ratio(self):
        paths = []
        for index, size in enumerate(((900, 1800), (1000, 1500), (800, 2000))):
            path = self.root / f"webtoon_{index}.jpg"
            Image.new("RGB", size, (30 + index * 40, 80, 150)).save(path, quality=85)
            paths.append(path)
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["default_viewer_mode"] = "webtoon"
        viewer = main.ViewerWindow(settings)
        viewer.viewer_mode = "webtoon_vertical"
        viewer.resize(1000, 720)
        viewer.show()
        viewer.load(paths, 0)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(viewer.webtoon_loaded) < len(paths):
            self.app.processEvents()
            time.sleep(0.002)
        self.assertEqual(len(viewer.labels), len(paths))
        self.assertEqual(len(viewer.webtoon_loaded), len(paths))
        for label, _ in viewer.labels:
            pixmap = label.pixmap()
            self.assertIsNotNone(pixmap)
            self.assertFalse(pixmap.isNull())
            self.assertEqual(label.size(), pixmap.size())
            self.assertGreater(label.height(), 120)
        self.pump_events(50)
        for index in range(1, len(viewer.labels)):
            previous = viewer.labels[index - 1][0]
            current = viewer.labels[index][0]
            self.assertGreaterEqual(current.y(), previous.y() + previous.height())
        self.assertGreater(viewer.webtoon_scroll.verticalScrollBar().maximum(), 0)
        viewer.deactivate()
        viewer.close()
        viewer.decode_pool.waitForDone(5000)
        viewer.preload_decode_pool.waitForDone(5000)

    def test_animated_gif_decodes_off_ui_thread_and_cancels_on_exit(self):
        gif = self.make_animated_gif(self.root / "animated.gif")
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [gif]
        ui_thread = threading.get_ident()
        decode_threads = []
        original_open = main.Image.open

        def tracked_open(*args, **kwargs):
            decode_threads.append(threading.get_ident())
            return original_open(*args, **kwargs)

        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(5)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        with mock.patch.object(main.Image, "open", side_effect=tracked_open):
            heartbeat.start()
            started = time.perf_counter()
            viewer.show_current()
            self.assertLess(time.perf_counter() - started, 0.08)
            deadline = time.monotonic() + 3
            progressed = False
            while time.monotonic() < deadline:
                self.app.processEvents()
                states = list(viewer.animated_image_states.values())
                if states and states[0].get("has_frame") and states[0].get("index", 0) >= 1:
                    progressed = True
                    break
                time.sleep(0.002)
            heartbeat.stop()
            self.assertTrue(progressed)
            self.assertTrue(decode_threads)
            self.assertTrue(all(thread_id != ui_thread for thread_id in decode_threads))
            self.assertGreaterEqual(len(ticks), 5)
            if len(ticks) > 1:
                self.assertLess(max(b - a for a, b in zip(ticks, ticks[1:])), 0.12)
            self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
            self.assertTrue(viewer.current_has_animation)
            self.assertFalse(viewer.animated_rate_btn.isHidden())
            rotate_layout = viewer.rotation_overlay.layout()
            self.assertLess(rotate_layout.indexOf(viewer.rotate_right_btn), rotate_layout.indexOf(viewer.animated_rate_btn))
            self.assertTrue(viewer.set_playback_rate("0.5x"))
            active_task = next(iter(viewer.animated_image_states.values())).get("task")
            self.assertIsNotNone(active_task)
            self.assertEqual(active_task.rate_snapshot()[1], 0.5)
            self.assertEqual(viewer.animated_rate_btn.text(), "0.5x")
            viewer.deactivate()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.animated_image_task_refs:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertFalse(viewer.animated_image_states)
            self.assertFalse(viewer.animated_image_task_refs)
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_static_webp_never_starts_the_animation_worker(self):
        webp = self.root / "static.webp"
        Image.new("RGB", (800, 1000), (30, 70, 120)).save(webp, format="WEBP", quality=85)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [webp]
        viewer.show_current()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (
            not viewer.labels or viewer.labels[0][0]._viewer_pixmap.isNull()
        ):
            self.app.processEvents()
            time.sleep(0.002)
        self.assertFalse(viewer.is_animated_image_path(webp))
        self.assertFalse(viewer.animated_image_states)
        self.assertFalse(viewer.animated_image_task_refs)
        self.assertFalse(viewer.current_has_animation)
        self.assertTrue(viewer.animated_rate_btn.isHidden())
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        viewer.deactivate()
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_animated_webp_still_uses_the_animation_worker(self):
        webp = self.root / "animated.webp"
        frames = [
            Image.new("RGB", (320, 180), color)
            for color in ((180, 20, 20), (20, 180, 20), (20, 20, 180))
        ]
        frames[0].save(
            webp,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=60,
            loop=0,
        )
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [webp]
        viewer.show_current()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not viewer.current_has_animation:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertTrue(viewer.is_animated_image_path(webp))
        self.assertTrue(viewer.current_has_animation)
        self.assertTrue(viewer.animated_image_states)
        self.assertFalse(viewer.animated_rate_btn.isHidden())
        viewer.deactivate()
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_animated_webp_duration_parser_reads_anmf_timestamps(self):
        path = self.root / "timed.webp"
        chunks = []
        for duration in (30, 40, 50):
            frame_header = b"\0" * 12 + int(duration).to_bytes(3, "little") + b"\0"
            chunks.append(b"ANMF" + len(frame_header).to_bytes(4, "little") + frame_header)
        body = b"WEBP" + b"".join(chunks)
        path.write_bytes(b"RIFF" + len(body).to_bytes(4, "little") + body)
        self.assertEqual(main.animated_webp_frame_durations(path), [30, 40, 50])
        self.assertEqual(main.animated_webp_frame_durations(self.root / "not-webp.gif"), [])

    def test_triple_animated_images_use_distinct_bounded_workers(self):
        gifs = [self.make_animated_gif(self.root / f"triple_{index}.gif", frame_count=6, size=(180, 120)) for index in range(3)]
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.viewer_mode = "triple"
        viewer.step_mode = "page"
        viewer.show()
        viewer.items = gifs
        viewer.show_current()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.app.processEvents()
            states = list(viewer.animated_image_states.values())
            if len(states) == 3 and all(state.get("has_frame") for state in states):
                break
            time.sleep(0.002)
        states = list(viewer.animated_image_states.values())
        self.assertEqual(len(states), 3)
        self.assertTrue(all(state.get("has_frame") for state in states))
        self.assertEqual(len({state.get("token") for state in states}), 3)
        self.assertLessEqual(viewer.animated_image_pool.maxThreadCount(), 3)
        viewer.deactivate()
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_viewer_exit_restores_cached_explorer_rows_without_rescan(self):
        media_folder = self.make_media_folder(10)
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            window.settings.update(settings)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(window.entries) < 11:
                self.app.processEvents()
                time.sleep(0.002)
            image_path = next(entry.path for entry in window.entries if not entry.is_dir)
            expected = len(window.entries)
            self.assertTrue(window.open_viewer_for(image_path))
            window.exit_viewer_mode()
            self.assertEqual(len(window.entries), expected)
            self.assertEqual(window.list.count(), expected)
            window.close()
            if window.viewer:
                window.viewer.decode_pool.waitForDone(5000)
                window.viewer.preload_decode_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_default_viewer_mode_applies_only_at_application_session_start(self):
        media_folder = self.make_media_folder(4)
        first = next(media_folder.glob("*.jpg"))
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings["default_viewer_mode"] = "single"
        # A mode saved by an older session must not override the configured
        # startup default when a new application session is created.
        settings["viewer_mode"] = "webtoon_vertical"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.media_paths:
                self.app.processEvents()
                time.sleep(0.002)

            self.assertTrue(window.open_viewer_for(first))
            self.assertEqual(window.viewer.viewer_mode, "single")

            window.viewer.set_viewer_mode("webtoon_vertical")
            window.exit_viewer_mode()
            self.assertTrue(window.open_viewer_for(first))
            self.assertEqual(window.viewer.viewer_mode, "webtoon_vertical")

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_external_media_open_schedules_foreground_activation(self):
        media_folder = self.make_media_folder(4)
        first = next(media_folder.glob("*.jpg"))
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.media_paths:
                self.app.processEvents()
                time.sleep(0.002)

            with mock.patch.object(window, "activate_from_external_request") as activate:
                window.open_external_request(first)
                self.pump_events(180)
                self.assertGreaterEqual(activate.call_count, 3)
                self.assertIs(window.main_stack.currentWidget(), window.viewer)

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_external_media_open_replaces_stale_explorer_folder_context(self):
        first_folder = self.root / "aaaa"
        second_folder = self.root / "Downloads"
        first_folder.mkdir()
        second_folder.mkdir()
        for index in range(3):
            Image.new("RGB", (320, 240), (30 + index, 70, 120)).save(
                first_folder / f"first_{index}.jpg",
                quality=80,
            )
            Image.new("RGB", (360, 260), (80, 40 + index, 140)).save(
                second_folder / f"second_{index}.jpg",
                quality=80,
            )
        first = first_folder / "first_0.jpg"
        second = second_folder / "second_1.jpg"
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(first_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 3:
                self.app.processEvents()
                time.sleep(0.002)

            self.assertTrue(window.open_viewer_for(first))
            window.open_external_request(second)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and (
                len(window.entries) < 3
                or any(entry.path.parent != second_folder for entry in window.entries)
            ):
                self.app.processEvents()
                time.sleep(0.002)

            window.exit_viewer_mode()
            self.assertEqual(window.current_folder, second_folder)
            self.assertEqual(Path(window.display_path), second_folder)
            self.assertEqual(Path(window.tabs[window.current_tab]["path"]), second_folder)
            self.assertEqual(len(window.entries), 3)
            self.assertTrue(all(entry.path.parent == second_folder for entry in window.entries))
            self.assertIn(str(second), window.media_paths)
            self.assertEqual(
                window.details.rowCount() if window.view_combo.currentText() == "details" else window.list.count(),
                3,
            )

            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_external_media_open_rescans_an_inactive_cached_folder(self):
        first_folder = self.root / "A"
        second_folder = self.root / "B"
        first_folder.mkdir()
        second_folder.mkdir()
        for index in range(1, 3):
            Image.new("RGB", (320, 240), (30 * index, 70, 120)).save(
                first_folder / f"{index}.jpg",
                quality=80,
            )
            Image.new("RGB", (360, 260), (80, 40 * index, 140)).save(
                second_folder / f"{index}.jpg",
                quality=80,
            )
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            # Visit B once so it has a valid but soon-to-be-stale cache, then
            # leave it inactive while its contents change.
            window = main.MainWindow(second_folder)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(window.entries) < 2:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(len(window.entries), 2)

            window.load_folder(first_folder, add_history=False)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (
                len(window.entries) < 2
                or any(entry.path.parent != first_folder for entry in window.entries)
            ):
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(window.open_viewer_for(first_folder / "1.jpg"))

            clicked = second_folder / "3.jpg"
            sibling = second_folder / "4.jpg"
            Image.new("RGB", (380, 280), (120, 90, 40)).save(clicked, quality=80)
            Image.new("RGB", (400, 300), (140, 100, 50)).save(sibling, quality=80)

            window.open_external_request(clicked)
            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            self.assertEqual(window.viewer.items[window.viewer.index], clicked)

            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and len(window.viewer.items) < 4:
                self.app.processEvents()
                time.sleep(0.002)

            self.assertEqual(
                [path.name for path in window.viewer.items],
                ["1.jpg", "2.jpg", "3.jpg", "4.jpg"],
            )
            self.assertIn(sibling, window.viewer.items)
            self.assertEqual(window.viewer.items[window.viewer.index], clicked)

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_late_old_folder_scan_cannot_overwrite_external_media_folder(self):
        first_folder = self.root / "slow_old"
        second_folder = self.root / "new_target"
        first_folder.mkdir()
        second_folder.mkdir()
        for index in range(4):
            Image.new("RGB", (300, 220), (20, 60 + index, 100)).save(first_folder / f"old_{index}.jpg")
            Image.new("RGB", (340, 250), (90, 40, 130 + index)).save(second_folder / f"new_{index}.jpg")
        target = second_folder / "new_2.jpg"
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(first_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 4:
                self.app.processEvents()
                time.sleep(0.002)

            original_scan = window.scan_folder_entries
            old_scan_started = threading.Event()
            release_old_scan = threading.Event()

            def delayed_scan(folder, cancel_check=None):
                if Path(folder) == first_folder and not old_scan_started.is_set():
                    old_scan_started.set()
                    release_old_scan.wait(1)
                return original_scan(folder, cancel_check=cancel_check)

            window.scan_folder_entries = delayed_scan
            window.load_folder(first_folder, add_history=False, force=True)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not old_scan_started.is_set():
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(old_scan_started.is_set())

            window.open_external_request(target)
            release_old_scan.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (
                len(window.entries) < 4
                or any(entry.path.parent != second_folder for entry in window.entries)
            ):
                self.app.processEvents()
                time.sleep(0.002)

            self.assertEqual(window.current_folder, second_folder)
            self.assertEqual(len(window.entries), 4)
            self.assertTrue(all(entry.path.parent == second_folder for entry in window.entries))
            self.assertTrue(all("old_" not in entry.path.name for entry in window.entries))

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_windowed_viewer_has_no_persistent_top_left_filename_badge(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.show()
        self.app.processEvents()

        self.assertIsNone(viewer.findChild(main.QLabel, "cornerFilenameLabel"))
        self.assertTrue(viewer.top_filename_label is not None)
        self.assertFalse(viewer.viewer_overlay.isVisible())

        viewer.close()
        viewer.decode_pool.waitForDone(5000)
        viewer.preload_decode_pool.waitForDone(5000)

    def test_viewer_overlay_labels_remain_readable_on_dark_overlay(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.show()
        viewer.viewer_overlay.show()
        viewer.rotation_overlay.show()
        viewer.video_overlay.show()
        self.app.processEvents()

        expected = QColor("#f5f1fc")
        labels = [
            viewer.top_filename_label,
            viewer.rotation_filename_label,
            viewer.video_filename_label,
            viewer.time_label,
        ]
        labels.extend(viewer.viewer_overlay.findChildren(main.QLabel))
        labels.extend(viewer.video_overlay.findChildren(main.QLabel))
        self.assertTrue(labels)
        for label in labels:
            self.assertEqual(label.palette().color(QPalette.WindowText), expected)

        viewer.close()

    def test_plain_plus_and_minus_keys_switch_to_manual_and_zoom(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.show()
        self.app.processEvents()
        viewer.fit_mode = "fit_height"
        viewer.zoom_factor = 1.0

        plus = QKeyEvent(QEvent.KeyPress, Qt.Key_Plus, Qt.ShiftModifier, "+")
        viewer.keyPressEvent(plus)
        self.assertTrue(plus.isAccepted())
        self.assertEqual(viewer.fit_mode, "manual")
        self.assertAlmostEqual(viewer.zoom_factor, 1.15)

        minus = QKeyEvent(QEvent.KeyPress, Qt.Key_Minus, Qt.KeypadModifier, "-")
        self.assertTrue(viewer.eventFilter(viewer.central, minus))
        self.assertTrue(minus.isAccepted())
        self.assertEqual(viewer.fit_mode, "manual")
        self.assertAlmostEqual(viewer.zoom_factor, 1.0)

        viewer.close()

    def test_windows_foreground_activation_is_not_persistently_topmost(self):
        window = main.MainWindow(self.root)
        fake_user32 = mock.Mock()
        fake_user32.GetForegroundWindow.return_value = 9001
        fake_user32.GetWindowThreadProcessId.side_effect = [111, 222]
        fake_user32.AttachThreadInput.return_value = 1
        fake_loader = mock.Mock()
        fake_loader.user32 = fake_user32

        with mock.patch.object(main.sys, "platform", "win32"), mock.patch.object(main.ctypes, "windll", fake_loader):
            window.activate_from_external_request()

        hwnd = int(window.winId())
        fake_user32.ShowWindow.assert_called_once_with(hwnd, 5)
        fake_user32.BringWindowToTop.assert_called_once_with(hwnd)
        self.assertEqual(fake_user32.SetWindowPos.call_count, 2)
        self.assertEqual(fake_user32.SetWindowPos.call_args_list[0].args[1], -1)
        self.assertEqual(fake_user32.SetWindowPos.call_args_list[1].args[1], -2)
        fake_user32.SetForegroundWindow.assert_called_once_with(hwnd)
        fake_user32.SetActiveWindow.assert_called_once_with(hwnd)
        self.assertEqual(
            fake_user32.AttachThreadInput.call_args_list,
            [mock.call(111, 222, True), mock.call(111, 222, False)],
        )

        window.close()
        window.folder_scan_pool.waitForDone(5000)
        window.thumbnail_pool.waitForDone(5000)

    def test_delete_in_viewer_keeps_viewer_and_selects_the_next_image(self):
        media_folder = self.make_media_folder(4)
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.media_paths) < 4:
                self.app.processEvents()
                time.sleep(0.002)
            first = Path(window.media_paths[0])
            expected_next = Path(window.media_paths[1])
            self.assertTrue(window.open_viewer_for(first))

            delete_attempts = 0

            def delete_after_one_busy_error(target):
                nonlocal delete_attempts
                delete_attempts += 1
                if delete_attempts == 1:
                    error = PermissionError("media decoder still owns the file")
                    error.winerror = 32
                    raise error
                Path(target).unlink()

            with (
                mock.patch.object(main, "send_to_recycle_bin", side_effect=delete_after_one_busy_error),
                mock.patch.object(
                    main.QMessageBox,
                    "warning",
                    side_effect=AssertionError("Viewer deletion unexpectedly opened an error dialog"),
                ),
            ):
                window.delete_from_viewer(first)

            self.assertEqual(delete_attempts, 2)
            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            self.assertNotIn(first, window.viewer.items)
            self.assertEqual(window.viewer.items[window.viewer.index], expected_next)
            self.assertEqual(len(window.viewer.items), 3)

            window.viewer.index = len(window.viewer.items) - 1
            last = window.viewer.items[-1]
            expected_previous = window.viewer.items[-2]
            with (
                mock.patch.object(main, "send_to_recycle_bin", side_effect=lambda target: Path(target).unlink()),
                mock.patch.object(
                    main.QMessageBox,
                    "warning",
                    side_effect=AssertionError("Viewer deletion unexpectedly opened an error dialog"),
                ),
            ):
                window.delete_from_viewer(last)

            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            self.assertNotIn(last, window.viewer.items)
            self.assertEqual(window.viewer.items[window.viewer.index], expected_previous)
            self.assertEqual(len(window.viewer.items), 2)

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_delete_from_provisional_single_item_viewer_finds_remaining_folder_media(self):
        media_folder = self.make_media_folder(4)
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.media_paths) < 4:
                self.app.processEvents()
                time.sleep(0.002)
            first = Path(window.media_paths[0])
            self.assertTrue(window.open_viewer_for(first))
            window.viewer.items = [first]
            window.viewer.index = 0
            window.media_paths = [str(first)]
            window.startup_media_scan_paths = []
            window.startup_media_scan_seen = {str(first)}
            window.startup_media_path = first
            window.startup_media_scan_target = str(first)

            with mock.patch.object(main, "send_to_recycle_bin", side_effect=lambda target: Path(target).unlink()):
                window.delete_from_viewer(first)

            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            self.assertEqual(len(window.viewer.items), 3)
            self.assertTrue(all(item.exists() for item in window.viewer.items))
            self.assertNotEqual(window.startup_media_scan_target, str(first))

            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_direct_startup_media_scans_once_in_background_and_defers_hidden_rows(self):
        folder = self.root / "large_direct_open"
        folder.mkdir()
        for index in range(1200):
            (folder / f"media_{index:05d}.jpg").write_bytes(b"not-decoded-during-hidden-scan")
        first = folder / "media_00000.jpg"
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(first)
            window.show()
            heartbeat = []
            timer = QTimer()
            timer.setInterval(5)
            timer.timeout.connect(lambda: heartbeat.append(time.perf_counter()))
            timer.start()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and len(window.entries) < 1200:
                self.app.processEvents()
                time.sleep(0.001)
            timer.stop()

            self.assertEqual(len(window.entries), 1200)
            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            self.assertIsNone(window.startup_media_scan_iter)
            self.assertFalse(window.startup_media_scan_timer.isActive())
            self.assertTrue(window.explorer_render_pending)
            self.assertEqual(window.list.count(), 0)
            self.assertEqual(window.details.rowCount(), 0)
            self.assertFalse(window.tree_sync_timer.isActive())
            gaps = [later - earlier for earlier, later in zip(heartbeat, heartbeat[1:])]
            self.assertLess(max(gaps, default=0), 0.12)

            window.exit_viewer_mode()
            self.assertFalse(window.explorer_render_pending)
            self.assertEqual(window.list.count(), 1200)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_direct_startup_scan_rebuilds_provisional_multi_page_group(self):
        folder = self.root / "direct_multi_page"
        folder.mkdir()
        for index in range(6):
            Image.new("RGB", (320, 240), (20 + index, 70, 120)).save(
                folder / f"image_{index:03d}.jpg"
            )
        first = folder / "image_002.jpg"
        settings_path = self.root / "settings.json"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        settings["default_viewer_mode"] = "double"
        settings_path.write_text(main.json.dumps(settings), encoding="utf-8")

        with mock.patch.object(main, "SETTINGS_PATH", settings_path):
            window = main.MainWindow(first)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(window.media_paths) < 6:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(len(window.viewer.items), 6)
            self.assertEqual(window.viewer.index, 2)
            self.assertEqual(window.viewer.grid.count(), 2)
            self.assertEqual(
                [path.name for _label, path in window.viewer.labels],
                ["image_002.jpg", "image_003.jpg"],
            )
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_folder_refresh_while_viewing_updates_cache_without_rendering_hidden_explorer(self):
        folder = self.make_media_folder(12)
        first = next(folder.glob("*.jpg"))
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(folder)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(window.entries) < 12:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(window.open_viewer_for(first))
            entries = list(window.entries)
            key = window.current_snapshot_key
            with mock.patch.object(window, "render_entries", wraps=window.render_entries) as render:
                window.apply_folder_entries(entries, key, lightweight=True)
                render.assert_not_called()
                self.assertTrue(window.explorer_render_pending)
                window.exit_viewer_mode()
                self.assertEqual(render.call_count, 1)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_low_spec_non_webtoon_viewer_never_queues_speculative_preloads(self):
        media_folder = self.make_media_folder(8)
        first = next(media_folder.glob("*.jpg"))
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.media_paths:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(window.media_paths)
            window.settings["performance_profile"] = "conservative"
            window.settings["default_viewer_mode"] = "single"
            self.assertTrue(window.open_viewer_for(first))
            self.pump_events(140)
            self.assertEqual(window.viewer.viewer_preload_queue, [])
            self.assertEqual(window.viewer.viewer_preload_queued, set())
            self.assertEqual(window.viewer.preload_decode_pool.activeThreadCount(), 0)
            window.exit_viewer_mode()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)
            window.viewer.decode_pool.waitForDone(5000)
            window.viewer.preload_decode_pool.waitForDone(5000)

    def test_balanced_viewer_preloads_only_the_next_screen(self):
        paths = []
        for index in range(8):
            path = self.root / f"lookahead_{index}.jpg"
            Image.new("RGB", (640, 360), (20 + index, 60, 100)).save(path, quality=85)
            paths.append(path)
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["performance_profile"] = "balanced"
        viewer = main.ViewerWindow(settings)
        viewer.items = paths
        viewer.index = 2
        viewer.viewer_mode = "single"
        viewer.step_mode = "slide"
        viewer.render_generation = 1

        viewer.queue_viewer_preloads()

        self.assertEqual(viewer.viewer_preload_queue, [paths[3]])
        self.assertEqual(viewer.viewer_preload_queued, {str(paths[3])})
        target_key = viewer.viewer_pixmap_cache_key(paths[3])
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and target_key not in viewer.viewer_pixmap_cache:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertIn(target_key, viewer.viewer_pixmap_cache)
        viewer.close()
        viewer.preload_decode_pool.waitForDone(5000)

    def test_direct_image_exit_never_returns_to_an_empty_explorer(self):
        media_folder = self.make_media_folder(6)
        image_path = media_folder / "image_000.jpg"
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["viewer_start_mode"] = "window"
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(startup_path=image_path)
            window.settings.update(settings)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and window.main_stack.currentWidget() is window.explorer_root:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertIs(window.main_stack.currentWidget(), window.viewer)
            window.entries = []
            window.list.clear()
            window.details.clear_entries()
            window.exit_viewer_mode()
            self.assertIs(window.main_stack.currentWidget(), window.explorer_root)
            visible_count = window.details.rowCount() if window.view_combo.currentText() == "details" else window.list.count()
            self.assertGreater(visible_count, 0)
            window.close()
            if window.viewer:
                window.viewer.decode_pool.waitForDone(5000)
                window.viewer.preload_decode_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_direct_view_mode_change_updates_the_visible_model(self):
        media_folder = self.make_media_folder(12)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 13:
                self.app.processEvents()
                time.sleep(0.002)
            window.change_view_mode("details")
            self.assertEqual(window.view_combo.currentText(), "details")
            self.assertEqual(window.details.rowCount(), len(window.entries))
            window.change_view_mode("large")
            self.assertEqual(window.view_combo.currentText(), "large")
            self.assertEqual(window.list.count(), len(window.entries))
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_up_resets_to_top_and_back_centers_entered_folder_in_every_view_mode(self):
        parent = self.root / "navigation_parent"
        parent.mkdir()
        children = []
        for index in range(60):
            child = parent / f"folder_{index:03d}"
            child.mkdir()
            children.append(child)
        target = children[42]
        for index in range(55):
            (target / f"nested_{index:03d}").mkdir()

        def wait_for_folder(window, folder, expected_count):
            expected_key = os.path.normcase(os.path.abspath(str(folder)))
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                current_key = os.path.normcase(os.path.abspath(str(window.current_folder)))
                if current_key == expected_key and len(window.entries) == expected_count:
                    self.pump_events(120)
                    return
                self.app.processEvents()
                time.sleep(0.002)
            self.fail(f"folder did not finish loading: {folder}")

        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            for mode in ("details", "list", "small", "medium", "large"):
                with self.subTest(mode=mode):
                    window = main.MainWindow(parent)
                    window.resize(900, 620)
                    window.show()
                    wait_for_folder(window, parent, 60)
                    window.change_view_mode(mode)
                    self.pump_events(180)

                    # Prime the child snapshot, then deliberately leave its
                    # active view at the bottom.  This reproduces the cached
                    # folder case that previously leaked the raw scrollbar
                    # value into the parent.
                    window.load_folder(target)
                    wait_for_folder(window, target, 55)
                    active_view = window.details if mode == "details" else window.list
                    active_view.verticalScrollBar().setValue(
                        active_view.verticalScrollBar().maximum()
                    )
                    self.pump_events(80)

                    window.go_up()
                    wait_for_folder(window, parent, 60)
                    self.pump_events(650)
                    self.assertEqual(active_view.verticalScrollBar().value(), 0)
                    self.assertEqual(window.selected_paths(), [])

                    # Back from the child must restore semantic context: the
                    # child row/icon is selected and placed at viewport center.
                    window.load_folder(target)
                    wait_for_folder(window, target, 55)
                    active_view.verticalScrollBar().setValue(
                        active_view.verticalScrollBar().maximum()
                    )
                    self.pump_events(80)
                    window.go_back()
                    wait_for_folder(window, parent, 60)
                    self.pump_events(650)

                    self.assertEqual(window.selected_paths(), [target])
                    if mode == "details":
                        item = window.detail_item_by_path[str(target)]
                        item_rect = window.details.visualItemRect(item)
                        viewport_rect = window.details.viewport().rect()
                    else:
                        item = window.list_item_by_path[str(target)]
                        item_rect = window.list.visualItemRect(item)
                        viewport_rect = window.list.viewport().rect()
                    self.assertLessEqual(
                        abs(item_rect.center().y() - viewport_rect.center().y()),
                        max(60, item_rect.height()),
                    )

                    window.close()
                    window.folder_scan_pool.waitForDone(5000)
                    window.thumbnail_pool.waitForDone(5000)

    def test_unc_share_up_uses_virtual_server_root_and_virtual_root_stays_put(self):
        folder = self.root / "unc_navigation"
        folder.mkdir()
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(folder)
            with mock.patch.object(window, "open_location", return_value=True) as open_location:
                window.current_folder = Path(r"\\svr\share")
                window.virtual_unc_server = ""
                window.go_up()
                open_location.assert_called_once()
                target = open_location.call_args.args[0]
                self.assertEqual(str(target).rstrip("\\"), r"\\svr")
                self.assertEqual(
                    open_location.call_args.kwargs["navigation"],
                    {"mode": "top"},
                )

                open_location.reset_mock()
                window.virtual_unc_server = "svr"
                window.go_up()
                open_location.assert_not_called()

            window.virtual_unc_server = ""
            window.current_folder = Path(r"\\svr\share")
            self.assertEqual(
                window.back_navigation_request(r"\\svr"),
                {"mode": "anchor", "anchor": str(Path(r"\\svr\share"))},
            )
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_home_end_move_to_first_and_last_items(self):
        listing = main.ThumbList()
        for index in range(8):
            listing.addItem(str(index))
        listing.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier))
        self.assertEqual(listing.currentRow(), 7)
        listing.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier))
        self.assertEqual(listing.currentRow(), 0)
        table = main.DetailsTable()
        table.setRowCount(8)
        table.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier))
        self.assertEqual(table.currentRow(), 7)
        table.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier))
        self.assertEqual(table.currentRow(), 0)

    def test_settings_cancel_is_transactional(self):
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        original = copy.deepcopy(settings)
        dialog = main.ShortcutDialog(settings)
        dialog.theme_combo.setCurrentText("light")
        dialog.default_viewer_combo.setCurrentText("webtoon")
        dialog.reject()
        self.assertEqual(settings, original)

    def test_context_menu_is_compact_and_complete(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.items = [Path("sample.jpg")]
        menu = viewer.build_context_menu()
        labels = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(labels, [
            "Zoom In", "Zoom Out", "Fit Height", "Fit Width", "Window Fit", "Original Size", "Lock",
            "Single", "Double", "Triple", "Webtoon", "Rotate Left", "Rotate Right", "Reset Rotation",
            "Cut", "Copy", "Paste", "Delete", "Properties",
        ])
        menu.ensurePolished()
        self.assertLessEqual(menu.sizeHint().width(), 300)
        self.assertLessEqual(menu.sizeHint().height(), 320)
        viewer.close()

    def test_file_copy_exports_windows_explorer_clipboard_format(self):
        target = self.root / "copy_target.jpg"
        target.write_bytes(b"image")

        class FakeClipboard:
            def __init__(self):
                self.mime = None

            def setMimeData(self, mime):
                self.mime = mime

        clipboard = FakeClipboard()
        with mock.patch.object(main.QApplication, "clipboard", return_value=clipboard):
            main.copy_files_to_clipboard([target])

        self.assertIsNotNone(clipboard.mime)
        self.assertEqual(
            [os.path.normcase(url.toLocalFile()) for url in clipboard.mime.urls()],
            [os.path.normcase(str(target))],
        )
        self.assertIn(str(target), clipboard.mime.text())
        if os.sys.platform == "win32":
            windows_format = 'application/x-qt-windows-mime;value="FileNameW"'
            self.assertIn(windows_format, clipboard.mime.formats())
            payload = bytes(clipboard.mime.data(windows_format))
            self.assertIn(str(target).encode("utf-16le"), payload)
            self.assertTrue(payload.endswith(b"\x00\x00\x00\x00"))

    def test_global_wheel_hook_requires_viewer_process_foreground(self):
        hook = main.ViewerMouseWheelHook.__new__(main.ViewerMouseWheelHook)
        hook.user32 = mock.Mock()
        hook.user32.GetForegroundWindow.return_value = 101

        def set_process_id(_hwnd, process_id):
            process_id._obj.value = os.getpid() + 1
            return 1

        hook.user32.GetWindowThreadProcessId.side_effect = set_process_id
        self.assertFalse(hook._viewer_process_is_foreground())

        def set_own_process_id(_hwnd, process_id):
            process_id._obj.value = os.getpid()
            return 1

        hook.user32.GetWindowThreadProcessId.side_effect = set_own_process_id
        self.assertTrue(hook._viewer_process_is_foreground())

    def test_region_selection_emits_only_after_selection_click(self):
        label = main.PannableImageLabel()
        label.resize(500, 400)
        pixmap = QPixmap(400, 300)
        pixmap.fill(Qt.black)
        label.setPixmap(pixmap)
        emitted = []
        label.regionZoomRequested.connect(emitted.append)
        label.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        label.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(250, 220), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        label.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(250, 220), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertFalse(emitted)
        label.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(150, 150), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertTrue(emitted)
        self.assertGreater(emitted[0].width(), 100)

    def test_explorer_structure_and_splitter_sizes_remain_v022(self):
        media_folder = self.make_media_folder(4)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            window.resize(1280, 820)
            window.show()
            self.pump_events(50)
            sizes = window.explorer_root.sizes()
            self.assertEqual(len(sizes), 2)
            self.assertTrue(250 <= sizes[0] <= 390)
            self.assertEqual(window.preview.minimumHeight(), 160)
            self.assertFalse(hasattr(window, "refresh_btn"))
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_preview_aspect_ratio_never_moves_user_splitters(self):
        landscape = self.root / "landscape.jpg"
        portrait = self.root / "portrait.jpg"
        Image.new("RGB", (1800, 600), (30, 70, 120)).save(landscape)
        Image.new("RGB", (600, 1800), (120, 70, 30)).save(portrait)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(self.root)
            window.resize(1280, 820)
            window.show()
            self.pump_events(100)
            window.explorer_root.setSizes([360, 920])
            window.left_splitter.setSizes([500, 300])
            expected_horizontal = list(window.explorer_root.sizes())
            expected_vertical = list(window.left_splitter.sizes())
            for path in (landscape, portrait, landscape):
                window.preview.show_path(str(path))
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and window.preview._source_pixmap.isNull():
                    self.app.processEvents()
                    time.sleep(0.002)
                self.pump_events(30)
                self.assertEqual(window.explorer_root.sizes(), expected_horizontal)
                self.assertEqual(window.left_splitter.sizes(), expected_vertical)
            window.close()
            window.preview._pool.clear()
            window.preview._pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_selected_tabs_do_not_use_an_accent_underline(self):
        media_folder = self.make_media_folder(2)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            stylesheet = window.styleSheet()
            self.assertNotIn("border-bottom: 2px solid", stylesheet)
            self.assertFalse(window.folder_tabs.drawBase())
            self.assertIn("background: #7962bd", stylesheet)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_viewer_popup_controls_keep_contrast_in_light_theme(self):
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["theme"] = "light"
        viewer = main.ViewerWindow(settings)
        popup = viewer.fit_combo.view()
        self.assertEqual(popup.palette().color(QPalette.Base).name(), "#211e29")
        self.assertEqual(popup.palette().color(QPalette.Text).name(), "#f5f1fc")
        self.assertEqual(popup.palette().color(QPalette.Highlight).name(), "#7560b4")
        self.assertIn("background-color: #211e29", popup.styleSheet())
        self.assertIn("color: #f5f1fc", popup.styleSheet())
        self.assertIn("background: #211e29", viewer.mode_btn.menu().styleSheet())
        self.assertIn("color: #f5f1fc", viewer.mode_btn.menu().styleSheet())
        self.assertIn("--quiet", main.VLC_INSTANCE_ARGS)
        self.assertNotIn("--vout=direct3d11", main.VLC_INSTANCE_ARGS)
        viewer.deactivate()
        viewer.shutdown_video_cleanup()
        viewer.close()
        for thread in (viewer.video_start_thread, viewer.video_cleanup_thread):
            thread.join(timeout=1)

    def test_video_fit_modes_match_image_geometry_including_fit_height(self):
        fake_vlc, state = self.fake_vlc(delay=0)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1000, 1500)
        viewer.central.resize(1000, 1500)
        frame = viewer.video_frame
        frame.resize(1000, 1500)
        viewer._native_video_frame_size = lambda _frame: QSize(1750, 2625)
        player = fake_vlc.Instance().media_player_new()
        slot = {
            "generation": viewer.render_generation,
            "player": player,
            "frame": frame,
        }

        viewer.fit_mode = "fit_height"
        viewer.zoom_factor = 1.0
        self.assertTrue(viewer.apply_video_fit(slot))
        self.assertEqual(player.scale_values[-1], 0.0)

        expected = {
            "fit_width": 0.0,
            "fit_window": 0.0,
            "actual": 1.0,
        }
        for mode, scale in expected.items():
            slot["fit_scale"] = None
            viewer.fit_mode = mode
            self.assertTrue(viewer.apply_video_fit(slot))
            self.assertAlmostEqual(player.scale_values[-1], scale, places=4)

        slot["fit_scale"] = None
        viewer.fit_mode = "manual"
        viewer.zoom_factor = 1.25
        self.assertTrue(viewer.apply_video_fit(slot))
        self.assertAlmostEqual(player.scale_values[-1], 1.25, places=4)
        viewer.deactivate()
        viewer.shutdown_video_cleanup()
        viewer.close()

    def test_feedback_details_columns_preview_quality_and_tree_font(self):
        self.assertEqual(
            main.DetailsTable.HEADERS,
            ["Filename", "Size (KB)", "Image Type", "Modified Date", "Image Properties"],
        )
        for removed in ("Date Taken", "Caption", "Rating", "Tagged"):
            self.assertNotIn(removed, main.DetailsTable.HEADERS)
        media_folder = self.make_media_folder(2)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            window.resize(1280, 820)
            window.show()
            self.pump_events(50)
            preview_target = window.preview._decode_target()
            self.assertGreater(preview_target.width(), window.preview.width())
            self.assertGreater(preview_target.height(), window.preview.height())
            stylesheet = window.styleSheet()
            self.assertIn("QTreeView { font-size: 8pt; }", stylesheet)
            self.assertIn("QTabBar#folderTabs", stylesheet)
            self.assertFalse(window.folder_tabs.drawBase())
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_extension_row_colors_and_thumbnail_badges(self):
        expected_keys = {
            "photo.jpg": "jpeg",
            "photo.png": "png",
            "photo.webp": "webp",
            "photo.gif": "gif",
            "clip.mp4": "video",
            "photo.tiff": "raster",
        }
        for path, expected in expected_keys.items():
            self.assertEqual(main.type_color_key(path), expected)
            self.assertTrue(main.type_color(path).isValid())
            self.assertTrue(main.type_color(path, dark_theme=True).isValid())
            self.assertNotEqual(
                main.type_color(path).name(),
                main.type_color(path, dark_theme=True).name(),
            )
        self.assertIsNone(main.type_color("folder", is_dir_entry=True))
        self.assertIsNone(main.type_color("archive.zip"))
        self.assertEqual(main.extension_badge_text("photo.webp"), "WEBP")
        self.assertEqual(main.extension_badge_text("clip.mp4"), "MP4")
        self.assertEqual(main.extension_badge_text("archive.zip"), "")

        self.assertEqual(main.normalize_playback_rate("1.25x"), 1.25)
        self.assertEqual(main.normalize_playback_rate("0.5"), 0.5)
        self.assertIsNone(main.normalize_playback_rate("0"))
        self.assertIsNone(main.normalize_playback_rate("fast"))
        self.assertEqual(main.format_playback_rate(1), "1.0x")
        self.assertEqual(main.format_playback_rate(0.25), "0.25x")

        thumbnail_list = main.ThumbList()
        thumbnail_list.resize(260, 260)
        white = QPixmap(192, 192)
        white.fill(QColor("white"))
        item = QListWidgetItem("photo.jpg")
        item.setData(Qt.UserRole, "photo.jpg")
        item.setIcon(QIcon(white))
        thumbnail_list.addItem(item)
        badge_rgb = main.type_badge_color("photo.jpg").rgb() & 0xFFFFFF
        thumbnail_list.show()
        for mode in ("small", "medium", "large"):
            thumbnail_list.set_view_mode_name(mode)
            self.pump_events(30)
            icon_image = thumbnail_list.grab().toImage().convertToFormat(QImage.Format_RGB32)
            icon_badge_pixels = sum(
                1
                for y in range(icon_image.height())
                for x in range(icon_image.width())
                if (icon_image.pixel(x, y) & 0xFFFFFF) == badge_rgb
            )
            self.assertGreater(icon_badge_pixels, 10, mode)

        thumbnail_list.set_dark_theme(False)
        thumbnail_list.set_view_mode_name("list")
        self.pump_events(30)
        list_image = thumbnail_list.grab().toImage().convertToFormat(QImage.Format_RGB32)
        list_badge_pixels = sum(
            1
            for y in range(list_image.height())
            for x in range(list_image.width())
            if (list_image.pixel(x, y) & 0xFFFFFF) == badge_rgb
        )
        self.assertEqual(list_badge_pixels, 0)
        self.assertEqual(item.background().color().name(), main.type_color("photo.jpg").name())

        details = main.DetailsTable()
        details._dark_theme = False
        details.setStyleSheet(
            "QTableWidget { background: #ffffff; } "
            "QTableWidget::item { padding: 4px; } "
            "QTableWidget::item:selected { background: #dcd4ff; color: #231c34; }"
        )
        details.resize(720, 140)
        details.load_entries(
            [main.MediaItem(Path("photo.jpg"), size=1024, mtime=1)],
            None,
            lambda _entry: QIcon(),
            lightweight=True,
        )
        details.show()
        self.pump_events(30)
        details_item = details.item(0, 0)
        details_rect = details.visualItemRect(details_item)
        details_image = details.viewport().grab().toImage()
        details_row_color = QColor(
            details_image.pixel(details_rect.right() - 8, details_rect.center().y())
        ).name()
        self.assertEqual(details_row_color, main.type_color("photo.jpg").name())
        details.selectRow(0)
        self.pump_events(20)
        selected_image = details.viewport().grab().toImage()
        selected = QColor(
            selected_image.pixel(details_rect.right() - 8, details_rect.center().y())
        ).name()
        self.assertEqual(selected, "#dcd4ff")
        details.close()
        thumbnail_list.close()
        details.deleteLater()
        thumbnail_list.deleteLater()
        self.app.processEvents()

    def test_thumbnail_wheel_scrolls_three_rows_per_notch(self):
        thumbnail_list = main.ThumbList()
        thumbnail_list.resize(500, 380)
        thumbnail_list.set_view_mode_name("large")
        for index in range(80):
            item = QListWidgetItem(f"image_{index:03d}.jpg")
            item.setData(Qt.UserRole, f"image_{index:03d}.jpg")
            thumbnail_list.addItem(item)
        thumbnail_list.show()
        self.pump_events(60)
        self.assertEqual(
            thumbnail_list.verticalScrollMode(),
            main.QAbstractItemView.ScrollPerPixel,
        )
        wheel = QWheelEvent(
            QPointF(20, 20),
            QPointF(20, 20),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.ScrollUpdate,
            False,
        )
        thumbnail_list.wheelEvent(wheel)
        self.assertEqual(
            thumbnail_list.verticalScrollBar().value(),
            thumbnail_list.gridSize().height() * main.THUMBNAIL_WHEEL_ROWS,
        )
        thumbnail_list.set_view_mode_name("list")
        self.assertEqual(
            thumbnail_list.verticalScrollMode(),
            main.QAbstractItemView.ScrollPerItem,
        )
        thumbnail_list.close()

    def test_historical_performance_profiles_and_single_dispatch(self):
        self.assertEqual(
            main.PERFORMANCE_PROFILES,
            {
                "conservative": {"thumbnail_workers": 1, "thumbnail_start_ms": 150, "thumbnail_gap_ms": 100},
                "balanced": {"thumbnail_workers": 2, "thumbnail_start_ms": 100, "thumbnail_gap_ms": 50},
                "fast": {"thumbnail_workers": 3, "thumbnail_start_ms": 80, "thumbnail_gap_ms": 30},
            },
        )
        media_folder = self.make_media_folder(5)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 6:
                self.app.processEvents()
                time.sleep(0.002)
            window.thumbnail_timer.stop()
            window.thumbnail_paused = False
            paths = [str(entry.path) for entry in window.entries if not entry.is_dir]
            window.thumbnail_queue = list(paths)
            submitted = []
            with mock.patch.object(window, "queue_thumbnail", side_effect=lambda path, priority=0: submitted.append(path) or True):
                window.queue_idle_thumbnail()
            self.assertEqual(len(submitted), 1)
            self.assertEqual(window.thumbnail_pool.maxThreadCount(), 2)
            self.assertEqual(window.thumbnail_start_ms, 100)
            self.assertEqual(window.thumbnail_gap_ms, 50)
            viewer = main.ViewerWindow(window.settings)
            self.assertEqual(viewer.decode_pool.maxThreadCount(), 2)
            viewer.close()
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_tab_switch_preserves_tree_structure_scroll_and_splitters(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        Image.new("RGB", (640, 480), (20, 40, 60)).save(first / "a.jpg")
        Image.new("RGB", (640, 480), (60, 40, 20)).save(second / "b.jpg")
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(first)
            window.resize(1280, 820)
            window.show()
            self.pump_events(220)
            root_index = window.tree_model.index(str(self.root))
            window.explorer_root.setSizes([345, 935])
            window.left_splitter.setSizes([510, 290])
            window.add_folder_tab(second)
            self.pump_events(120)
            root_index = window.tree_model.index(str(self.root))
            self.assertTrue(root_index.isValid())
            window.tree.setExpanded(root_index, True)
            window.tree.setCurrentIndex(root_index)
            self.pump_events(20)
            tree_path = window.tree_model.filePath(window.tree.currentIndex())
            self.assertTrue(window.tree.isExpanded(window.tree_model.index(str(self.root))))
            expanded = True
            horizontal_sizes = list(window.explorer_root.sizes())
            vertical_sizes = list(window.left_splitter.sizes())
            for tab_index in (0, 1, 0, 1):
                window.folder_tabs.setCurrentIndex(tab_index)
                self.pump_events(30)
                self.assertEqual(window.tree_model.filePath(window.tree.currentIndex()), tree_path)
                current_root_index = window.tree_model.index(str(self.root))
                self.assertTrue(current_root_index.isValid())
                self.assertEqual(window.tree.isExpanded(current_root_index), expanded)
                self.assertEqual(window.explorer_root.sizes(), horizontal_sizes)
                self.assertEqual(window.left_splitter.sizes(), vertical_sizes)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_late_thumbnail_result_cannot_touch_deleted_items(self):
        class DeletedItem:
            def setIcon(self, _icon):
                raise RuntimeError("deleted")

        media_folder = self.make_media_folder(1)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            path = str(next(media_folder.glob("*.jpg")))
            window.list_item_by_path[path] = DeletedItem()
            window.detail_item_by_path[path] = DeletedItem()
            window.apply_thumbnail_icon(path, main.QIcon())
            self.assertNotIn(path, window.list_item_by_path)
            self.assertNotIn(path, window.detail_item_by_path)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_rapid_folder_switch_discards_stale_work(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        for index in range(12):
            Image.new("RGB", (1200, 900), (index, 10, 20)).save(first / f"first_{index}.jpg")
            Image.new("RGB", (640, 480), (10, index, 20)).save(second / f"second_{index}.jpg")
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(first)
            window.load_folder(second)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.entries:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(Path(window.current_folder), second)
            self.assertTrue(window.entries)
            self.assertTrue(all(entry.path.parent == second for entry in window.entries))
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_folder_switch_actively_cancels_the_running_old_scan(self):
        first = self.root / "slow_first"
        second = self.root / "fast_second"
        first.mkdir()
        second.mkdir()
        Image.new("RGB", (640, 480), (10, 20, 30)).save(first / "first.jpg")
        Image.new("RGB", (640, 480), (30, 20, 10)).save(second / "second.jpg")
        started = threading.Event()
        cancelled = threading.Event()
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(first)
            window.folder_scan_pool.waitForDone(5000)
            self.pump_events(20)
            original_scan = window.scan_folder_entries

            def controlled_scan(folder, cancel_check=None):
                if Path(folder) == first:
                    started.set()
                    for _ in range(400):
                        if cancel_check is not None and cancel_check():
                            cancelled.set()
                            raise InterruptedError
                        time.sleep(0.002)
                return original_scan(folder, cancel_check=cancel_check)

            window.scan_folder_entries = controlled_scan
            window.load_folder(first, force=True)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not started.is_set():
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(started.is_set())
            switched = time.perf_counter()
            window.load_folder(second, force=True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.app.processEvents()
                if window.entries and all(entry.path.parent == second for entry in window.entries):
                    break
                time.sleep(0.002)
            self.assertTrue(cancelled.is_set())
            self.assertLess(time.perf_counter() - switched, 1.0)
            self.assertTrue(window.entries)
            self.assertTrue(all(entry.path.parent == second for entry in window.entries))
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_cancel_pending_thumbnail_work_cancels_running_tasks(self):
        class FakeTask:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        media_folder = self.make_media_folder(1)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            task = FakeTask()
            window.thumbnail_task_refs.add(task)
            window.pause_thumbnail_work(cancel_pending=True)
            self.assertTrue(task.cancelled)
            window.thumbnail_task_refs.discard(task)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_sort_cancels_competing_thumbnail_tasks_without_dropping_cache(self):
        class FakeTask:
            def __init__(self):
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

        media_folder = self.make_media_folder(3)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.entries:
                self.app.processEvents()
                time.sleep(0.002)
            path = str(next(media_folder.glob("*.jpg")))
            sentinel = window.style().standardIcon(main.QStyle.SP_FileIcon)
            window.thumbnail_cache[path] = sentinel
            task = FakeTask()
            window.thumbnail_task_refs.add(task)
            window.set_sort_from_header("name", False)
            self.assertTrue(task.cancelled)
            self.assertIs(window.thumbnail_cache[path], sentinel)
            self.assertFalse(window.thumbnail_paused)
            window.thumbnail_task_refs.discard(task)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_thumbnail_canvas_uses_scaled_qimage_without_pil_redecode(self):
        image_path = self.root / "large_thumbnail.png"
        Image.new("RGB", (4096, 3072), (20, 50, 80)).save(image_path)
        result = []
        task = main.ImageDecodeTask(1, image_path, (192, 192), canvas_size=(192, 192))
        task.signals.finished.connect(lambda generation, path, payload, metadata: result.append(payload))
        with mock.patch.object(main.Image, "open", side_effect=AssertionError("PIL fallback used")):
            task.run()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], QImage)
        self.assertEqual(result[0].size().width(), 192)
        self.assertEqual(result[0].size().height(), 192)

    def test_viewer_pixmap_cache_is_bounded_by_bytes_not_only_item_count(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        pixmap = QPixmap(512, 512)
        pixmap.fill(Qt.black)
        one_megabyte = 512 * 512 * 4
        with mock.patch.object(main, "VIEWER_CACHE_LIMIT_BYTES", one_megabyte * 2):
            for index in range(5):
                viewer.store_viewer_pixmap(("test", index), QPixmap(pixmap))
            self.assertLessEqual(viewer.viewer_pixmap_cache_bytes, one_megabyte * 2)
            self.assertLessEqual(len(viewer.viewer_pixmap_cache), 2)
        viewer.close()

    def test_folder_reentry_never_leaves_the_hidden_view_empty(self):
        first = self.root / "view_first"
        second = self.root / "view_second"
        first.mkdir()
        second.mkdir()
        for index in range(3):
            Image.new("RGB", (640, 480), (index, 20, 40)).save(first / f"first_{index}.jpg")
            Image.new("RGB", (640, 480), (40, 20, index)).save(second / f"second_{index}.jpg")
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(first)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 3:
                self.app.processEvents()
                time.sleep(0.002)
            window.change_view_mode("large")
            self.assertEqual(window.list.count(), len(window.entries))
            window.change_view_mode("details")
            window.load_folder(second)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.entries:
                self.app.processEvents()
                time.sleep(0.002)
            window.load_folder(first)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and len(window.entries) < 3:
                self.app.processEvents()
                time.sleep(0.002)
            window.change_view_mode("large")
            self.assertEqual(window.list.count(), len(window.entries))
            self.assertGreater(window.list.count(), 0)
            window.close()
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_slow_vlc_initialization_never_blocks_the_ui_thread(self):
        video = self.root / "slow_init.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0.25)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video]
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        with mock.patch.object(main, "vlc", fake_vlc):
            heartbeat.start()
            started = time.perf_counter()
            viewer.show_current()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.08)
            self.assertTrue(viewer.vlc_init_inflight)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and viewer.vlc_instance is None:
                self.app.processEvents()
                time.sleep(0.002)
            heartbeat.stop()
            self.assertIsNotNone(viewer.vlc_instance)
            self.assertGreaterEqual(len(ticks), 5)
            self.assertEqual(state["instances"], 1)
            self.assertEqual(state["plays"], 1)
            self.assertEqual(viewer.video_path, video)
        viewer.deactivate()
        viewer.close()

    def test_video_playback_start_runs_off_the_ui_thread(self):
        video = self.root / "slow_play.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0.01, play_delay=0.2)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video]
        ui_thread = threading.get_ident()
        ticks = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.append(time.perf_counter()))
        with mock.patch.object(main, "vlc", fake_vlc):
            heartbeat.start()
            started = time.perf_counter()
            viewer.show_current()
            self.assertLess(time.perf_counter() - started, 0.08)
            self.wait_for_video_start(viewer, timeout=4)
            heartbeat.stop()
            self.assertEqual(state["plays"], 1)
            self.assertTrue(state["play_threads"])
            self.assertTrue(all(thread_id != ui_thread for thread_id in state["play_threads"]))
            self.assertGreaterEqual(len(ticks), 5)
        viewer.deactivate()
        viewer.close()

    def test_image_view_prewarms_vlc_before_navigating_to_video(self):
        image = self.root / "prewarm.jpg"
        Image.new("RGB", (640, 480), (20, 40, 60)).save(image)
        video = self.root / "prewarm.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0.15)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        with mock.patch.object(main, "vlc", fake_vlc):
            started = time.perf_counter()
            viewer.load([image, video], 0)
            self.assertLess(time.perf_counter() - started, 0.08)
            self.assertFalse(viewer.vlc_init_inflight)
            self.assertTrue(viewer.vlc_prewarm_timer.isActive())
            self.pump_events(500)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(state["instances"], 1)
            self.assertEqual(state["plays"], 0)
            self.assertEqual(len(viewer.video_standby_players), main.VIDEO_INITIAL_PLAYER_TARGET)
            viewer.next_media()
            self.wait_for_video_start(viewer)
            self.assertEqual(state["plays"], 1)
            self.assertEqual(viewer.video_path, video)
        viewer.deactivate()
        viewer.close()

    def test_video_to_video_navigation_uses_a_clean_player_and_surface(self):
        videos = []
        for index in range(2):
            video = self.root / f"nonblocking_stop_{index}.mp4"
            video.write_bytes(b"test")
            videos.append(video)
        fake_vlc, state = self.fake_vlc(delay=0.01, stop_delay=0.25)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = videos
        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            old_player = viewer.media_player
            self.assertIsNotNone(old_player)
            started = time.perf_counter()
            viewer.next_media()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.08)
            self.wait_for_video_start(viewer)
            self.assertEqual(state["plays"], 2)
            self.assertIsNot(viewer.media_player, old_player)
            self.assertGreaterEqual(old_player.pause_calls, 1)
            self.assertEqual(viewer.media_player.media, str(videos[1]))
            self.assertNotEqual(
                int(viewer.media_player.hwnd or 0),
                int(old_player.hwnd or 0),
            )
            self.assertNotIn(str(videos[1]), [value for op, value in old_player.operations if op == "media"])
            self.assertTrue(old_player.hwnd_values and 0 not in old_player.hwnd_values)
        viewer.deactivate()
        viewer.close()

    def test_video_to_image_transition_mutes_pauses_and_hides_before_cleanup(self):
        video = self.root / "retire_audio.mp4"
        video.write_bytes(b"test")
        image = self.root / "after_video.jpg"
        Image.new("RGB", (640, 480), (30, 60, 90)).save(image)
        fake_vlc, state = self.fake_vlc(delay=0.01, stop_delay=0.15)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video, image]
        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.wait_for_video_start(viewer)
            old_player = viewer.media_player
            old_frame = next(iter(viewer.video_slot_states.values()))["frame"]
            viewer.next_media()
            self.assertEqual(viewer.index, 1)
            self.assertTrue(old_frame.isHidden())
            self.assertIn(True, old_player.mute_values)
            self.assertIn(0, old_player.volume_values)
            self.assertIn(("pause", 1), old_player.operations)
            self.assertNotIn(("pause", 0), old_player.operations)
            self.pump_events(main.VIDEO_CLEANUP_IDLE_MS + 30)
            viewer.video_cleanup_queue.join()
            self.assertGreaterEqual(old_player.stop_calls, 1)
        viewer.deactivate()
        viewer.close()

    def test_video_frame_pool_is_bounded(self):
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        allocated = []
        for _ in range(main.VIDEO_MAX_FRAMES_PER_SLOT):
            frame = viewer.video_frame_for_index(0)
            self.assertIsNotNone(frame)
            allocated.append(frame)
            viewer.video_frame_busy.add(id(frame))
        self.assertIsNone(viewer.video_frame_for_index(0))
        self.assertEqual(
            len(viewer.video_frame_pools[0]),
            main.VIDEO_MAX_FRAMES_PER_SLOT,
        )
        for frame in allocated:
            viewer.video_frame_busy.discard(id(frame))
        viewer.close()

    def test_invalid_native_surface_never_starts_a_fallback_vlc_window(self):
        video = self.root / "invalid_surface.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0)
        instance = fake_vlc.Instance()
        player = instance.media_player_new()
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.vlc_instance = instance
        viewer.video_player_instances[id(player)] = instance
        viewer.video_standby_players.append(player)
        with mock.patch.object(viewer, "_native_video_handle", return_value=0), mock.patch.object(
            viewer, "_ensure_video_standby_players"
        ):
            viewer._start_video_playback(video, viewer.video_frame, primary=True)
        viewer.video_cleanup_queue.join()
        self.pump_events(50)
        self.assertEqual(state["plays"], 0)
        self.assertEqual(player.hwnd_values, [])
        self.assertEqual(player.release_calls, 1)
        viewer.close()

    def test_reused_video_surface_stays_covered_until_only_the_current_output_is_ready(self):
        videos = []
        for index in range(2):
            video = self.root / f"covered_transition_{index}.mp4"
            video.write_bytes(b"test")
            videos.append(video)
        fake_vlc, state = self.fake_vlc(delay=0.01)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = videos

        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.wait_for_video_start(viewer)

            self.assertEqual(len(viewer.video_slot_states), 1)
            old_token, old_state = next(iter(viewer.video_slot_states.items()))
            player = old_state["player"]
            label = old_state["frame"].findChild(main.QLabel, "videoStatusLabel")
            self.assertIsNotNone(label)
            self.assertFalse(label.isHidden())
            old_serial = old_state["playback_serial"]

            player.current_time = 0
            viewer._mark_video_output_ready(old_token, old_serial)
            self.pump_events(100)
            self.assertFalse(label.isHidden())
            self.assertFalse(old_state["revealed"])
            player.current_time = 25
            self.pump_events(180)
            self.assertTrue(label.isHidden())
            self.assertTrue(old_state["revealed"])

            viewer.next_media()
            self.wait_for_video_start(viewer)
            self.assertIsNot(viewer.media_player, player)
            self.assertEqual(len(viewer.video_slot_states), 1)
            new_token, new_state = next(iter(viewer.video_slot_states.items()))
            self.assertNotEqual(new_token, old_token)
            new_label = new_state["frame"].findChild(main.QLabel, "videoStatusLabel")
            self.assertIsNotNone(new_label)
            self.assertFalse(new_label.isHidden())
            self.assertFalse(new_state["revealed"])

            new_player = new_state["player"]
            new_player.current_time = 0
            viewer._mark_video_output_ready(old_token, old_serial)
            self.pump_events(100)
            self.assertFalse(new_label.isHidden())
            self.assertFalse(new_state["revealed"])

            viewer._mark_video_output_ready(new_token, new_state["playback_serial"])
            self.pump_events(100)
            self.assertFalse(new_label.isHidden())
            self.assertFalse(new_state["revealed"])
            new_player.current_time = 25
            self.pump_events(180)
            self.assertTrue(new_label.isHidden())
            self.assertTrue(new_state["revealed"])

        viewer.deactivate()
        viewer.close()

    def test_navigation_does_not_wait_for_a_slow_video_start(self):
        video = self.root / "slow_transition.mp4"
        video.write_bytes(b"test")
        image = self.root / "after_slow_transition.jpg"
        Image.new("RGB", (640, 480), (45, 90, 125)).save(image)
        fake_vlc, state = self.fake_vlc(delay=0.01, play_delay=0.6)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video, image]

        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not viewer.video_start_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(viewer.video_start_inflight, 1)

            started = time.perf_counter()
            viewer.next_media()
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.15)
            self.assertEqual(viewer.index, 1)
            self.assertIsNone(viewer.pending_navigation_index)
            self.assertFalse(viewer.current_is_video)

            viewer.deactivate()
            viewer.video_start_queue.join()
            self.pump_events(100)
        viewer.close()

    def test_terminal_vlc_state_retires_black_slot_without_waiting_for_timeout(self):
        video = self.root / "terminal_video.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0.01)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video]

        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            self.wait_for_video_start(viewer)
            player = viewer.media_player
            self.assertIsNotNone(player)
            player.play_state = "error"
            self.pump_events(120)
            self.assertEqual(viewer.video_slot_states, {})
            self.assertIsNone(viewer.media_player)
            self.assertEqual(viewer.video_path, None)

        viewer.deactivate()
        viewer.close()

    def test_single_double_and_triple_video_navigation_rotate_clean_slot_players(self):
        cases = (("single", 1, 8), ("double", 2, 8), ("triple", 3, 9))
        for mode, slots, count in cases:
            with self.subTest(mode=mode):
                videos = []
                for index in range(count):
                    video = self.root / f"stable_{mode}_{index}.mp4"
                    video.write_bytes(b"test")
                    videos.append(video)
                fake_vlc, state = self.fake_vlc(delay=0.01, stop_delay=0.2)
                viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
                viewer.resize(1200, 700)
                viewer.viewer_mode = mode
                viewer.step_mode = "page"
                viewer.show()
                viewer.items = videos
                video_start_geometries = []
                original_start_video_playback = viewer._start_video_playback

                def traced_start_video_playback(path, frame, primary=True):
                    target = viewer.viewer_area()
                    video_start_geometries.append(
                        (frame.width(), frame.height(), target.width(), target.height())
                    )
                    return original_start_video_playback(path, frame, primary)

                viewer._start_video_playback = traced_start_video_playback

                with mock.patch.object(main, "vlc", fake_vlc):
                    viewer.show_current()
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline and viewer.vlc_init_inflight:
                        self.app.processEvents()
                        time.sleep(0.002)
                    self.wait_for_video_start(viewer)
                    initial_players = [viewer.media_player, *viewer.extra_media_players]
                    self.assertEqual(len(initial_players), slots)
                    for player in initial_players:
                        player.current_time = 25
                    self.pump_events(180)

                    while viewer.index + slots < len(videos):
                        expected_index = min(len(videos) - 1, viewer.index + slots)
                        started = time.perf_counter()
                        viewer.next_media()
                        self.assertLess(time.perf_counter() - started, 0.08)
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            for player in [viewer.media_player, *viewer.extra_media_players]:
                                if player is not None:
                                    player.current_time = 25
                            self.app.processEvents()
                            if (
                                viewer.index == expected_index
                                and viewer.pending_navigation_index is None
                                and not viewer._video_lifecycle_busy()
                                and len(
                                    [
                                        player
                                        for player in [viewer.media_player, *viewer.extra_media_players]
                                        if player is not None
                                    ]
                                ) == slots
                            ):
                                break
                            time.sleep(0.002)
                        self.assertEqual(viewer.index, expected_index)

                    active = [
                        player
                        for player in [viewer.media_player, *viewer.extra_media_players]
                        if player is not None
                    ]
                    self.assertEqual(len(active), slots)
                    self.assertTrue(all(int(player.hwnd or 0) != 0 for player in active))
                    self.assertTrue(all(int(player.hwnd or 0) != 0 for player in active))
                    self.assertTrue(video_start_geometries)
                    self.assertTrue(
                        all(width == target_width and height == target_height for (
                            width,
                            height,
                            target_width,
                            target_height,
                        ) in video_start_geometries),
                        video_start_geometries,
                    )

                viewer.deactivate()
                viewer.close()

    def test_mixed_media_transitions_retire_old_vlc_players_on_hidden_surfaces(self):
        cases = (("single", 1), ("double", 2), ("triple", 3))
        for mode, slots in cases:
            with self.subTest(mode=mode):
                videos = []
                for index in range(slots):
                    video = self.root / f"mixed_{mode}_{index}.mp4"
                    video.write_bytes(b"test")
                    videos.append(video)
                image = self.root / f"mixed_{mode}.jpg"
                Image.new("RGB", (640, 480), (40, 70, 110)).save(image)

                fake_vlc, state = self.fake_vlc(delay=0.01, stop_delay=0.05)
                viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
                viewer.resize(1200, 700)
                viewer.viewer_mode = mode
                viewer.step_mode = "page"
                viewer.show()
                viewer.items = [*videos, image]

                with mock.patch.object(main, "vlc", fake_vlc):
                    viewer.show_current()
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline and viewer.vlc_init_inflight:
                        self.app.processEvents()
                        time.sleep(0.002)
                    self.wait_for_video_start(viewer)
                    for player in [viewer.media_player, *viewer.extra_media_players]:
                        if player is not None:
                            player.current_time = 25
                    self.pump_events(120)

                    players = [viewer.media_player, *viewer.extra_media_players]
                    frames = [slot["frame"] for slot in viewer.video_slot_states.values()]
                    frame_ids = [id(frame) for frame in frames]
                    native_handles = [int(player.hwnd or 0) for player in players]
                    self.assertEqual(len(players), slots)
                    self.assertEqual(len(frames), slots)
                    self.assertTrue(all(handle != 0 for handle in native_handles))

                    viewer.next_media()
                    self.assertEqual(viewer.index, slots)
                    self.assertIsNone(viewer.media_player)
                    self.assertEqual(len(viewer.extra_media_players), 0)
                    self.assertGreaterEqual(len(viewer.video_standby_players), 0)
                    self.assertTrue(all(frame.parent() is viewer.central for frame in frames))
                    self.assertTrue(all(frame.isHidden() for frame in frames))

                    viewer.previous_media()
                    self.wait_for_video_start(viewer)
                    active_players = [viewer.media_player, *viewer.extra_media_players]
                    active_frames = [slot["frame"] for slot in viewer.video_slot_states.values()]
                    self.assertTrue(all(player not in players for player in active_players))
                    self.assertTrue(set(id(frame) for frame in active_frames).isdisjoint(frame_ids))
                    self.assertTrue(all(0 not in player.hwnd_values for player in active_players))

                    viewer.deactivate()
                    self.pump_events(main.VIDEO_CLEANUP_IDLE_MS + 100)
                    viewer.video_cleanup_queue.join()
                    self.pump_events(50)
                    for player in players:
                        pause_index = player.operations.index(("pause", 1))
                        stop_index = player.operations.index(("stop", None))
                        release_index = player.operations.index(("release", None))
                        self.assertLess(pause_index, stop_index)
                        self.assertLess(stop_index, release_index)
                        self.assertNotIn(("hwnd", 0), player.operations)

                viewer.close()

    def test_stale_vlc_initialization_never_restarts_video_after_exit(self):
        video = self.root / "stale_init.mp4"
        video.write_bytes(b"test")
        fake_vlc, state = self.fake_vlc(delay=0.2)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [video]
        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            self.assertTrue(viewer.pending_video_requests)
            viewer.deactivate()
            self.assertFalse(viewer.pending_video_requests)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(state["plays"], 0)
            self.assertIsNone(viewer.video_path)
        viewer.close()

    def test_async_vlc_keeps_three_video_slots_and_primary_player_distinct(self):
        videos = []
        for index in range(3):
            video = self.root / f"slot_{index}.mp4"
            video.write_bytes(b"test")
            videos.append(video)
        fake_vlc, state = self.fake_vlc(delay=0.2)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.viewer_mode = "triple"
        viewer.step_mode = "page"
        viewer.show()
        viewer.items = videos
        with mock.patch.object(main, "vlc", fake_vlc):
            viewer.show_current()
            self.assertEqual(len(viewer.pending_video_requests), 3)
            self.assertEqual(
                [request["primary"] for request in viewer.pending_video_requests],
                [True, False, False],
            )
            self.assertEqual(len({id(request["frame"]) for request in viewer.pending_video_requests}), 3)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.wait_for_video_start(viewer)
            self.assertEqual(state["plays"], 3)
            self.assertEqual(len(viewer.extra_media_players), 2)
            self.assertEqual(viewer.video_path, videos[0])
        viewer.deactivate()
        viewer.close()

    def test_video_loop_restarts_all_three_slots_and_toggle_off_stops_repeating(self):
        videos = []
        for index in range(3):
            video = self.root / f"loop_slot_{index}.mp4"
            video.write_bytes(b"test")
            videos.append(video)
        fake_vlc, state = self.fake_vlc(delay=0.01)
        settings = copy.deepcopy(main.DEFAULT_SETTINGS)
        settings["video_loop_enabled"] = True
        settings_path = self.root / "settings.json"

        with mock.patch.object(main, "SETTINGS_PATH", settings_path), mock.patch.object(main, "vlc", fake_vlc):
            viewer = main.ViewerWindow(settings)
            viewer.resize(1200, 700)
            viewer.viewer_mode = "triple"
            viewer.step_mode = "page"
            viewer.show()
            viewer.items = videos
            viewer.show_current()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.wait_for_video_start(viewer)

            self.assertEqual(state["plays"], 3)
            initial_players = [viewer.media_player, *viewer.extra_media_players]
            self.assertEqual(len(viewer.video_slot_states), 3)
            self.assertTrue(viewer.video_loop_btn.isChecked())
            self.assertEqual(viewer.video_loop_btn.text(), "∞")
            self.assertEqual((viewer.video_loop_btn.width(), viewer.video_loop_btn.height()), (34, 28))
            layout = viewer.video_overlay.layout()
            self.assertLess(layout.indexOf(viewer.stop_btn), layout.indexOf(viewer.video_rate_btn))
            self.assertLess(layout.indexOf(viewer.video_rate_btn), layout.indexOf(viewer.video_loop_btn))
            self.assertLess(layout.indexOf(viewer.video_loop_btn), layout.indexOf(viewer.time_label))
            self.assertEqual(viewer.video_rate_btn.text(), "1.0x")
            self.assertEqual(
                [action.text() for action in viewer.video_rate_btn.playback_rate_actions.values()],
                ["0.25x", "0.5x", "0.75x", "1.0x", "2.0x"],
            )

            custom_edit = viewer.video_rate_btn.playback_rate_edit
            custom_edit.setText("1.25x")
            viewer.apply_custom_playback_rate(custom_edit, viewer.video_rate_btn.playback_rate_menu)
            self.assertEqual(viewer.playback_rate, 1.25)
            self.assertEqual(viewer.video_rate_btn.text(), "1.25x")

            self.assertTrue(viewer.set_playback_rate("2x"))
            self.assertEqual(viewer.video_rate_btn.text(), "2.0x")
            self.assertEqual(viewer.animated_rate_btn.text(), "2.0x")
            self.assertTrue(all(player.rate_values[-1:] == [2.0] for player in initial_players))
            self.assertFalse(viewer.set_playback_rate("9x"))
            self.assertEqual(viewer.playback_rate, 2.0)

            for player in list(state["players"]):
                player.current_time = 25
                player.manager.trigger(fake_vlc.EventType.MediaPlayerVout)
            self.pump_events(100)
            self.assertTrue(all(slot["revealed"] for slot in viewer.video_slot_states.values()))

            for player in initial_players:
                player.play_state = fake_vlc.State.Ended
            viewer.update_video_controls()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and state["plays"] < 6:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(state["plays"], 6)
            restarted_players = [viewer.media_player, *viewer.extra_media_players]
            self.assertEqual(len(restarted_players), 3)
            self.assertTrue(all(player not in initial_players for player in restarted_players))
            self.assertTrue(all(player.rate_values[-1:] == [2.0] for player in restarted_players))
            self.assertTrue(all(not slot["revealed"] for slot in viewer.video_slot_states.values()))
            self.assertTrue(
                all(
                    not slot["frame"].findChild(main.QLabel, "videoStatusLabel").isHidden()
                    for slot in viewer.video_slot_states.values()
                )
            )

            for player in list(state["players"]):
                player.current_time = 25
                player.manager.trigger(fake_vlc.EventType.MediaPlayerTimeChanged)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not all(
                slot["revealed"] for slot in viewer.video_slot_states.values()
            ):
                for player in [viewer.media_player, *viewer.extra_media_players]:
                    if player is not None:
                        player.current_time = 25
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(all(slot["revealed"] for slot in viewer.video_slot_states.values()))

            viewer.video_loop_btn.click()
            self.assertFalse(viewer.video_loop_enabled)
            self.assertFalse(viewer.video_loop_btn.isChecked())
            saved = main.json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["video_loop_enabled"])
            plays_before = state["plays"]
            for player in restarted_players:
                player.play_state = fake_vlc.State.Ended
            viewer.update_video_controls()
            self.pump_events(120)
            self.assertEqual(state["plays"], plays_before)

            viewer.deactivate()
            viewer.close()

    def test_stopping_video_detaches_native_surfaces_before_explorer_return(self):
        fake_vlc, state = self.fake_vlc(delay=0)
        instance = fake_vlc.Instance()
        primary = instance.media_player_new()
        extra = instance.media_player_new()
        primary.set_media("primary")
        primary.set_hwnd(101)
        extra.set_media("extra")
        extra.set_hwnd(202)

        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.vlc_instance = instance
        viewer.media_player = primary
        viewer.extra_media_players = [extra]
        viewer.video_path = self.root / "playing.mp4"
        viewer.stop_media()
        viewer.video_cleanup_queue.join()
        self.pump_events(50)

        self.assertGreaterEqual(primary.stop_calls, 1)
        self.assertGreaterEqual(primary.pause_calls, 1)
        self.assertIn(True, primary.mute_values)
        self.assertIn(0, primary.volume_values)
        self.assertEqual(primary.hwnd, 101)
        self.assertEqual(primary.media, "primary")
        self.assertEqual(primary.release_calls, 1)
        self.assertGreaterEqual(extra.stop_calls, 1)
        self.assertGreaterEqual(extra.pause_calls, 1)
        self.assertIn(True, extra.mute_values)
        self.assertIn(0, extra.volume_values)
        self.assertEqual(extra.hwnd, 202)
        self.assertEqual(extra.media, "extra")
        self.assertEqual(extra.release_calls, 1)
        self.assertEqual(viewer.extra_media_players, [])
        self.assertIsNone(viewer.media_player)
        self.assertIsNone(viewer.video_path)

        next_video = self.root / "next.mp4"
        next_player = instance.media_player_new()
        viewer.vlc_instance = instance
        viewer.video_player_instances[id(next_player)] = instance
        viewer.video_standby_players.append(next_player)
        viewer._start_video_playback(next_video, viewer.video_frame, primary=True)
        self.wait_for_video_start(viewer)
        self.assertIsNotNone(viewer.media_player)
        self.assertIs(viewer.media_player, next_player)
        self.assertEqual(viewer.video_path, next_video)
        self.assertEqual(state["plays"], 1)
        viewer.close()

    def test_folder_watcher_storm_is_debounced(self):
        folder = self.root / "watched_media"
        folder.mkdir()
        for index in range(6):
            Image.new("RGB", (320, 240), (index, 80, 140)).save(folder / f"image_{index:03d}.jpg")
        (folder / "folder_a").mkdir()
        settings_dir = self.root / "config"
        settings_dir.mkdir()
        with mock.patch.object(main, "SETTINGS_PATH", settings_dir / "settings.json"):
            window = main.MainWindow(folder)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and (
                len(window.entries) < 7 or window.folder_scan_pool.activeThreadCount() > 0
            ):
                self.app.processEvents()
                time.sleep(0.002)
            scans = 0
            original_scan = window.scan_folder_entries

            def counted_scan(path, cancel_check=None):
                nonlocal scans
                scans += 1
                return original_scan(path, cancel_check=cancel_check)

            window.scan_folder_entries = counted_scan
            for _ in range(20):
                window.on_watched_folder_changed(str(folder))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and scans < 1:
                self.app.processEvents()
                time.sleep(0.002)
            window.folder_scan_pool.waitForDone(5000)
            self.pump_events(450)
            self.assertEqual(scans, 1)
            window.close()
            window.thumbnail_pool.waitForDone(5000)

    def test_zip_open_is_asynchronous_and_folder_like(self):
        folder = self.root / "empty"
        folder.mkdir()
        archive_path = self.root / "images.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for index in range(8):
                data = BytesIO()
                Image.new("RGB", (300, 200), (index, 30, 80)).save(data, format="JPEG")
                archive.writestr(f"nested/image_{index}.jpg", data.getvalue())
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(folder)
            started = time.perf_counter()
            self.assertTrue(window.open_archive(archive_path))
            self.assertLess(time.perf_counter() - started, 0.05)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (
                not str(window.display_path).endswith("::") or len(window.entries) < 1
                or len(window.archive_member_sources) < 8
            ):
                self.app.processEvents()
                time.sleep(0.002)
            self.pump_events(100)
            self.assertTrue(str(window.display_path).endswith("::"))
            self.assertEqual(len(window.entries), 1)
            self.assertTrue(window.entries[0].is_dir)
            self.assertEqual(len(window.archive_member_sources), 8)
            nested = window.entries[0]
            window.open_path(nested.path)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and len(window.entries) < 8:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(len(window.entries), 8)
            self.assertTrue(all(not Path(entry.path).exists() for entry in window.entries))
            window.close()
            window.archive_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_zip_up_returns_to_original_archive_parent_without_exposing_temp(self):
        source_folder = self.root / "server_share" / "images"
        source_folder.mkdir(parents=True)
        archive_path = source_folder / "album.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            data = BytesIO()
            Image.new("RGB", (300, 200), (30, 60, 90)).save(data, format="JPEG")
            archive.writestr("nested/image.jpg", data.getvalue())

        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(source_folder)
            self.assertTrue(window.open_archive(archive_path))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not str(window.display_path).endswith("::"):
                self.app.processEvents()
                time.sleep(0.002)

            extracted_root = Path(window.current_folder)
            self.assertNotEqual(extracted_root, source_folder)
            self.assertTrue(str(window.display_path).endswith("album.zip::"))
            self.assertEqual(window.pending_tree_path, "")

            window.go_up()
            self.assertEqual(Path(window.current_folder), source_folder)
            self.assertEqual(window.display_path, str(source_folder))
            self.assertEqual(window.path_edit.text(), str(source_folder))
            self.assertNotIn(str(extracted_root), window.path_edit.text())

            window.close()
            window.archive_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)

    def test_archive_member_is_decoded_from_memory_without_materializing_a_file(self):
        archive_path = self.root / "memory-only.zip"
        data = BytesIO()
        Image.new("RGB", (640, 480), (40, 80, 120)).save(data, format="JPEG")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("nested/image.jpg", data.getvalue())

        session = main.ArchiveSession(archive_path)
        source = main.ArchiveMemberSource(session, "nested/image.jpg")
        virtual_path = self.root / "never-created.jpg"
        task = main.ImageDecodeTask(1, virtual_path, (160, 160), archive_source=source)
        captured = []
        task.signals.finished.connect(lambda *args: captured.append(args))
        task.run()
        self.pump_events(50)

        self.assertFalse(virtual_path.exists())
        self.assertEqual(len(captured), 1)
        self.assertIsNotNone(captured[0][2])
        self.assertEqual(captured[0][3]["image_size"], (640, 480))
        session.close()

    def test_archive_member_opens_in_viewer_without_extracted_file(self):
        folder = self.root / "archive-viewer"
        folder.mkdir()
        archive_path = folder / "album.zip"
        data = BytesIO()
        Image.new("RGB", (500, 700), (90, 40, 130)).save(data, format="JPEG")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("nested/image.jpg", data.getvalue())

        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(folder)
            self.assertTrue(window.open_archive(archive_path))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and (
                not str(window.display_path).endswith("::") or not window.entries
            ):
                self.app.processEvents()
                time.sleep(0.002)

            self.assertTrue(window.entries[0].is_dir)
            window.open_path(window.entries[0].path)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not window.entries:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(window.entries)
            virtual_path = str(window.entries[0].path)
            self.assertFalse(Path(virtual_path).exists())
            self.assertTrue(window.open_viewer_for(virtual_path))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not window.viewer.viewer_pixmap_cache:
                self.app.processEvents()
                time.sleep(0.002)

            self.assertTrue(window.viewer.viewer_pixmap_cache)
            self.assertEqual(window.viewer.archive_image_sizes[virtual_path], (500, 700))
            self.assertFalse(Path(virtual_path).exists())
            window.close()
            window.archive_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
