import unittest
import json
from unittest.mock import Mock, patch
from pathlib import Path
from downloader import extract_share_url
from downloader_service import extract_media_choice, download_video, safe_filename
from rename_service import rename_media_bundle
from downloader import extract_share_urls
from batch_service import run_batch
from app_config import save_credentials
from asr import transcribe_request_config, segments_to_srt, segments_to_text
from media import fixed_scenes
from ai import validate_plan
class TestCore(unittest.TestCase):
    def test_extract(self): self.assertEqual(extract_share_url("复制 https://v.douyin.com/abc/ 打开"),"https://v.douyin.com/abc/")
    def test_extract_multiple_share_urls(self):
        text = "第一条 https://v.douyin.com/abc/\n第二条 https://v.douyin.com/xyz/"
        self.assertEqual(extract_share_urls(text), ["https://v.douyin.com/abc/", "https://v.douyin.com/xyz/"])

    def test_batch_keeps_each_result_and_error(self):
        results = run_batch([1, 2, 3], lambda n: 10 // (n - 2), workers=2)
        self.assertEqual(results[0][1], -10)
        self.assertIsInstance(results[1][2], Exception)
        self.assertEqual(results[2][1], 10)

    def test_save_credentials_writes_expected_fields(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path = Path(folder) / "credentials.local.json"
            save_credentials("download-key", "groq-key", path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data, {"henghengmao_api_key": "download-key", "groq_api_key": "groq-key"})
    def test_scenes(self): self.assertEqual(fixed_scenes(11,5)[-1]["end"],11)
    def test_invalid_speed(self):
        with self.assertRaises(ValueError): validate_plan({"timeline":[{"scene_id":1,"rewrite_segment_id":1,"speed":2}]},[{"id":1,"start":0,"end":2}],{"segments":[{"id":1}]},2)

    def test_henghengmao_selects_default_variant(self):
        payload = {"medias": [{"media_type": "video", "variants": [
            {"quality": 720, "video_url": "https://x/720.mp4"},
            {"quality": 1080, "video_url": "https://x/1080.mp4", "is_default": True}
        ]}]}
        choice = extract_media_choice(payload, "推荐")
        self.assertEqual(choice["url"], "https://x/1080.mp4")

    def test_henghengmao_uses_fixed_service(self):
        self.assertEqual(extract_media_choice({"medias": [{"media_type": "video", "resource_url": "https://x/video.mp4"}]})["url"], "https://x/video.mp4")

    def test_henghengmao_keeps_separate_audio_url(self):
        payload = {"medias": [{"media_type": "video", "variants": [{
            "video_url": "https://x/video.mp4", "audio_url": "https://x/audio.m4a", "is_default": True
        }]}]}
        choice = extract_media_choice(payload)
        self.assertEqual(choice["audio_url"], "https://x/audio.m4a")

    def test_groq_asr_config_is_fixed(self):
        config = transcribe_request_config("中文")
        self.assertEqual(config["endpoint"], "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertEqual(config["data"]["model"], "whisper-large-v3-turbo")
        self.assertEqual(config["data"]["response_format"], "verbose_json")
        self.assertEqual(config["data"]["language"], "zh")

    def test_segments_export_to_srt(self):
        srt = segments_to_srt([{"start": 1.2, "end": 3.45, "text": "你好，世界"}])
        self.assertIn("1\n00:00:01,200 --> 00:00:03,450\n你好，世界", srt)

    def test_segments_export_to_plain_text(self):
        text = segments_to_text([{"text": "第一句"}, {"text": " 第二句 "}])
        self.assertEqual(text, "第一句\n第二句\n")

    def test_safe_filename_removes_windows_characters(self):
        self.assertEqual(safe_filename('标题:/测试*'), "标题__测试_")

    def test_rename_media_bundle_renames_video_text_and_srt(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for suffix in (".mp4", ".txt", ".srt", ".json"):
                (root / f"old{suffix}").write_text("x", encoding="utf-8")
            renamed = rename_media_bundle(root / "old.mp4", "new title")
            self.assertEqual(renamed.name, "new title.mp4")
            self.assertTrue((root / "new title.txt").exists())
            self.assertTrue((root / "new title.srt").exists())
            self.assertTrue((root / "new title.json").exists())
if __name__=='__main__': unittest.main()
