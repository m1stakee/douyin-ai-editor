import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from azure_tts_service import (
    AzureTTSError,
    available_voices,
    build_ssml,
    rate_to_ssml,
    resolve_voice,
    synthesize_speech,
)


class _FakeSpeechSdk:
    class ResultReason:
        SynthesizingAudioCompleted = "completed"

    class SpeechSynthesisOutputFormat:
        Audio24Khz48KBitRateMonoMp3 = "mp3"

    class SpeechConfig:
        def __init__(self, subscription, region):
            self.subscription = subscription
            self.region = region
            self.speech_synthesis_voice_name = ""
            self.output_format = None

        def set_speech_synthesis_output_format(self, value):
            self.output_format = value

    class audio:
        class AudioOutputConfig:
            def __init__(self, filename):
                self.filename = filename

    class _Future:
        def __init__(self, result):
            self.result = result

        def get(self):
            return self.result

    class _Result:
        reason = "completed"
        cancellation_details = None

    class SpeechSynthesizer:
        def __init__(self, speech_config, audio_config):
            self.speech_config = speech_config
            self.audio_config = audio_config

        def speak_ssml_async(self, ssml):
            Path(self.audio_config.filename).write_bytes(b"fake-mp3")
            return _FakeSpeechSdk._Future(_FakeSpeechSdk._Result())

        def close(self):
            return None


class TestAzureTtsService(unittest.TestCase):
    def test_voice_label_and_custom_voice_are_supported(self):
        self.assertEqual(resolve_voice("晓晓（女）"), "zh-CN-XiaoxiaoNeural")
        self.assertEqual(resolve_voice("en-US-AvaNeural"), "en-US-AvaNeural")
        self.assertTrue(any(item["name"] == "ja-JP-NanamiNeural" for item in available_voices()))

    def test_ssml_escapes_text_and_converts_rate(self):
        ssml = build_ssml("A&B <测试>", "zh-CN-XiaoxiaoNeural", 1.3)
        self.assertIn('rate="+30%"', ssml)
        self.assertIn("A&amp;B &lt;测试&gt;", ssml)
        self.assertEqual(rate_to_ssml(1.0), "0%")

    def test_missing_key_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(AzureTTSError, "AZURE_SPEECH_KEY"):
                synthesize_speech("测试", "output.mp3", _speechsdk=_FakeSpeechSdk)

    def test_synthesis_uses_environment_and_atomically_writes_mp3(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(
            os.environ,
            {"AZURE_SPEECH_KEY": "test-key", "AZURE_SPEECH_REGION": "test-region"},
            clear=True,
        ):
            output = synthesize_speech(
                "测试语音",
                Path(folder) / "voice",
                voice="晓晓（女）",
                rate=1.2,
                _speechsdk=_FakeSpeechSdk,
            )
            self.assertEqual(output.name, "voice.mp3")
            self.assertEqual(output.read_bytes(), b"fake-mp3")
            self.assertFalse(Path(str(output) + ".tmp").exists())

    def test_caller_can_supply_key_region_voice_and_rate(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            output = synthesize_speech(
                "调用方参数测试",
                Path(folder) / "caller.mp3",
                speech_key="caller-key",
                speech_region="canadacentral",
                voice="ja-JP-NanamiNeural",
                rate=0.9,
                _speechsdk=_FakeSpeechSdk,
            )
            self.assertEqual(output.read_bytes(), b"fake-mp3")


if __name__ == "__main__":
    unittest.main()
