import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Listenote'/'app'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['LISTENOTE_DISABLE_UPDATE_CHECK'] = '1'
os.environ['LISTENOTE_DATA'] = str(ROOT/'.test-data'/'motion-tests')
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QListWidget, QPushButton, QComboBox, QMenu
import requests
import motion
import updates
from main import Window, STYLE


def response(status=200, data=None, headers=None, url=None):
    result = Mock(status_code=status, headers=headers or {}, url=url or updates.LATEST_URL)
    result.json.return_value = data or {'tag_name':'v99.0.0'}
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(str(status))
    return result


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'.test-data')
        self.cache = Path(self.temp.name)/'updates.json'
        self.clock = patch('updates.time.time', return_value=10000)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def test_rate_limit_uses_official_redirect_and_persists_cooldown(self):
        limited = response(403, headers={'X-RateLimit-Reset':'13600'})
        web = response(url=updates.REPOSITORY_URL+'/releases/tag/v99.0.0')
        with patch('updates.requests.get', side_effect=[limited, web]) as get:
            result = updates.check_release(self.cache, manual=True)
        self.assertTrue(result['newer'])
        self.assertEqual(result['source'], 'github-web')
        self.assertEqual(get.call_args_list[1].args[0], updates.WEB_LATEST_URL)
        saved = json.loads(self.cache.read_text('utf8'))
        self.assertEqual(saved['api_retry_at'], 13600)
        with patch('updates.time.time', return_value=10100), patch('updates.requests.get', return_value=web) as get:
            updates.check_release(self.cache, manual=True)
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args.args[0], updates.WEB_LATEST_URL)

    def test_recent_checks_and_manual_clicks_do_not_repeat_requests(self):
        with patch('updates.requests.get', return_value=response(headers={'ETag':'tag1'})) as get:
            updates.check_release(self.cache)
            self.assertTrue(updates.check_release(self.cache, manual=True)['cached'])
            self.assertEqual(get.call_count, 1)

    def test_etag_304_reuses_valid_release(self):
        with patch('updates.requests.get', return_value=response(headers={'ETag':'tag1'})):
            updates.check_release(self.cache)
        with patch('updates.time.time', return_value=13700), patch('updates.requests.get', return_value=response(304)) as get:
            self.assertEqual(updates.check_release(self.cache)['tag'], 'v99.0.0')
            self.assertEqual(get.call_args.kwargs['headers']['If-None-Match'], 'tag1')

    def test_offline_cache_is_marked_stale_and_failures_back_off(self):
        with patch('updates.requests.get', return_value=response()):
            updates.check_release(self.cache)
        with patch('updates.time.time', return_value=14000), patch('updates.requests.get', side_effect=requests.ConnectionError()) as get:
            self.assertTrue(updates.check_release(self.cache)['stale'])
            self.assertTrue(updates.check_release(self.cache, manual=True)['stale'])
            self.assertEqual(get.call_count, 2)  # API + official website, only once.

    def test_redirect_cannot_supply_foreign_or_prerelease_link(self):
        for url in ['https://example.com/releases/tag/v9.0.0',
                    updates.REPOSITORY_URL+'/releases/tag/v9.0.0-beta',
                    updates.REPOSITORY_URL+'/releases']:
            with patch('updates.requests.get', return_value=response(url=url)):
                with self.assertRaises(ValueError):
                    updates.web_release()


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLE)
        motion.install_motion()

    def test_maximize_restores_bounds_without_per_frame_geometry_updates(self):
        w = Window(); w.show(); self.app.processEvents()
        normal = w.geometry()
        with patch.object(w, 'setGeometry', wraps=w.setGeometry) as geometry:
            for _ in range(3):
                w.motion.toggle_maximized(); self.app.processEvents()
                self.assertTrue(w.isMaximized())
                w.motion.toggle_maximized(); self.app.processEvents()
                self.assertFalse(w.isMaximized())
            geometry.assert_not_called()
        self.assertEqual(w.geometry(), normal)
        w.close()

    def test_item_hover_does_not_create_a_second_selection_overlay(self):
        view = QListWidget(); view.setObjectName('courseList')
        view.resize(500, 300); view.addItems(['第一节课堂', '第二节课堂']); view.show()
        self.app.processEvents()
        with patch('motion.reduced_motion', return_value=False):
            QTest.mouseMove(view.viewport(), view.visualItemRect(view.item(0)).center())
            QTest.mousePress(view.viewport(), Qt.LeftButton, pos=QPoint(30, 25))
            self.app.processEvents()
            self.assertIsNone(getattr(view.viewport(), '_motion_glow', None))
        view.close()

    def test_rapid_page_changes_release_covers_and_keep_inputs_clickable(self):
        stack = motion.AnimatedStack(); stack.resize(500,300)
        first = QWidget(); second = QPushButton('目标按钮')
        stack.addWidget(first); stack.addWidget(second); stack.show()
        self.app.processEvents()
        with patch('motion.reduced_motion', return_value=False):
            for _ in range(6):
                stack.setCurrentIndex(1); stack.setCurrentIndex(0)
            stack.setCurrentIndex(1)
            clicks = []; second.clicked.connect(lambda:clicks.append(True))
            QTest.mouseClick(second, Qt.LeftButton)
            self.assertEqual(clicks, [True])
            QTest.qWait(300)
            self.assertIsNone(stack._transition_cover)
        stack.close()

    def test_editable_combo_focus_creates_only_one_glow(self):
        combo = QComboBox(); combo.setEditable(True); combo.addItems(['模型一','模型二'])
        with patch('motion.reduced_motion', return_value=False):
            combo.show(); self.app.processEvents()
            for _ in range(5):
                QApplication.sendEvent(combo.lineEdit(), QFocusEvent(QEvent.FocusIn))
                self.app.processEvents()
            glows = combo.lineEdit().findChildren(motion.InteractionGlow)
            self.assertEqual(len(glows), 1)
        combo.close()

    def test_caption_buttons_dispatch_native_system_commands(self):
        w = Window(); w.show(); self.app.processEvents()
        with patch('motion.reduced_motion', return_value=False), patch('window_chrome.native_window_command', return_value=True) as command:
            w.motion.toggle_maximized()
            command.assert_called_with(w, 0xF030)
            w.showMaximized(); self.app.processEvents()
            w.motion.toggle_maximized()
            command.assert_called_with(w, 0xF120)
            w.motion.minimize()
            command.assert_called_with(w, 0xF020)
        w.close()

    def test_combo_popup_and_menu_clip_actual_outer_corners(self):
        from ui_components import AppleComboBox, POPUP_RADIUS
        combo = AppleComboBox(); combo.addItems(['轻量识别 · 国内下载','高精度识别 · 原版模型'])
        combo.resize(240,40); combo.show(); self.app.processEvents()
        combo.showPopup(); self.app.processEvents()
        popup = combo.view().window()
        self.assertTrue(popup.testAttribute(Qt.WA_TranslucentBackground))
        rendered=popup.grab().toImage()
        self.assertEqual(rendered.pixelColor(0,0).alpha(),0)
        self.assertGreater(rendered.pixelColor(rendered.rect().center()).alpha(),0)
        combo.setFocus(); QTest.keyClick(combo, Qt.Key_Down)
        combo.hidePopup(); combo.close()
        menu = QMenu(); menu.addActions([menu.addAction('导出课堂摘录'),menu.addAction('导出全部资料')])
        menu.popup(QPoint(20,20)); self.app.processEvents()
        self.assertFalse(menu.mask().contains(QPoint(0,0)))
        self.assertTrue(menu.mask().contains(menu.rect().center()))
        menu.close()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows work area')
    def test_maximized_bounds_respect_taskbars_on_different_edges(self):
        from ctypes import wintypes
        from window_chrome import constrain_maximized_bounds
        class MinMaxInfo(ctypes.Structure):
            _fields_ = [(name,wintypes.POINT) for name in
                        ('reserved','max_size','max_position','min_track','max_track')]
        for work in [(0,0,1920,1040), (0,40,1920,1080), (50,0,1920,1080), (0,0,1870,1080)]:
            monitor = SimpleNamespace(monitor=wintypes.RECT(0,0,1920,1080), work=wintypes.RECT(*work))
            bounds = MinMaxInfo()
            with patch('window_chrome.monitor_info', return_value=monitor):
                constrain_maximized_bounds(1, ctypes.addressof(bounds))
            self.assertEqual((bounds.max_position.x,bounds.max_position.y), work[:2])
            self.assertEqual((bounds.max_size.x,bounds.max_size.y), (work[2]-work[0],work[3]-work[1]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
