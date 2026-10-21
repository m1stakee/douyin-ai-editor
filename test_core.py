import unittest
import json
import os
from unittest.mock import Mock, patch
from pathlib import Path
from downloader import extract_share_url
from downloader_service import DownloadControl, DownloadSpec, api_worker_count, download_resolved, download_videos, extract_media_choice, download_video, run_with_fresh_thread_retries, safe_filename, smart_segment_count, worker_count
from rename_service import rename_media_bundle
from downloader import extract_share_urls
from batch_service import run_batch, transcribe_worker_count
from app_config import save_settings, load_settings
from asr import prepared_asr_audio, transcribe, transcribe_request_config, segments_to_srt, segments_to_text
from media import fixed_scenes
from ai import rewrite_text, validate_plan
from task_store import TaskStore
from license_client import verify_license, verify_saved_license
class TestCore(unittest.TestCase):
    @patch("license_client.requests.post")
    def test_license_verification_posts_to_server(self, post):
        post.return_value.json.return_value={"valid":True,"message":"授权验证成功"}
        valid,message=verify_license("https://license.example.com/","VF-TEST-KEY")
        self.assertTrue(valid); self.assertEqual(message,"授权验证成功")
        self.assertEqual(post.call_args.args[0],"https://license.example.com/api/license/verify")
        self.assertEqual(post.call_args.kwargs["json"]["license_key"],"VF-TEST-KEY")

    def test_saved_license_skips_prompt_when_valid(self):
        verifier = Mock(return_value=(True, "授权验证成功"))
        self.assertEqual(verify_saved_license("VF-SAVED", verifier), "VF-SAVED")

    def test_invalid_saved_license_requires_prompt(self):
        verifier = Mock(return_value=(False, "卡密已过期"))
        self.assertIsNone(verify_saved_license("VF-OLD", verifier))
    def test_task_store_persists_items_and_marks_running_tasks_interrupted(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/"task_history.local.json"
            store=TaskStore(path); task=store.create("download","下载批次 1","D:/out",[{"url":"https://v.douyin.com/a/"}])
            store.update_task(task["id"],status="运行中"); store.update_item(task["id"],0,status="下载中",progress=42,error="")
            restored=TaskStore(path).get(task["id"])
            self.assertEqual(restored["status"],"已中断")
            self.assertEqual(restored["items"][0]["status"],"已中断")
            self.assertEqual(restored["items"][0]["progress"],42)

    def test_task_store_does_not_include_credentials(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/"task_history.local.json"
            store=TaskStore(path); store.create("transcribe","文案与 SRT","D:/out",[{"path":"D:/out/a.mp4"}])
            self.assertNotIn("api_key",path.read_text(encoding="utf-8"))

    @patch("ai.requests.post")
    def test_bailian_rewrite_sends_only_prompt_and_transcript_text(self, post):
        post.return_value.json.return_value={"choices":[{"message":{"content":"改写结果"}}]}
        result=rewrite_text("转录正文","改写提示", "secret-key", "qwen-plus")
        self.assertEqual(result,"改写结果")
        self.assertEqual(post.call_args.args[0],"https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
        messages=post.call_args.kwargs["json"]["messages"]
        self.assertEqual(messages,[{"role":"system","content":"改写提示"},{"role":"user","content":"转录正文"}])
        self.assertEqual(post.call_args.kwargs["json"]["model"],"qwen-plus")

    def test_extract(self): self.assertEqual(extract_share_url("复制 https://v.douyin.com/abc/ 打开"),"https://v.douyin.com/abc/")
    def test_extract_multiple_share_urls(self):
        text = "第一条 https://v.douyin.com/abc/\n第二条 https://v.douyin.com/xyz/"
        self.assertEqual(extract_share_urls(text), ["https://v.douyin.com/abc/", "https://v.douyin.com/xyz/"])

    def test_batch_keeps_each_result_and_error(self):
        results = run_batch([1, 2, 3], lambda n: 10 // (n - 2), workers=2)
        self.assertEqual(results[0][1], -10)
        self.assertIsInstance(results[1][2], Exception)
        self.assertEqual(results[2][1], 10)

    def test_batch_retries_failures_in_fresh_executor_rounds(self):
        calls = {}
        def operation(value):
            calls[value] = calls.get(value, 0) + 1
            if calls[value] < 3:
                raise RuntimeError("temporary")
            return value * 2
        results = run_batch([4], operation, workers=1, retries=3)
        self.assertEqual(results[0][1], 8)
        self.assertEqual(calls[4], 3)

    @patch("downloader_service.download_resolved")
    @patch("downloader_service.resolve_video")
    def test_download_videos_isolates_api_and_download_errors(self, resolve, download):
        def resolve_one(url, *args):
            if url.endswith("/b/"):
                raise RuntimeError("API failed")
            name = url.rstrip("/").rsplit("/", 1)[-1]
            return DownloadSpec(url, name, f"https://media/{name}.mp4")
        def download_one(spec, *args):
            if spec.title == "c":
                raise RuntimeError("download failed")
            return f"D:/out/{spec.title}.mp4"
        resolve.side_effect = resolve_one
        download.side_effect = download_one
        results = download_videos(
            "https://v.douyin.com/a/ https://v.douyin.com/b/ https://v.douyin.com/c/",
            "D:/out", api_key="key", download_workers=2,
        )
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(error is None for _, _, error in results), 1)
        self.assertEqual(sum(error is not None for _, _, error in results), 2)

    @patch("downloader_service.download_resolved")
    @patch("downloader_service.resolve_video")
    def test_five_independent_urls_are_each_resolved_and_downloaded(self, resolve, download):
        resolve.side_effect = lambda url, *args: DownloadSpec(url, url[-2], f"https://media/{url[-2]}.mp4")
        download.side_effect = lambda spec, *args: f"D:/out/{spec.title}.mp4"
        urls = [f"https://v.douyin.com/{number}/" for number in range(1, 6)]
        results = download_videos("\n".join(urls), "D:/out", api_key="key", download_workers=5)
        self.assertEqual(resolve.call_count, 5)
        self.assertEqual(download.call_count, 5)
        self.assertEqual([url for url, _, _ in results], urls)
        self.assertTrue(all(error is None for _, _, error in results))

    def test_worker_count_follows_url_count_and_safety_limit(self):
        self.assertEqual(worker_count(5, 8), 5)
        self.assertEqual(worker_count(30, 8), 8)
        self.assertEqual(worker_count(30, 100), 16)

    def test_api_worker_count_queues_large_batches(self):
        self.assertEqual(api_worker_count(2), 2)
        self.assertEqual(api_worker_count(10), 5)

    def test_transcribe_worker_count_queues_large_batches(self):
        self.assertEqual(transcribe_worker_count(2), 2)
        self.assertEqual(transcribe_worker_count(10), 5)

    @patch("downloader_service.download_resolved", return_value="D:/out/video.mp4")
    @patch("downloader_service.resolve_video")
    def test_api_pool_limits_parallel_requests(self, resolve, _download):
        from concurrent.futures import Future
        created=[]
        class ImmediatePool:
            def __init__(self,max_workers,**_kwargs): created.append(max_workers)
            def __enter__(self): return self
            def __exit__(self,*_args): return False
            def submit(self,operation,*args):
                future=Future()
                try: future.set_result(operation(*args))
                except Exception as exc: future.set_exception(exc)
                return future
        resolve.side_effect=lambda url,*_args: DownloadSpec(url,"video","https://media/video.mp4")
        urls=[f"https://v.douyin.com/{index}/" for index in range(20)]
        with patch("downloader_service.ThreadPoolExecutor",ImmediatePool):
            download_videos("\n".join(urls),"D:/out",api_key="key",download_workers=2)
        self.assertEqual(created[0],5)

    def test_confirmed_failure_destroys_attempt_thread_and_retries_three_times(self):
        calls=[]
        def operation():
            calls.append(1)
            raise RuntimeError("failed")
        with self.assertRaisesRegex(RuntimeError,"failed"):
            run_with_fresh_thread_retries(operation,retries=3)
        self.assertEqual(len(calls),4)

    def test_smart_segments_balance_file_size_and_batch_concurrency(self):
        mb=1024*1024
        self.assertEqual(smart_segment_count(4*mb,1),1)
        self.assertEqual(smart_segment_count(40*mb,5),4)
        self.assertEqual(smart_segment_count(40*mb,12),2)
        self.assertEqual(smart_segment_count(40*mb,30),1)
        self.assertEqual(smart_segment_count(200*mb,2),6)

    def test_download_control_can_pause_and_resume(self):
        import threading
        control=DownloadControl(); control.pause(); passed=threading.Event()
        worker=threading.Thread(target=lambda: (control.checkpoint(),passed.set()),daemon=True); worker.start()
        self.assertFalse(passed.wait(0.05)); control.resume(); self.assertTrue(passed.wait(1))

    @patch("downloader_service._session")
    def test_save_media_resumes_partial_file_with_range(self, make_session):
        from tempfile import TemporaryDirectory
        class Response:
            status_code = 206
            headers = {"Content-Range": "bytes 3-5/6"}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def raise_for_status(self): pass
            def iter_content(self, size): return [b"def"]
        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, *args, **kwargs):
                self.headers = kwargs["headers"]
                return Response()
        session = Session(); make_session.return_value = session
        with TemporaryDirectory() as folder:
            target = Path(folder) / "video.mp4"
            target.with_name(".video.mp4.part").write_bytes(b"abc")
            from downloader_service import _save_media
            _save_media("https://media/video.mp4", target)
            self.assertEqual(target.read_bytes(), b"abcdef")
            self.assertEqual(session.headers["Range"], "bytes=3-")

    @patch("downloader_service._save_media_segmented")
    @patch("downloader_service._range_size", return_value=32 * 1024 * 1024)
    def test_new_range_capable_download_uses_parallel_segments(self, range_size, segmented):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            target=Path(folder)/"video.mp4"
            from downloader_service import _save_media
            _save_media("https://media/video.mp4",target,headers={"Referer":"https://x/"})
            segmented.assert_called_once()
            self.assertEqual(segmented.call_args.args[2],32 * 1024 * 1024)

    @patch("downloader_service._save_media")
    def test_parallel_same_titles_get_unique_targets(self, save_media):
        from tempfile import TemporaryDirectory
        def create_file(url, target, headers, *args, **kwargs):
            target.write_bytes(b"video")
        save_media.side_effect = create_file
        spec = DownloadSpec("https://v.douyin.com/a/", "same", "https://media/video.mp4")
        with TemporaryDirectory() as folder:
            results = run_batch(range(2), lambda _: download_resolved(spec, folder), workers=2)
            paths = [Path(result).name for _, result, error in results if error is None]
            self.assertEqual(set(paths), {"same.mp4", "same (2).mp4"})

    def test_settings_round_trip_keeps_all_ui_values(self):
        from tempfile import TemporaryDirectory
        values = {
            "output_directory": "D:/video-output", "download_quality": "1080P",
            "download_workers": "6",
            "ffmpeg": "D:/tools/ffmpeg.exe", "source_lang": "日语",
            "henghengmao_api_key": "download-key", "dashscope_api_key": "bailian-key",
            "llm_url": "https://example.com/v1", "llm_key": "llm-key",
            "llm_model": "qwen-plus", "target_lang": "韩语",
            "writing_style": "故事叙述", "writing_length": "缩短文案"
        }
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.local.json"
            save_settings(values, path)
            self.assertEqual(load_settings(path), values)

    def test_settings_round_trip_keeps_rewrite_prompt_library(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path=Path(folder)/"settings.local.json"
            prompts=[{"name":"口播","text":"保留事实并改写"}]
            save_settings({"rewrite_prompts":prompts},path)
            self.assertEqual(load_settings(path)["rewrite_prompts"],prompts)

    def test_default_settings_path_uses_stable_local_app_data(self):
        from tempfile import TemporaryDirectory
        import app_config
        with TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"LOCALAPPDATA": folder}):
                expected = Path(folder) / "VideoFlow" / "settings.local.json"
                self.assertEqual(app_config.settings_path(), expected)

    def test_legacy_exe_settings_are_migrated_to_local_app_data(self):
        from tempfile import TemporaryDirectory
        import app_config
        with TemporaryDirectory() as local_folder, TemporaryDirectory() as legacy_folder:
            legacy_path = Path(legacy_folder) / "settings.local.json"
            legacy_path.write_text(json.dumps({"license_key": "VF-SAVED"}), encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": local_folder}), patch.object(app_config, "_root", return_value=Path(legacy_folder)):
                self.assertEqual(app_config.load_settings()["license_key"], "VF-SAVED")
                saved_path = app_config.save_settings(app_config.load_settings())
                self.assertEqual(saved_path, Path(local_folder) / "VideoFlow" / "settings.local.json")
                self.assertEqual(json.loads(saved_path.read_text(encoding="utf-8"))["license_key"], "VF-SAVED")

    def test_main_settings_hide_deferred_options(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        build_source = source.split("    def build(self):", 1)[1].split(
            "    def _scroll_main_window", 1
        )[0]
        for label in (
            "下载并发上限",
            "目标语言",
            "文案风格",
            "文案长度",
            "FFmpeg",
            "LLM URL",
            "LLM Key",
            "LLM Model",
        ):
            self.assertNotIn(label, build_source)
        self.assertIn("self.ffmpeg=tk.StringVar(value=asr.resolve_ffmpeg())", source)
        self.assertNotIn('asr.resolve_ffmpeg(saved.get("ffmpeg")', source)

    def test_load_settings_returns_empty_for_invalid_json(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.local.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(load_settings(path), {})
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

    def test_aliyun_asr_config_is_fixed(self):
        config = transcribe_request_config("中文")
        self.assertEqual(config["endpoint"], "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription")
        self.assertEqual(config["model"], "paraformer-v2")
        self.assertEqual(config["language"], "zh")

    def test_segments_export_to_srt(self):
        srt = segments_to_srt([{"start": 1.2, "end": 3.45, "text": "你好，世界"}])
        self.assertIn("1\n00:00:01,200 --> 00:00:03,450\n你好，世界", srt)

    def test_segments_export_to_plain_text(self):
        text = segments_to_text([{"text": "第一句"}, {"text": " 第二句 "}])
        self.assertEqual(text, "第一句\n第二句\n")

    @patch("asr.subprocess.run")
    def test_prepared_asr_audio_uses_compact_mp3_and_removes_temporary_file(self, run):
        from tempfile import TemporaryDirectory
        observed = {}
        def convert(command, **_kwargs):
            observed["command"] = command
            Path(command[-1]).write_bytes(b"mp3")
            return Mock(returncode=0, stderr="")
        run.side_effect = convert
        with TemporaryDirectory() as folder:
            source = Path(folder) / "video.mp4"
            ffmpeg = Path(folder) / "ffmpeg.exe"
            source.write_bytes(b"video")
            ffmpeg.write_bytes(b"exe")
            with prepared_asr_audio(str(source), str(ffmpeg)) as audio_path:
                temporary_audio = Path(audio_path)
                self.assertTrue(temporary_audio.exists())
                self.assertEqual(temporary_audio.suffix, ".mp3")
            self.assertFalse(temporary_audio.exists())
        command = observed["command"]
        self.assertEqual(command[0], str(ffmpeg))
        self.assertEqual(command[command.index("-ac") + 1], "1")
        self.assertEqual(command[command.index("-ar") + 1], "16000")
        self.assertEqual(command[command.index("-b:a") + 1], "48k")
        if __import__("sys").platform == "win32":
            self.assertEqual(run.call_args.kwargs["creationflags"], __import__("subprocess").CREATE_NO_WINDOW)

    @patch("asr.subprocess.run", return_value=Mock(returncode=1, stderr="bad input"))
    def test_prepared_asr_audio_reports_ffmpeg_failure(self, _run):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            source = Path(folder) / "video.mp4"
            ffmpeg = Path(folder) / "ffmpeg.exe"
            source.write_bytes(b"video")
            ffmpeg.write_bytes(b"exe")
            with self.assertRaisesRegex(RuntimeError, "bad input"):
                with prepared_asr_audio(str(source), str(ffmpeg)):
                    pass

    @patch("asr.time.sleep")
    @patch("asr.requests.post")
    @patch("asr.requests.get")
    def test_transcribe_uploads_prepared_mp3_to_aliyun(self, get, post, _sleep):
        from tempfile import TemporaryDirectory
        policy = Mock(status_code=200)
        policy.json.return_value = {"data": {"upload_dir": "temporary/path", "upload_host": "https://oss.example", "oss_access_key_id": "id", "signature": "sig", "policy": "policy", "x_oss_object_acl": "private", "x_oss_forbid_overwrite": "true", "max_file_size_mb": "100"}}
        transcript = Mock(status_code=200)
        transcript.json.return_value = {"transcripts": [{"sentences": [{"begin_time": 0, "end_time": 1000, "text": "你好"}]}]}
        completed = Mock(status_code=200); completed.json.return_value = {"output": {"task_status": "SUCCEEDED", "results": [{"subtask_status": "SUCCEEDED", "transcription_url": "https://result.example"}]}}
        get.side_effect = [policy, completed, transcript]
        uploaded = Mock(status_code=200)
        submitted = Mock(status_code=200); submitted.json.return_value = {"output": {"task_id": "task-1"}}
        post.side_effect = [uploaded, submitted]
        with TemporaryDirectory() as folder:
            audio = Path(folder) / "中文 标题 #测试.mp3"
            audio.write_bytes(b"audio")
            result = transcribe(str(audio), key="test-key")
        self.assertEqual(result[0]["text"], "你好")
        uploaded_file = post.call_args_list[0].kwargs["files"]["file"]
        self.assertEqual(uploaded_file[0], "中文 标题 #测试.mp3")
        self.assertEqual(uploaded_file[2], "audio/mpeg")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["model"], "paraformer-v2")
        self.assertIn("task-1", get.call_args_list[1].args[0])

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
