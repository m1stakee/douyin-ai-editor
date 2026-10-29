from pathlib import Path
from typing import Callable
from contextlib import contextmanager
import json
import mimetypes
import shutil
import subprocess
import sys
import tempfile
import time

import requests

from app_config import dashscope_key
from text_io import write_text

MODEL = "paraformer-v2"
UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
LANGUAGE_CODES = {"中文": "zh", "英语": "en", "日语": "ja", "韩语": "ko", "法语": "fr", "德语": "de", "俄语": "ru"}

def transcribe_request_config(language: str) -> dict:
    """Compatibility metadata retained for older callers and tests."""
    return {"endpoint": SUBMIT_URL, "model": MODEL, "language": LANGUAGE_CODES.get(language, "zh")}


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, 1):
        text = str(segment.get("text", "")).strip()
        if text:
            blocks.append(f"{index}\n{_srt_time(segment['start'])} --> {_srt_time(segment['end'])}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def segments_to_text(segments: list[dict]) -> str:
    lines = [str(segment.get("text", "")).strip() for segment in segments]
    lines = [line for line in lines if line]
    return "\n".join(lines) + ("\n" if lines else "")


def write_transcript_outputs(output_dir: Path, stem: str, segments: list[dict]) -> tuple[Path, Path, Path]:
    """Write the matched JSON, SRT and TXT transcript artifacts as UTF-8."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    srt_path = output_dir / f"{stem}.srt"
    txt_path = output_dir / f"{stem}.txt"
    write_text(json_path, json.dumps(segments, ensure_ascii=False, indent=2), bom=False)
    write_text(srt_path, segments_to_srt(segments))
    write_text(txt_path, segments_to_text(segments))
    return json_path, srt_path, txt_path


def resolve_ffmpeg(configured: str = "") -> str:
    candidates = [configured.strip()] if configured.strip() else []
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    bundle_root = Path(getattr(sys, "_MEIPASS", root))
    candidates.extend([str(bundle_root / "ffmpeg.exe"), str(root / "ffmpeg.exe"), shutil.which("ffmpeg") or ""])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError("未找到内置 ffmpeg.exe，请重新安装软件")


@contextmanager
def prepared_asr_audio(media_path: str, ffmpeg: str = "", on_status: Callable[[str], None] | None = None):
    source = Path(media_path)
    if not source.is_file():
        raise FileNotFoundError(f"待转写文件不存在：{source}")
    notify = on_status or (lambda _status: None)
    notify("提取音频")
    with tempfile.TemporaryDirectory(prefix="videoflow-asr-") as folder:
        target = Path(folder) / f"{source.stem[:80]}.mp3"
        result = subprocess.run(
            [resolve_ffmpeg(ffmpeg), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(target)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode or not target.is_file() or not target.stat().st_size:
            raise RuntimeError(result.stderr[-2000:] or "FFmpeg 提取音频失败")
        yield str(target)


def _raise_api_error(response: requests.Response, action: str) -> None:
    if response.status_code in (401, 403):
        raise RuntimeError("阿里云百炼 API Key 无效、无权限或服务尚未开通")
    if response.status_code == 429:
        raise RuntimeError(f"阿里云百炼{action}触发限流，请稍后重试")
    try:
        detail = response.json().get("message") or response.text
    except ValueError:
        detail = response.text
    raise RuntimeError(f"阿里云百炼{action}失败（HTTP {response.status_code}）：{str(detail)[:500]}")


def upload_temporary_file(media_path: str, key: str) -> str:
    path = Path(media_path)
    if not path.is_file():
        raise FileNotFoundError(f"待转写文件不存在：{path}")
    response = requests.get(
        UPLOAD_POLICY_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": MODEL},
        timeout=(15, 60),
    )
    if response.status_code != 200:
        _raise_api_error(response, "获取上传凭证")
    policy = response.json().get("data") or {}
    max_mb = float(policy.get("max_file_size_mb") or 1024)
    if path.stat().st_size > max_mb * 1024 * 1024:
        raise RuntimeError(f"音频文件超过阿里云当前模型的 {max_mb:g} MB 上传限制")
    object_key = f"{policy['upload_dir']}/{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as handle:
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, object_key),
            "success_action_status": (None, "200"),
            "file": (path.name, handle, content_type),
        }
        uploaded = requests.post(policy["upload_host"], files=files, timeout=(15, 600))
    if uploaded.status_code != 200:
        _raise_api_error(uploaded, "上传音频")
    return f"oss://{object_key}"


def _parse_segments(payload: dict) -> list[dict]:
    transcripts = payload.get("transcripts") or []
    segments = []
    for transcript in transcripts:
        for sentence in transcript.get("sentences") or []:
            text = str(sentence.get("text") or "").strip()
            if text:
                segments.append({"id": len(segments) + 1, "start": float(sentence.get("begin_time", 0)) / 1000, "end": float(sentence.get("end_time", 0)) / 1000, "text": text})
    if not segments:
        raise ValueError("阿里云转写结果中缺少句子时间戳")
    return segments


def transcribe(media_path: str, key: str = "", language: str = "中文", on_status: Callable[[str], None] | None = None) -> list[dict]:
    """Transcribe an audio file with the only supported provider: Aliyun Bailian."""
    key = key.strip() or dashscope_key()
    if not key:
        raise ValueError("请填写阿里云百炼 API Key")
    notify = on_status or (lambda _status: None)
    notify("上传阿里云")
    file_url = upload_temporary_file(media_path, key)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-DashScope-Async": "enable", "X-DashScope-OssResourceResolve": "enable"}
    language_code = LANGUAGE_CODES.get(language, "zh")
    body = {"model": MODEL, "input": {"file_urls": [file_url]}, "parameters": {"channel_id": [0], "language_hints": [language_code, "en"] if language_code != "en" else ["en"], "timestamp_alignment_enabled": True}}
    response = requests.post(SUBMIT_URL, headers=headers, json=body, timeout=(15, 60))
    if response.status_code != 200:
        _raise_api_error(response, "提交转写任务")
    task_id = (response.json().get("output") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("阿里云未返回转写任务 ID")
    notify("等待阿里识别")
    deadline = time.monotonic() + 30 * 60
    while time.monotonic() < deadline:
        result = requests.get(TASK_URL.format(task_id=task_id), headers=headers, timeout=(15, 60))
        if result.status_code != 200:
            _raise_api_error(result, "查询转写任务")
        output = result.json().get("output") or {}
        status = output.get("task_status")
        if status == "SUCCEEDED":
            rows = output.get("results") or []
            succeeded = next((row for row in rows if row.get("subtask_status") == "SUCCEEDED"), None)
            if not succeeded:
                message = next((row.get("message") for row in rows if row.get("message")), "文件转写失败")
                raise RuntimeError(f"阿里云转写失败：{message}")
            transcript = requests.get(succeeded.get("transcription_url"), timeout=(15, 60))
            if transcript.status_code != 200:
                _raise_api_error(transcript, "下载转写结果")
            return _parse_segments(transcript.json())
        if status not in ("PENDING", "RUNNING"):
            raise RuntimeError(f"阿里云转写任务异常：{output.get('message') or status or '未知状态'}")
        time.sleep(1.5)
    raise TimeoutError("阿里云转写等待超过 30 分钟，请点击重试")
