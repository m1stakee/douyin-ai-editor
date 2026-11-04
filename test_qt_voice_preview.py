import os
import unittest
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication

from qt_voice_preview import QtVoiceWindow


class TestQtVoicePreview(unittest.TestCase):
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
            self.assertEqual(window.mm_dropdown.text(), '▼')
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
        window.language_combo.setCurrentText('English')
        self.assertEqual(window.voice_list.count(), 1)
        self.assertEqual(window.voice_list.item(0).data(256), 'en-US-JennyNeural')
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
