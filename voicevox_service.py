"""VOICEVOX 本地引擎发现、启动和语音合成。

本模块不重新分发 VOICEVOX。用户从官方渠道安装后，应用只连接本机
``127.0.0.1`` 上的 VOICEVOX Engine HTTP API。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import wave
from text_io import read_text, write_text
import csv
import io
import ctypes
from ctypes import wintypes
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


DEFAULT_ENGINE_URL = "http://127.0.0.1:50021"
OFFICIAL_DOWNLOAD_URL = "https://voicevox.hiroshiba.jp/"
SUPPORTED_OUTPUT_FORMATS = {"wav", "mp3", "m4a", "flac"}


class VoicevoxError(RuntimeError):
    """VOICEVOX 安装、连接或合成失败。"""


@dataclass(frozen=True)
class VoiceOption:
    name: str
    style: str
    style_id: int
    speaker_uuid: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} / {self.style}"


@dataclass(frozen=True)
class SrtCue:
    index: int
    start: float
    end: float
    text: str


def normalize_engine_url(value: str = DEFAULT_ENGINE_URL) -> str:
    url = str(value or DEFAULT_ENGINE_URL).strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("VOICEVOX 地址必须是本机 HTTP 地址，例如 http://127.0.0.1:50021")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("VOICEVOX 地址格式无效")
    return url


def _candidate_roots() -> list[Path]:
    values = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
    ]
    roots: list[Path] = []
    for value in values:
        if not value:
            continue
        base = Path(value)
        roots.extend((base / "Programs" / "VOICEVOX", base / "VOICEVOX"))
    return roots


def _installation_executable(path: str | Path) -> Path | None:
    selected = Path(path).expanduser()
    if selected.is_file():
        return selected if selected.name.lower() in {"voicevox.exe", "run.exe"} else None
    candidates = (
        selected / "vv-engine" / "run.exe",
        selected / "resources" / "vv-engine" / "run.exe",
        selected / "VOICEVOX.exe",
        selected / "run.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def find_installation(preferred: str | Path | None = None) -> Path | None:
    """查找用户安装的 VOICEVOX 或引擎可执行文件。"""
    if preferred:
        found = _installation_executable(preferred)
        if found:
            return found.resolve()
        if Path(preferred).expanduser().exists():
            return None
    for root in _candidate_roots():
        found = _installation_executable(root)
        if found:
            return found.resolve()
    roaming = os.environ.get("APPDATA", "")
    if roaming:
        engine_root = Path(roaming) / "voicevox" / "vvpp-engines"
        engines = sorted(
            engine_root.glob("VOICEVOX_Engine*/run.exe"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ) if engine_root.is_dir() else []
        if engines:
            return engines[0].resolve()
    return None


def engine_version(
    engine_url: str = DEFAULT_ENGINE_URL,
    *,
    timeout: float = 1.5,
    request_get: Callable = requests.get,
) -> str | None:
    """返回运行中引擎的版本；没有运行时返回 ``None``。"""
    try:
        response = request_get(f"{normalize_engine_url(engine_url)}/version", timeout=timeout)
        response.raise_for_status()
        value = response.json()
        return str(value).strip() if value is not None else None
    except (requests.RequestException, ValueError, TypeError):
        return None


def launch_engine(
    executable: str | Path,
    engine_url: str = DEFAULT_ENGINE_URL,
    *,
    use_gpu: bool = False,
) -> subprocess.Popen:
    """后台启动用户已安装的 VOICEVOX；返回由本应用创建的进程。"""
    target = _installation_executable(executable)
    if not target:
        raise VoicevoxError("没有找到 VOICEVOX.exe 或 vv-engine/run.exe")
    if use_gpu and target.name.lower() != "run.exe":
        engine = find_installation()
        if not engine or engine.name.lower() != "run.exe":
            raise VoicevoxError("GPU 模式需要选择 VOICEVOX 引擎的 vv-engine/run.exe")
        target = engine
    parsed = urlparse(normalize_engine_url(engine_url))
    command = [str(target)]
    if target.name.lower() == "run.exe":
        command.extend(("--host", "127.0.0.1", "--port", str(parsed.port or 50021)))
        if use_gpu:
            command.append("--use_gpu")
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        return subprocess.Popen(
            command,
            cwd=str(target.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise VoicevoxError(f"VOICEVOX 启动失败：{exc}") from exc


def wait_until_ready(
    engine_url: str = DEFAULT_ENGINE_URL,
    *,
    timeout: float = 45.0,
    interval: float = 0.5,
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        version = engine_version(engine_url)
        if version:
            return version
        time.sleep(interval)
    raise VoicevoxError("VOICEVOX 启动超时，请确认安装完整或手动启动 VOICEVOX")


def available_voices(engine_url: str = DEFAULT_ENGINE_URL, *, timeout: float = 10.0) -> list[VoiceOption]:
    try:
        response = requests.get(f"{normalize_engine_url(engine_url)}/speakers", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise VoicevoxError(f"读取 VOICEVOX 音色失败：{exc}") from exc
    voices: list[VoiceOption] = []
    for speaker in payload if isinstance(payload, list) else []:
        if not isinstance(speaker, dict):
            continue
        name = str(speaker.get("name", "")).strip()
        speaker_uuid = str(speaker.get("speaker_uuid", "")).strip()
        for style in speaker.get("styles", []):
            if not isinstance(style, dict) or "id" not in style:
                continue
            voices.append(VoiceOption(name, str(style.get("name", "ノーマル")), int(style["id"]), speaker_uuid))
    if not voices:
        raise VoicevoxError("VOICEVOX 没有返回可用音色")
    return voices


def synthesize_speech(
    text: str,
    output_path: str | Path,
    *,
    style_id: int,
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
    intonation: float = 1.0,
    engine_url: str = DEFAULT_ENGINE_URL,
    timeout: float = 180.0,
) -> Path:
    """调用本机 VOICEVOX Engine 生成 WAV，并原子写入输出文件。"""
    content = str(text or "").strip()
    if not content:
        raise ValueError("待转语音文本不能为空")
    speed_value = float(speed)
    pitch_value = float(pitch)
    volume_value = float(volume)
    intonation_value = float(intonation)
    if not 0.5 <= speed_value <= 2.0:
        raise ValueError("语速必须在 0.5 到 2.0 之间")
    if not -0.15 <= pitch_value <= 0.15:
        raise ValueError("音高必须在 -0.15 到 0.15 之间")
    if not 0.0 <= volume_value <= 2.0:
        raise ValueError("音量必须在 0 到 2.0 之间")
    if not 0.0 <= intonation_value <= 2.0:
        raise ValueError("语调必须在 0 到 2.0 之间")

    base = normalize_engine_url(engine_url)
    speaker = int(style_id)
    try:
        query_response = requests.post(
            f"{base}/audio_query",
            params={"text": content, "speaker": speaker},
            timeout=min(timeout, 60.0),
        )
        query_response.raise_for_status()
        query = query_response.json()
        query.update(
            speedScale=speed_value,
            pitchScale=pitch_value,
            volumeScale=volume_value,
            intonationScale=intonation_value,
        )
        audio_response = requests.post(
            f"{base}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=timeout,
        )
        audio_response.raise_for_status()
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise VoicevoxError(f"VOICEVOX 语音生成失败：{exc}") from exc

    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".wav.tmp")
    try:
        temporary.write_bytes(audio_response.content)
        if temporary.stat().st_size < 44:
            raise VoicevoxError("VOICEVOX 返回的音频文件无效")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def split_batch_text(text: str) -> list[str]:
    """将输入按非空行拆分为批量合成项目。"""
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def split_script_text(text: str, *, max_chars: int = 80) -> list[str]:
    """按换行和中日文句末标点拆分文案，供语音与字幕共用。"""
    if max_chars < 10:
        raise ValueError("每条字幕最大字数不能小于 10")
    sentences: list[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[。！？!?])\s*", line)
        for part in parts:
            remaining = part.strip()
            while len(remaining) > max_chars:
                cut = max(
                    remaining.rfind(mark, 0, max_chars + 1)
                    for mark in ("、", "，", ",", "；", ";", " ")
                )
                if cut < max_chars // 2:
                    cut = max_chars
                else:
                    cut += 1
                sentences.append(remaining[:cut].strip())
                remaining = remaining[cut:].strip()
            if remaining:
                sentences.append(remaining)
    if not sentences:
        raise ValueError("文案中没有可生成的内容")
    return sentences


def read_script_file(path: str | Path) -> str:
    """读取常见 Windows/日文 TXT 编码。"""
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != ".txt":
        raise ValueError(f"只支持 TXT 文案：{source.name}")
    data = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文案编码，请保存为 UTF-8：{source.name}")


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def synthesize_script(
    text: str,
    output_path: str | Path,
    *,
    style_id: int,
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
    intonation: float = 1.0,
    pause_seconds: float = 0.3,
    max_chars: int = 80,
    engine_url: str = DEFAULT_ENGINE_URL,
    on_progress: Callable[[int, int, str, Path], None] | None = None,
) -> tuple[Path, Path, list[dict]]:
    """将一份文案生成同名 WAV、同步 SRT 和逐句 WAV。"""
    pause = float(pause_seconds)
    if not 0.0 <= pause <= 5.0:
        raise ValueError("句间停顿必须在 0 到 5 秒之间")
    sentences = split_script_text(text, max_chars=max_chars)
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    subtitle = target.with_suffix(".srt")
    segment_dir = target.parent / f"{target.stem}_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    silence = array("h", [0]) * int(round(pause * sample_rate))
    combined = array("h")
    report: list[dict] = []
    current_time = 0.0

    for index, sentence in enumerate(sentences, 1):
        segment_path = segment_dir / _safe_audio_name(sentence, index)
        output = synthesize_speech(
            sentence,
            segment_path,
            style_id=style_id,
            speed=speed,
            pitch=pitch,
            volume=volume,
            intonation=intonation,
            engine_url=engine_url,
        )
        with wave.open(str(output), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != sample_rate:
                raise VoicevoxError("VOICEVOX 分段音频不是预期的 24kHz 单声道 16-bit WAV")
            frames = array("h")
            frames.frombytes(wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            frames.byteswap()
        start = current_time
        duration = len(frames) / sample_rate
        end = start + duration
        combined.extend(frames)
        if index < len(sentences):
            combined.extend(silence)
            current_time = end + pause
        else:
            current_time = end
        report.append({
            "index": index,
            "text": sentence,
            "start": start,
            "end": end,
            "audio_duration": duration,
            "segment_path": output,
        })
        if on_progress:
            on_progress(index, len(sentences), sentence, output)

    wav_temporary = target.with_suffix(".wav.tmp")
    srt_temporary = subtitle.with_suffix(".srt.tmp")
    try:
        with wave.open(str(wav_temporary), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            output_frames = array("h", combined)
            if sys.byteorder != "little":
                output_frames.byteswap()
            wav.writeframes(output_frames.tobytes())
        blocks = [
            f"{item['index']}\n{_srt_timestamp(item['start'])} --> {_srt_timestamp(item['end'])}\n{item['text']}"
            for item in report
        ]
        write_text(srt_temporary, "\n\n".join(blocks) + "\n")
        wav_temporary.replace(target)
        srt_temporary.replace(subtitle)
    except Exception:
        wav_temporary.unlink(missing_ok=True)
        srt_temporary.unlink(missing_ok=True)
        raise
    return target, subtitle, report


def synthesize_script_files(
    source_paths: list[str | Path],
    output_directory: str | Path,
    *,
    style_id: int,
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
    intonation: float = 1.0,
    pause_seconds: float = 0.3,
    output_format: str = "wav",
    ffmpeg_path: str | Path | None = None,
    engine_url: str = DEFAULT_ENGINE_URL,
    on_progress: Callable[[int, int, Path, int, int], None] | None = None,
) -> list[dict]:
    """批量处理 TXT；某个文件失败时继续处理其余文件。"""
    sources = [Path(item).expanduser().resolve() for item in source_paths]
    if not sources:
        raise ValueError("请先导入至少一个 TXT 文案")
    audio_format = str(output_format or "wav").strip().lower()
    if audio_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError("输出格式只支持 WAV、MP3、M4A 或 FLAC")
    if audio_format != "wav" and not ffmpeg_path:
        raise VoicevoxError("输出非 WAV 格式需要 FFmpeg")
    folder = Path(output_directory).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    used_names: set[str] = set()
    for file_index, source in enumerate(sources, 1):
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source.stem).strip(" .") or f"voice_{file_index}"
        try:
            if stem.casefold() in used_names:
                raise ValueError(f"存在同名文案：{source.name}；语音输出不会自动添加后缀，请保留一个或先重命名")
            used_names.add(stem.casefold())
            text = read_script_file(source)

            def sentence_progress(current: int, total: int, _text: str, _path: Path) -> None:
                if on_progress:
                    on_progress(file_index, len(sources), source, current, total)

            wav_path, srt_path, report = synthesize_script(
                text,
                folder / f"{stem}.wav",
                style_id=style_id,
                speed=speed,
                pitch=pitch,
                volume=volume,
                intonation=intonation,
                pause_seconds=pause_seconds,
                engine_url=engine_url,
                on_progress=sentence_progress,
            )
            audio_path = convert_audio(wav_path, audio_format, ffmpeg_path) if audio_format != "wav" else wav_path
            results.append({"source": source, "audio": audio_path, "wav": audio_path, "srt": srt_path, "report": report, "error": None})
        except Exception as exc:
            results.append({"source": source, "audio": None, "wav": None, "srt": None, "report": [], "error": exc})
    return results


def convert_audio(
    wav_path: str | Path,
    output_format: str,
    ffmpeg_path: str | Path | None,
) -> Path:
    """使用 FFmpeg 将完整 WAV 转成所选格式；成功后移除原始完整 WAV。"""
    source = Path(wav_path).expanduser().resolve()
    audio_format = str(output_format or "wav").strip().lower()
    if audio_format == "wav":
        return source
    if audio_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError("输出格式只支持 WAV、MP3、M4A 或 FLAC")
    if not ffmpeg_path or not Path(ffmpeg_path).expanduser().is_file():
        raise VoicevoxError("未找到 FFmpeg，无法转换音频格式")
    target = source.with_suffix(f".{audio_format}")
    temporary = target.with_name(f"{target.stem}.tmp{target.suffix}")
    codec_args = {
        "mp3": ["-codec:a", "libmp3lame", "-b:a", "192k"],
        "m4a": ["-codec:a", "aac", "-b:a", "192k"],
        "flac": ["-codec:a", "flac"],
    }[audio_format]
    command = [str(Path(ffmpeg_path).expanduser()), "-y", "-i", str(source), "-vn", *codec_args, str(temporary)]
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if completed.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise VoicevoxError(f"音频转换为 {audio_format.upper()} 失败" + (f"：{detail[-1]}" if detail else ""))
        temporary.replace(target)
        source.unlink()
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _safe_audio_name(text: str, index: int, *, limit: int = 36) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    stem = re.sub(r"\s+", " ", stem)[:limit].strip(" .") or "voice"
    return f"{index:03d}_{stem}.wav"


def synthesize_batch(
    text: str,
    output_directory: str | Path,
    *,
    style_id: int,
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
    intonation: float = 1.0,
    engine_url: str = DEFAULT_ENGINE_URL,
    on_progress: Callable[[int, int, str, Path | None, Exception | None], None] | None = None,
) -> list[tuple[str, Path | None, Exception | None]]:
    """按非空行顺序生成多个 WAV；单项失败不会中断后续项目。"""
    lines = split_batch_text(text)
    if not lines:
        raise ValueError("批量文本至少需要一行非空内容")
    folder = Path(output_directory).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, Path | None, Exception | None]] = []
    total = len(lines)
    for index, line in enumerate(lines, 1):
        target = folder / _safe_audio_name(line, index)
        try:
            output = synthesize_speech(
                line,
                target,
                style_id=style_id,
                speed=speed,
                pitch=pitch,
                volume=volume,
                intonation=intonation,
                engine_url=engine_url,
            )
            item = (line, output, None)
        except Exception as exc:
            item = (line, None, exc)
        results.append(item)
        if on_progress:
            on_progress(index, total, line, item[1], item[2])
    return results


_SRT_TIME_RE = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})"
)


def _srt_seconds(hours: str, minutes: str, seconds: str, milliseconds: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def parse_srt(text: str) -> list[SrtCue]:
    """解析常规 SRT，保留多行字幕文本。"""
    blocks = re.split(r"\r?\n\s*\r?\n", str(text or "").strip())
    cues: list[SrtCue] = []
    for position, block in enumerate(blocks, 1):
        lines = [line.strip("\ufeff\r") for line in block.splitlines()]
        if not lines:
            continue
        time_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if time_index < 0:
            raise ValueError(f"第 {position} 个字幕块缺少时间轴")
        match = _SRT_TIME_RE.fullmatch(lines[time_index].strip())
        if not match:
            raise ValueError(f"第 {position} 个字幕块时间格式无效：{lines[time_index]}")
        values = match.groupdict()
        start = _srt_seconds(values["sh"], values["sm"], values["ss"], values["sms"])
        end = _srt_seconds(values["eh"], values["em"], values["es"], values["ems"])
        if end <= start:
            raise ValueError(f"第 {position} 个字幕块结束时间必须晚于开始时间")
        content = " ".join(line.strip() for line in lines[time_index + 1 :] if line.strip())
        if not content:
            continue
        try:
            index = int(lines[0]) if time_index > 0 else position
        except ValueError:
            index = position
        cues.append(SrtCue(index, start, end, content))
    if not cues:
        raise ValueError("SRT 中没有可转换的字幕")
    return cues


def synthesize_srt(
    srt_path: str | Path,
    output_path: str | Path,
    *,
    style_id: int,
    speed: float = 1.0,
    pitch: float = 0.0,
    volume: float = 1.0,
    intonation: float = 1.0,
    engine_url: str = DEFAULT_ENGINE_URL,
    on_progress: Callable[[int, int, SrtCue, Path], None] | None = None,
) -> tuple[Path, list[dict]]:
    """逐句合成 SRT，并按字幕开始时间混合为一条 24kHz 单声道 WAV。"""
    source = Path(srt_path).expanduser().resolve()
    cues = parse_srt(read_text(source))
    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".wav":
        target = target.with_suffix(".wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    segment_dir = target.parent / f"{target.stem}_segments"
    segment_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = 24000
    timeline = array("h", [0]) * max(1, int(round(max(cue.end for cue in cues) * sample_rate)))
    report: list[dict] = []
    for position, cue in enumerate(cues, 1):
        segment_path = segment_dir / _safe_audio_name(cue.text, position)
        output = synthesize_speech(
            cue.text,
            segment_path,
            style_id=style_id,
            speed=speed,
            pitch=pitch,
            volume=volume,
            intonation=intonation,
            engine_url=engine_url,
        )
        with wave.open(str(output), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != sample_rate:
                raise VoicevoxError("VOICEVOX 分段音频不是预期的 24kHz 单声道 16-bit WAV")
            frames = array("h")
            frames.frombytes(wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            frames.byteswap()
        offset = int(round(cue.start * sample_rate))
        required = offset + len(frames)
        if required > len(timeline):
            timeline.extend([0] * (required - len(timeline)))
        for sample_index, sample in enumerate(frames):
            mixed = timeline[offset + sample_index] + sample
            timeline[offset + sample_index] = max(-32768, min(32767, mixed))
        duration = len(frames) / sample_rate
        report.append({
            "index": cue.index,
            "text": cue.text,
            "start": cue.start,
            "end": cue.end,
            "audio_duration": duration,
            "overrun": duration > cue.end - cue.start,
            "segment_path": output,
        })
        if on_progress:
            on_progress(position, len(cues), cue, output)
    temporary = target.with_suffix(".wav.tmp")
    try:
        with wave.open(str(temporary), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            if sys.byteorder != "little":
                timeline.byteswap()
            wav.writeframes(timeline.tobytes())
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target, report


def stop_owned_process(process: subprocess.Popen | None, *, timeout: float = 5.0) -> None:
    """只关闭本应用启动的引擎，不影响用户原先打开的 VOICEVOX。"""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def find_running_engine_pid(engine_url: str = DEFAULT_ENGINE_URL) -> int | None:
    """返回监听指定本机端口的 VOICEVOX run.exe 进程 ID。"""
    parsed = urlparse(normalize_engine_url(engine_url))
    port = parsed.port or 50021
    if os.name != "nt" or not engine_version(engine_url):
        return None
    completed = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP" or fields[3].upper() != "LISTENING":
            continue
        if not fields[1].rsplit(":", 1)[-1] == str(port) or not fields[4].isdigit():
            continue
        pid = int(fields[4])
        if _windows_process_name(pid) == "run.exe":
            return pid
    return None


def _windows_process_name(pid: int) -> str:
    task = subprocess.run(
        ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    rows = list(csv.reader(io.StringIO(task.stdout)))
    return rows[0][0].strip().lower() if rows and rows[0] else ""


def _windows_parent_pid(pid: int) -> int | None:
    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = ProcessEntry(); entry.dwSize = ctypes.sizeof(ProcessEntry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.th32ProcessID == int(pid):
                return int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)


def stop_engine(
    process: subprocess.Popen | None = None,
    engine_url: str = DEFAULT_ENGINE_URL,
    *,
    timeout: float = 5.0,
) -> bool:
    """关闭本软件启动或当前监听端口的 VOICEVOX 引擎。"""
    if process is not None and process.poll() is None:
        stop_owned_process(process, timeout=timeout)
        return True
    pid = find_running_engine_pid(engine_url)
    if pid is None:
        return False
    parent_pid = _windows_parent_pid(pid)
    target_pid = parent_pid if parent_pid and _windows_process_name(parent_pid) == "voicevox.exe" else pid
    completed = subprocess.run(
        ["taskkill", "/PID", str(target_pid), "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise VoicevoxError("无法退出 VOICEVOX 引擎" + (f"：{detail}" if detail else ""))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not engine_version(engine_url, timeout=0.3):
            return True
        time.sleep(0.15)
    raise VoicevoxError("VOICEVOX 引擎已被外部程序重新启动，请先退出 VOICEVOX 桌面程序")
