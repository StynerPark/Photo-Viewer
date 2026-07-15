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
from PySide6.QtCore import QEvent, QPointF, QTimer, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication

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

    def fake_vlc(self, delay=0.2, stop_delay=0):
        state = {"players": [], "plays": 0, "instances": 0}

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
                self.set_times = []
                self.manager = FakeEventManager()
                state["players"].append(self)

            def video_set_mouse_input(self, _enabled):
                return None

            def video_set_key_input(self, _enabled):
                return None

            def event_manager(self):
                return self.manager

            def set_media(self, media):
                self.media = media

            def set_hwnd(self, hwnd):
                self.hwnd = hwnd

            def play(self):
                state["plays"] += 1
                return 0

            def audio_set_volume(self, value):
                self.volume_values.append(value)
                return None

            def set_pause(self, _paused):
                self.pause_calls += 1
                return None

            def set_time(self, value):
                self.set_times.append(value)
                return None

            def stop(self):
                if stop_delay:
                    time.sleep(stop_delay)
                self.stop_calls += 1
                return None

            def release(self):
                self.release_calls += 1
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
            deadline = time.monotonic() + 2
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
        deadline = time.monotonic() + 4
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
            viewer.deactivate()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.animated_image_task_refs:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertFalse(viewer.animated_image_states)
            self.assertFalse(viewer.animated_image_task_refs)
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_static_webp_uses_animation_worker_once_without_looping(self):
        webp = self.root / "static.webp"
        Image.new("RGB", (800, 1000), (30, 70, 120)).save(webp, format="WEBP", quality=85)
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(960, 640)
        viewer.show()
        viewer.items = [webp]
        viewer.show_current()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            states = list(viewer.animated_image_states.values())
            if states and states[0].get("has_frame") and states[0].get("task") is None:
                break
            time.sleep(0.002)
        states = list(viewer.animated_image_states.values())
        self.assertTrue(states)
        self.assertTrue(states[0].get("has_frame"))
        self.assertEqual(states[0].get("frame_count"), 1)
        self.assertIsNone(states[0].get("task"))
        self.assertFalse(viewer.labels[0][0]._viewer_pixmap.isNull())
        viewer.deactivate()
        viewer.close()
        viewer.animated_image_pool.waitForDone(5000)

    def test_triple_animated_images_use_distinct_bounded_workers(self):
        gifs = [self.make_animated_gif(self.root / f"triple_{index}.gif", frame_count=6, size=(180, 120)) for index in range(3)]
        viewer = main.ViewerWindow(copy.deepcopy(main.DEFAULT_SETTINGS))
        viewer.resize(1200, 700)
        viewer.viewer_mode = "triple"
        viewer.step_mode = "page"
        viewer.show()
        viewer.items = gifs
        viewer.show_current()
        deadline = time.monotonic() + 3
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
            deadline = time.monotonic() + 2
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

            with (
                mock.patch.object(main, "send_to_recycle_bin", side_effect=lambda target: Path(target).unlink()),
                mock.patch.object(
                    main.QMessageBox,
                    "warning",
                    side_effect=AssertionError("Viewer deletion unexpectedly opened an error dialog"),
                ),
            ):
                window.delete_from_viewer(first)

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

    def test_non_webtoon_viewer_never_queues_speculative_preloads(self):
        media_folder = self.make_media_folder(8)
        first = next(media_folder.glob("*.jpg"))
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(media_folder)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not window.media_paths:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertTrue(window.media_paths)
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
            deadline = time.monotonic() + 2
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
            self.assertTrue(viewer.vlc_init_inflight)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and viewer.vlc_init_inflight:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(state["instances"], 1)
            self.assertEqual(state["plays"], 0)
            self.assertEqual(len(viewer.video_standby_players), 1)
            viewer.next_media()
            self.assertEqual(state["plays"], 1)
            self.assertEqual(viewer.video_path, video)
        viewer.deactivate()
        viewer.close()

    def test_video_to_video_navigation_queues_slow_stop_off_ui_thread(self):
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
            self.assertEqual(state["plays"], 2)
            self.assertIsNot(viewer.media_player, old_player)
            self.assertGreaterEqual(old_player.pause_calls, 1)
            self.assertEqual(old_player.hwnd, 0)
            self.assertEqual(old_player.volume_values[-1], 0)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and old_player.release_calls == 0:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(old_player.stop_calls, 1)
            self.assertEqual(old_player.release_calls, 1)
        viewer.deactivate()
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

            self.assertEqual(state["plays"], 3)
            self.assertEqual(len(viewer.video_slot_states), 3)
            self.assertTrue(viewer.video_loop_btn.isChecked())
            self.assertEqual(viewer.video_loop_btn.text(), "∞")
            self.assertEqual((viewer.video_loop_btn.width(), viewer.video_loop_btn.height()), (34, 28))
            layout = viewer.video_overlay.layout()
            self.assertLess(layout.indexOf(viewer.stop_btn), layout.indexOf(viewer.video_loop_btn))
            self.assertLess(layout.indexOf(viewer.video_loop_btn), layout.indexOf(viewer.time_label))

            for player in list(state["players"]):
                player.manager.trigger(fake_vlc.EventType.MediaPlayerEndReached)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and state["plays"] < 6:
                self.app.processEvents()
                time.sleep(0.002)
            self.assertEqual(state["plays"], 6)
            self.assertTrue(all(player.set_times[-1:] == [0] for player in state["players"]))

            viewer.video_loop_btn.click()
            self.assertFalse(viewer.video_loop_enabled)
            self.assertFalse(viewer.video_loop_btn.isChecked())
            saved = main.json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertFalse(saved["video_loop_enabled"])
            plays_before = state["plays"]
            for player in list(state["players"]):
                player.manager.trigger(fake_vlc.EventType.MediaPlayerEndReached)
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

        self.assertEqual(primary.stop_calls, 1)
        self.assertEqual(primary.hwnd, 0)
        self.assertIsNone(primary.media)
        self.assertEqual(primary.release_calls, 1)
        self.assertEqual(extra.stop_calls, 1)
        self.assertEqual(extra.hwnd, 0)
        self.assertIsNone(extra.media)
        self.assertEqual(extra.release_calls, 1)
        self.assertEqual(viewer.extra_media_players, [])
        self.assertIsNone(viewer.media_player)
        self.assertIsNone(viewer.video_path)

        next_video = self.root / "next.mp4"
        viewer._start_video_playback(next_video, viewer.video_frame, primary=True)
        self.assertIsNotNone(viewer.media_player)
        self.assertIs(viewer.media_player, state["players"][-1])
        self.assertEqual(viewer.video_path, next_video)
        self.assertEqual(state["plays"], 1)
        viewer.close()

    def test_folder_watcher_storm_is_debounced(self):
        folder = self.make_media_folder(6)
        with mock.patch.object(main, "SETTINGS_PATH", self.root / "settings.json"):
            window = main.MainWindow(folder)
            self.pump_events(100)
            scans = 0
            original_scan = window.scan_folder_entries

            def counted_scan(path, cancel_check=None):
                nonlocal scans
                scans += 1
                return original_scan(path, cancel_check=cancel_check)

            window.scan_folder_entries = counted_scan
            for _ in range(20):
                window.on_watched_folder_changed(str(folder))
            self.pump_events(450)
            window.folder_scan_pool.waitForDone(5000)
            self.pump_events(20)
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
                not str(window.display_path).endswith("::") or len(window.entries) < 8
            ):
                self.app.processEvents()
                time.sleep(0.002)
            self.pump_events(100)
            self.assertTrue(str(window.display_path).endswith("::"))
            self.assertEqual(len(window.entries), 8)
            window.close()
            window.archive_pool.waitForDone(5000)
            window.folder_scan_pool.waitForDone(5000)
            window.thumbnail_pool.waitForDone(5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
