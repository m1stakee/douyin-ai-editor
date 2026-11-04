import tempfile
import unittest
from pathlib import Path

import edge_voice_catalog as catalog

VOICES = [
    {'ShortName': 'en-US-JennyNeural', 'Locale': 'en-US', 'Gender': 'Female'},
    {'ShortName': 'en-GB-RyanNeural', 'Locale': 'en-GB', 'Gender': 'Male'},
    {'ShortName': 'zh-CN-XiaoxiaoNeural', 'Locale': 'zh-CN', 'Gender': 'Female'},
]


class TestVoiceCatalog(unittest.TestCase):
    def test_regional_voice_names_are_accepted_for_synthesis(self):
        from edge_tts_service import validate_voice
        self.assertEqual(validate_voice('zh-CN-liaoning-XiaobeiNeural'), 'zh-CN-liaoning-XiaobeiNeural')

    def test_combines_language_region_gender_and_favorites(self):
        filtered = catalog.filter_voices(VOICES, language='en', region='US', gender='Female')
        self.assertEqual([v['ShortName'] for v in filtered], ['en-US-JennyNeural'])
        self.assertEqual(catalog.filter_voices(VOICES, favorites_only=True, favorites=['en-GB-RyanNeural']), [VOICES[1]])

    def test_downloads_once_and_uses_cache_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / 'voices.json'
            calls = []
            async def fetch():
                calls.append(1)
                return VOICES
            self.assertEqual(catalog.load_voices(cache, fetch=fetch), VOICES)
            self.assertEqual(catalog.load_voices(cache, fetch=fetch), VOICES)
            self.assertEqual(len(calls), 1)
            async def offline():
                raise ConnectionError('offline')
            self.assertEqual(catalog.load_voices(cache, refresh=True, fetch=offline), VOICES)
