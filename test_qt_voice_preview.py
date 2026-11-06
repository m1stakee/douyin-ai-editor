import os
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from qt_voice_preview import QtVoiceWindow


class TestQtVoicePreview(unittest.TestCase):
    def test_voicevox_running_engine_is_reused_and_failure_restores_button(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            window = QtVoiceWindow(config_path=Path(folder)/'settings.json', voices=[])
            try:
                with patch.object(window, 'start_job') as job, \
                     patch('voicevox_service.engine_version', return_value='1.0'), \
                     patch('voicevox_service.launch_engine') as launch, \
                     patch('voicevox_service.available_voices', return_value=[]):
                    window.connect_voicevox()
                    self.assertFalse(window.vv_connect.isEnabled())
                    job.call_args.args[0](None)
                    launch.assert_not_called()
                    job.call_args.args[1]([])
                    self.assertTrue(window.vv_connect.isEnabled())
                with patch.object(window, 'start_job') as job, \
                     patch('voicevox_service.engine_version', return_value=None):
                    window.connect_voicevox()
                    with self.assertRaisesRegex(Exception, '请先选择'):
                        job.call_args.args[0](None)
                    job.call_args.args[2]('未选择安装目录')
                    self.assertTrue(window.vv_connect.isEnabled())
                    self.assertTrue(window.vv_choose.isEnabled())
            finally:
                window.close()

    def test_voicevox_directory_is_saved_and_launches_before_loading_voices(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'settings.json'
            window = QtVoiceWindow(config_path=config, voices=[])
            try:
                with patch('qt_voice_preview.QFileDialog.getExistingDirectory', return_value=folder):
                    window.choose_voicevox_directory()
                with patch.object(window, 'start_job') as job, \
                     patch('voicevox_service.engine_version', return_value=None), \
                     patch('voicevox_service.launch_engine') as launch, \
                     patch('voicevox_service.wait_until_ready') as ready, \
                     patch('voicevox_service.available_voices', return_value=['voice']):
                    window.connect_voicevox()
                    self.assertEqual(job.call_args.args[0](None), ['voice'])
                    launch.assert_called_once_with(folder)
                    ready.assert_called_once()
            finally:
                window.close()
            restored = QtVoiceWindow(config_path=config, voices=[])
            try:
                self.assertEqual(restored.vv_path.text(), folder)
            finally:
                restored.close()

    def test_edge_key_persists_and_preview_runs_without_key(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'settings.json'
            window = QtVoiceWindow(config_path=config, voices=[])
            with patch.object(window, 'start_job') as job:
                window.preview_voice({'ShortName':'en-US-JennyNeural', 'Locale':'en-US'})
                job.assert_called_once()
            window.edge_key.setText('ET-unit-test')
            window.save(); window.close()
            restored = QtVoiceWindow(config_path=config, voices=[])
            self.assertEqual(restored.edge_key.text(), 'ET-unit-test')
            restored.close()

    def test_all_combo_boxes_have_visible_dropdown_style(self):
        self.assertIn('QComboBox::drop-down', __import__('qt_voice_preview').STYLE)
        self.assertIn('QComboBox::down-arrow', __import__('qt_voice_preview').STYLE)
        from qt_controls import ComboBox
        combo = ComboBox()
        combo.addItem('A long model or voice name that should be readable in the dropdown')
        combo.resize(150, 36)
        combo.show()
        combo.showPopup()
        self.app.processEvents()
        self.assertGreater(combo.view().minimumWidth(), combo.width())
        self.assertLessEqual(combo.view().minimumWidth(), 720)
        combo.hidePopup()
        combo.close()

    def test_dropdown_reference_applies_to_editable_and_fixed_selectors(self):
        from qt_controls import ComboBox, PlainSelectionDelegate
        from qt_theme import STYLE, DROPDOWN_LIST_STYLE
        from PySide6.QtCore import QPoint
        for editable in (False, True):
            combo = ComboBox()
            combo.setStyleSheet(STYLE)
            combo.setEditable(editable)
            combo.addItems(['English', 'French', 'Japanese'] * 8)
            combo.move(20, 20)
            combo.show()
            combo.showPopup()
            self.app.processEvents()
            self.assertEqual(combo.view().sizeHintForRow(0), 42)
            self.assertLessEqual(abs(combo.view().window().y() - combo.mapToGlobal(QPoint(0, combo.height())).y()), 2)
            if editable:
                self.assertEqual(combo.completer().popup().styleSheet(), DROPDOWN_LIST_STYLE)
                self.assertIsInstance(combo.completer().popup().itemDelegate(), PlainSelectionDelegate)
            combo.hidePopup()
            combo.close()

    def test_edge_search_combines_filters_and_preserves_selected_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            window = QtVoiceWindow(config_path=Path(folder)/'settings.json', voices=[
                {'ShortName':'en-US-JennyNeural','Locale':'en-US','Gender':'Female','FriendlyName':'Jenny'},
                {'ShortName':'en-GB-RyanNeural','Locale':'en-GB','Gender':'Male'},
                {'ShortName':'zh-CN-XiaoxiaoNeural','Locale':'zh-CN','Gender':'Female'},
            ])
            selected = window.selected_voice
            window.voice_search.setText('  JENNY  ')
            self.assertEqual(window.voice_list.count(), 1)
            window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))
            self.assertEqual(window.voice_list.count(), 0)
            self.assertEqual(window.selected_voice, selected)
            window.voice_search.clear()
            self.assertEqual(window.voice_list.count(), 1)
            window.close()

    def test_edge_language_can_be_typed_to_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            window = QtVoiceWindow(config_path=Path(folder)/'settings.json', voices=[
                {'ShortName':'en-US-JennyNeural','Locale':'en-US','Gender':'Female','FriendlyName':'Jenny'},
                {'ShortName':'zh-CN-XiaoxiaoNeural','Locale':'zh-CN','Gender':'Female','FriendlyName':'Xiaoxiao'},
            ])
            window.language_combo.setEditText('英')
            self.assertEqual(window.voice_list.count(), 1)
            self.assertEqual(window.voice_list.item(0).data(256), 'en-US-JennyNeural')
            window.language_combo.setEditText('zh')
            self.assertEqual(window.voice_list.count(), 1)
            self.assertEqual(window.voice_list.item(0).data(256), 'zh-CN-XiaoxiaoNeural')
            window.close()

    def test_minimax_search_matches_name_or_id_and_returns_id(self):
        from PySide6.QtCore import Qt
        with tempfile.TemporaryDirectory() as folder:
            window = QtVoiceWindow(voices=[], config_path=Path(folder)/'config.json')
            window.minimax_voices_ready([
                {'voice_name': '温柔女声', 'voice_id': 'Chinese_Gentle'},
                {'voice_name': '明亮男声', 'voice_id': 'English_Bright'},
            ])
            search = window.mm_voice.completer()
            self.assertEqual(search.filterMode(), Qt.MatchFlag.MatchContains)
            self.assertEqual(search.caseSensitivity(), Qt.CaseSensitivity.CaseInsensitive)
            search.setCompletionPrefix('温柔')
            self.assertEqual(search.completionCount(), 1)
            search.setCompletionPrefix('bright')
            self.assertEqual(search.completionCount(), 1)
            window.mm_voice.setEditText('明亮男声 · English_Bright')
            self.assertEqual(window.minimax_voice_id(), 'English_Bright')
            window.mm_voice.setEditText('my_custom_voice')
            self.assertEqual(window.minimax_voice_id(), 'my_custom_voice')
            window.mm_voice.setCurrentIndex(1)
            restored = QtVoiceWindow(voices=[], config_path=Path(folder)/'config.json')
            restored.minimax_voices_ready([
                {'voice_name': '温柔女声', 'voice_id': 'Chinese_Gentle'},
                {'voice_name': '明亮男声', 'voice_id': 'English_Bright'},
            ])
            self.assertEqual(restored.minimax_voice_id(), 'English_Bright')
            restored.close()
            window.close()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_has_filters_voice_list_and_sliders(self):
        with tempfile.TemporaryDirectory() as folder:
            self.check_filters(Path(folder)/'settings.json')

    def check_filters(self, config):
        window = QtVoiceWindow(config_path=config, voices=[
            {'ShortName': 'en-US-JennyNeural', 'Locale': 'en-US', 'Gender': 'Female', 'FriendlyName': 'Jenny'},
            {'ShortName': 'zh-CN-XiaoxiaoNeural', 'Locale': 'zh-CN', 'Gender': 'Female', 'FriendlyName': 'Xiaoxiao'},
        ])
        self.assertEqual(window.voice_list.count(), 2)
        self.assertIsNotNone(window.language_combo)
        self.assertIsNotNone(window.speed_slider)
        window.language_combo.setCurrentText('英语')
        self.assertEqual(window.voice_list.count(), 1)
        self.assertEqual(window.voice_list.item(0).data(256), 'en-US-JennyNeural')
        window.close()

    def test_edge_language_filter_uses_chinese_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            window = QtVoiceWindow(config_path=Path(folder)/'settings.json', voices=[
                {'ShortName': 'en-US-JennyNeural', 'Locale': 'en-US', 'Gender': 'Female'},
                {'ShortName': 'zh-CN-XiaoxiaoNeural', 'Locale': 'zh-CN', 'Gender': 'Female'},
            ])
            self.assertEqual(window.language_combo.itemText(window.language_combo.findData('en')), '英语')
            self.assertEqual(window.language_combo.itemText(window.language_combo.findData('zh')), '中文')
            window.close()

    def test_favorites_and_pitch_survive_reopening(self):
        voices = [{'ShortName':'en-US-JennyNeural','Locale':'en-US','Gender':'Female'}]
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'settings.json'
            window = QtVoiceWindow(voices=voices, config_path=config)
            window.toggle_favorite('en-US-JennyNeural')
            window.pitch_slider.setValue(12)
            window.selected_voice = 'en-US-JennyNeural'
            window.close()
            restored = QtVoiceWindow(voices=voices, config_path=config)
            self.assertEqual(restored.pitch_slider.value(), 12)
            self.assertEqual(restored.selected_voice, 'en-US-JennyNeural')
            self.assertIn('en-US-JennyNeural', restored.favorites)
            restored.close()

    def test_minimax_settings_persist_and_dispatch(self):
        from unittest.mock import patch
        import minimax_tts_service
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'settings.json'
            window = QtVoiceWindow(voices=[], config_path=config)
            window.engine.setCurrentIndex(2)
            window.mm_key.setText('test-key')
            window.mm_model.setCurrentText('speech-2.8-turbo')
            window.close()
            restored = QtVoiceWindow(voices=[], config_path=config)
            self.assertEqual(restored.engine.currentIndex(), 2)
            self.assertEqual(restored.mm_key.text(), 'test-key')
            source = Path(folder)/'sample.txt'; source.write_text('Hello.', encoding='utf-8')
            restored.add_files([source])
            with patch.object(restored, 'start_job') as job, patch.object(minimax_tts_service, 'synthesize_script_files', return_value=[]) as synth:
                restored.generate()
                job.call_args.args[0](lambda _: None)
                self.assertEqual(synth.call_args.kwargs['api_key'], 'test-key')
                self.assertEqual(synth.call_args.kwargs['model'], 'speech-2.8-turbo')
            restored.finish_generation(); restored.close()


if __name__ == '__main__':
    unittest.main()
