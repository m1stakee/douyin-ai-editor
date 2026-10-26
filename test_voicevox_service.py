import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import voicevox_service


class Response:
    def __init__(self, payload=None, content=b""):
        self.payload = payload
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class TestVoicevoxService(unittest.TestCase):
    def test_engine_url_only_accepts_loopback_http(self):
        self.assertEqual(
            voicevox_service.normalize_engine_url("http://localhost:50021/"),
            "http://localhost:50021",
        )
        with self.assertRaises(ValueError):
            voicevox_service.normalize_engine_url("https://example.com:50021")
        with self.assertRaises(ValueError):
            voicevox_service.normalize_engine_url("http://192.168.1.10:50021")

    def test_find_installation_prefers_engine_run_executable(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            engine = root / "vv-engine" / "run.exe"
            engine.parent.mkdir()
            engine.write_bytes(b"exe")
            (root / "VOICEVOX.exe").write_bytes(b"editor")
            self.assertEqual(voicevox_service.find_installation(root), engine.resolve())

    def test_installation_selection_rejects_unrelated_executables(self):
        with TemporaryDirectory() as folder:
            unrelated = Path(folder) / "other.exe"
            unrelated.write_bytes(b"exe")
            self.assertIsNone(voicevox_service.find_installation(unrelated))

    def test_available_voices_flattens_speaker_styles(self):
        payload = [{
            "name": "青山龍星",
            "speaker_uuid": "uuid",
            "styles": [{"name": "ノーマル", "id": 13}, {"name": "熱血", "id": 81}],
        }]
        response = Response(payload)
        with patch("voicevox_service.requests.get", return_value=response):
            voices = voicevox_service.available_voices()
        self.assertEqual([voice.style_id for voice in voices], [13, 81])
        self.assertEqual(voices[0].label, "青山龍星 / ノーマル")

    def test_synthesis_sends_adjustments_and_atomically_writes_wav(self):
        query_response = Response({"speedScale": 1.0})
        audio_response = Response(content=b"RIFF" + b"0" * 64)
        with TemporaryDirectory() as folder, patch(
            "voicevox_service.requests.post", side_effect=[query_response, audio_response]
        ) as post:
            output = voicevox_service.synthesize_speech(
                "こんにちは",
                Path(folder) / "a",
                style_id=13,
                speed=1.2,
                pitch=0.05,
                volume=0.9,
            )
            self.assertEqual(output.name, "a.wav")
            self.assertTrue(output.exists())
            self.assertFalse(Path(str(output) + ".tmp").exists())
        query = post.call_args_list[1].kwargs["json"]
        self.assertEqual(query["speedScale"], 1.2)
        self.assertEqual(query["pitchScale"], 0.05)
        self.assertEqual(query["volumeScale"], 0.9)
        self.assertEqual(post.call_args_list[1].kwargs["params"]["speaker"], 13)

    @patch("voicevox_service.subprocess.Popen")
    def test_engine_launch_is_bound_to_loopback(self, popen):
        popen.return_value = Mock()
        with TemporaryDirectory() as folder:
            executable = Path(folder) / "run.exe"
            executable.write_bytes(b"exe")
            voicevox_service.launch_engine(executable)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "50021")
        self.assertNotIn("--use_gpu", command)

    @patch("voicevox_service.subprocess.Popen")
    def test_engine_launch_can_enable_gpu(self, popen):
        popen.return_value = Mock()
        with TemporaryDirectory() as folder:
            executable = Path(folder) / "run.exe"
            executable.write_bytes(b"exe")
            voicevox_service.launch_engine(executable, use_gpu=True)
        command = popen.call_args.args[0]
        self.assertIn("--use_gpu", command)

    @patch("voicevox_service.engine_version", return_value="0.26.0")
    @patch("voicevox_service.subprocess.run")
    @patch("voicevox_service.os.name", "nt")
    def test_finds_voicevox_engine_listener_pid(self, run, _version):
        run.side_effect = [
            Mock(stdout="  TCP    127.0.0.1:50021   0.0.0.0:0   LISTENING   7232\n"),
            Mock(stdout='"run.exe","7232","Console","1","1 K"\n'),
        ]
        self.assertEqual(voicevox_service.find_running_engine_pid(), 7232)

    def test_invalid_voice_controls_are_rejected_before_network(self):
        with patch("voicevox_service.requests.post") as post:
            with self.assertRaises(ValueError):
                voicevox_service.synthesize_speech("text", "a.wav", style_id=1, speed=4)
        post.assert_not_called()

    def test_batch_splits_nonempty_lines_and_keeps_item_failures(self):
        with TemporaryDirectory() as folder, patch(
            "voicevox_service.synthesize_speech"
        ) as synthesize:
            def generate(text, output, **_kwargs):
                if text == "第二句":
                    raise RuntimeError("failed")
                Path(output).write_bytes(b"RIFF" + b"0" * 64)
                return Path(output)
            synthesize.side_effect = generate
            progress = []
            results = voicevox_service.synthesize_batch(
                "第一句\n\n第二句\n第三句",
                folder,
                style_id=13,
                on_progress=lambda *args: progress.append(args),
            )
        self.assertEqual(len(results), 3)
        self.assertEqual(Path(results[0][1]).name, "001_第一句.wav")
        self.assertIsInstance(results[1][2], RuntimeError)
        self.assertEqual(Path(results[2][1]).name, "003_第三句.wav")
        self.assertEqual([item[0] for item in progress], [1, 2, 3])

    def test_script_split_uses_lines_punctuation_and_length_limit(self):
        parts = voicevox_service.split_script_text(
            "こんにちは。今日は晴れです！\n\n短い行\n" + "長" * 85,
            max_chars=40,
        )
        self.assertEqual(parts[:3], ["こんにちは。", "今日は晴れです！", "短い行"])
        self.assertTrue(all(1 <= len(part) <= 40 for part in parts))

    def test_script_builds_matching_wav_and_srt_timeline(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            def fake_synthesis(text, output, **_kwargs):
                frames = 24000 if text.startswith("一") else 12000
                with wave.open(str(output), "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                    wav.writeframes(b"\0\0" * frames)
                return Path(output)
            with patch("voicevox_service.synthesize_speech", side_effect=fake_synthesis):
                wav_path, srt_path, report = voicevox_service.synthesize_script(
                    "一番目です。二番です。", root / "sample.wav", style_id=13, pause_seconds=0.3
                )
            with wave.open(str(wav_path), "rb") as wav:
                self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 1.8, places=3)
            cues = voicevox_service.parse_srt(srt_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(len(cues), 2)
            self.assertAlmostEqual(cues[0].start, 0.0, places=3)
            self.assertAlmostEqual(cues[0].end, 1.0, places=3)
            self.assertAlmostEqual(cues[1].start, 1.3, places=3)
            self.assertAlmostEqual(cues[1].end, 1.8, places=3)
            self.assertEqual(len(report), 2)

    def test_multiple_scripts_continue_after_one_file_fails(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            good = root / "good.txt"; good.write_text("成功です。", encoding="utf-8")
            missing = root / "missing.txt"
            def fake_script(_text, output, **_kwargs):
                target = Path(output); target.write_bytes(b"RIFF")
                subtitle = target.with_suffix(".srt"); subtitle.write_text("ok", encoding="utf-8")
                return target, subtitle, []
            with patch("voicevox_service.synthesize_script", side_effect=fake_script):
                results = voicevox_service.synthesize_script_files(
                    [missing, good], root / "out", style_id=13
                )
            self.assertIsNotNone(results[0]["error"])
            self.assertIsNone(results[1]["error"])
            self.assertEqual(results[1]["wav"].name, "good.wav")

    @patch("voicevox_service.subprocess.run")
    def test_convert_audio_uses_selected_format_and_removes_full_wav(self, run):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "voice.wav"; source.write_bytes(b"RIFF" + b"0" * 64)
            ffmpeg = root / "ffmpeg.exe"; ffmpeg.write_bytes(b"exe")
            def converted(command, **_kwargs):
                Path(command[-1]).write_bytes(b"ID3" + b"0" * 64)
                return Mock(returncode=0, stderr=b"")
            run.side_effect = converted
            output = voicevox_service.convert_audio(source, "mp3", ffmpeg)
            self.assertEqual(output.name, "voice.mp3")
            self.assertTrue(output.exists())
            self.assertFalse(source.exists())
        self.assertIn("libmp3lame", run.call_args.args[0])

    def test_parse_srt_and_build_timeline_audio(self):
        content = """1
00:00:01,000 --> 00:00:02,000
こんにちは。

2
00:00:03,000 --> 00:00:04,500
二番目です。
"""
        cues = voicevox_service.parse_srt(content)
        self.assertEqual([(cue.start, cue.end) for cue in cues], [(1.0, 2.0), (3.0, 4.5)])
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "sample.srt"
            source.write_text(content, encoding="utf-8")
            def fake_synthesis(_text, output, **_kwargs):
                with wave.open(str(output), "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                    wav.writeframes(b"\0\0" * 12000)
                return Path(output)
            with patch("voicevox_service.synthesize_speech", side_effect=fake_synthesis):
                output, report = voicevox_service.synthesize_srt(source, root / "track.wav", style_id=13)
            with wave.open(str(output), "rb") as wav:
                self.assertAlmostEqual(wav.getnframes() / wav.getframerate(), 4.5, places=2)
            self.assertEqual(len(report), 2)
            self.assertTrue(all(not item["overrun"] for item in report))


if __name__ == "__main__":
    unittest.main()
