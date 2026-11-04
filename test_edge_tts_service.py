import tempfile
import wave
import unittest
from pathlib import Path
from unittest.mock import patch

import edge_tts_service

class TestEdgeTtsService(unittest.TestCase):
    def test_rate_and_voice_validation(self):
        self.assertEqual(edge_tts_service.rate_to_edge(1.2), "+20%")
        with self.assertRaises(ValueError): edge_tts_service.rate_to_edge(3)
        with self.assertRaises(ValueError): edge_tts_service.validate_voice("")

    def test_batch_writes_mp3_and_utf8_srt(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"demo.txt"; source.write_text("第一句。第二句。",encoding="utf-8")
            def fake(text, output, **kwargs):
                with wave.open(str(output), "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(b"\0\0"*24000)
                return Path(output), [(0.0, 1.0, text)]
            with patch.object(edge_tts_service, "synthesize_speech", side_effect=fake):
                result=edge_tts_service.synthesize_script_files([source], Path(folder)/"out", voice="zh-CN-XiaoxiaoNeural", output_format="wav", pause_seconds=0.3, ffmpeg_path=Path(__file__).parent/"vendor"/"ffmpeg"/"ffmpeg.exe")
            self.assertIsNone(result[0]["error"])
            self.assertEqual(result[0]["audio"].suffix, ".wav")
            with wave.open(str(result[0]["audio"]), "rb") as wav:
                self.assertAlmostEqual(wav.getnframes()/wav.getframerate(),2.3,places=3)
            self.assertIn("第一句。", result[0]["srt"].read_text(encoding="utf-8"))

class TestEdgeStreaming(unittest.TestCase):
    def test_subtitles_use_service_timing_and_failure_keeps_old_audio(self):
        class Stream:
            def __init__(self, *args, **kwargs): pass
            async def stream(self):
                yield {"type":"audio", "data":b"ID3audio"}
                yield {"type":"SentenceBoundary", "offset":12000000,"duration":23000000,"text":"Hello."}
        with tempfile.TemporaryDirectory() as folder, patch("edge_tts_service.edge_tts.Communicate",Stream):
            audio,cues=edge_tts_service.synthesize_speech("Hello.",Path(folder)/"test.mp3")
            self.assertEqual(cues,[(1.2,3.5,"Hello.")])
            self.assertEqual(audio.read_bytes(),b"ID3audio")
            class Broken(Stream):
                async def stream(self):
                    yield {"type":"audio","data":b"partial"}
                    raise ConnectionError("offline")
            with patch("edge_tts_service.edge_tts.Communicate",Broken):
                with self.assertRaisesRegex(edge_tts_service.EdgeTTSError,"offline"):
                    edge_tts_service.synthesize_speech("Hello.",audio)
            self.assertEqual(audio.read_bytes(),b"ID3audio")
            self.assertFalse(audio.with_suffix(".mp3.tmp").exists())

if __name__ == "__main__": unittest.main()

