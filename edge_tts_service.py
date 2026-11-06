"""Microsoft Edge online TTS integration."""
from __future__ import annotations
import asyncio, re
from pathlib import Path
from typing import Callable
import edge_tts
from edge_tts_access import require_key

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_OPTIONS = [
    ("中文 / 晓晓", "zh-CN-XiaoxiaoNeural"),
    ("中文 / 云希", "zh-CN-YunxiNeural"),
    ("英语 / Jenny", "en-US-JennyNeural"),
    ("英语 / Aria", "en-US-AriaNeural"),
    ("日语 / Nanami", "ja-JP-NanamiNeural"),
    ("韩语 / SunHi", "ko-KR-SunHiNeural"),
    ("西班牙语 / Elvira", "es-ES-ElviraNeural"),
    ("法语 / Denise", "fr-FR-DeniseNeural"),
    ("德语 / Katja", "de-DE-KatjaNeural"),
]

class EdgeTTSError(RuntimeError): pass

def validate_voice(voice: str) -> str:
    value=str(voice or "").strip()
    if not value or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]+){2,}", value):
        raise ValueError("Edge TTS 音色无效")
    return value

def rate_to_edge(rate: float) -> str:
    value=float(rate)
    if not 0.5 <= value <= 2.0: raise ValueError("语速必须在 0.5 到 2.0 之间")
    percent=round((value-1)*100)
    return f"{percent:+d}%"

def _run(coro):
    try: return asyncio.run(coro)
    except RuntimeError as exc: raise EdgeTTSError(f"Edge TTS 运行失败：{exc}") from exc

async def _save(text: str, output: Path, voice: str, rate: str, volume: str, pitch: str):
    communicate=edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch, boundary="SentenceBoundary")
    cues=[]
    with output.open("wb") as stream:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                stream.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                cues.append((chunk["offset"]/10_000_000, (chunk["offset"]+chunk["duration"])/10_000_000, chunk["text"]))
    if not cues:
        raise EdgeTTSError("Edge TTS 未返回字幕时间信息，请重试")
    return cues

def synthesize_speech(text: str, output_path: str|Path, *, license_key: str='', **options):
    require_key(license_key)
    return _synthesize_speech(text, output_path, **options)

def preview_speech(output_path, *, voice=DEFAULT_VOICE, **options):
    """Play a fixed sample without requiring an Edge TTS license."""
    language = voice.split('-')[0].lower()
    samples = {'zh': '你好，这是语音试听，欢迎使用语音工作台。', 'en': 'Hello, this is a voice preview. Welcome to your voice studio.', 'ja': 'こんにちは。音声のサンプルをお聞きください。', 'ko': '안녕하세요. 음성 미리 듣기입니다.', 'fr': 'Bonjour, voici un aperçu de cette voix.', 'es': 'Hola, esta es una prueba de voz.', 'de': 'Hallo, dies ist eine Sprachvorschau.'}
    text = samples.get(language, 'Hello, this is a voice preview.')
    return _synthesize_speech(text, output_path, voice=voice, **options)

def _synthesize_speech(text: str, output_path: str|Path, *, voice: str=DEFAULT_VOICE, rate: float=1.0, volume: float=1.0, pitch: float=0.0):
    content=str(text or "").strip()
    if not content: raise ValueError("待转语音文本不能为空")
    selected=validate_voice(voice); rate_value=rate_to_edge(rate)
    if not 0.0 <= float(volume) <= 1.0: raise ValueError("音量必须在 0 到 1 之间")
    target=Path(output_path).expanduser().resolve().with_suffix(".mp3"); target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix(".mp3.tmp")
    try:
        cues=_run(_save(content,temporary,selected,rate_value,f"{round((float(volume)-1)*100):+d}%",f"{round(float(pitch)):+d}Hz"))
        if not temporary.exists() or temporary.stat().st_size == 0: raise EdgeTTSError("Edge TTS 未返回有效音频")
        temporary.replace(target)
        return target, cues
    except Exception as exc:
        raise EdgeTTSError(f"Edge TTS 合成失败：{exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

def synthesize_script_files(source_paths, output_directory, *, license_key='', voice=DEFAULT_VOICE, rate=1.0, volume=1.0, pitch=0.0, pause_seconds=0.3, output_format="mp3", ffmpeg_path=None, on_progress=None):
    """Use the same segmentation, pauses, output formats and timeline as VOICEVOX."""
    import os
    import subprocess
    import tempfile
    import voicevox_service

    require_key(license_key)
    selected=validate_voice(voice)
    rate_to_edge(rate)
    if not ffmpeg_path or not Path(ffmpeg_path).is_file():
        raise EdgeTTSError("FFmpeg is required for Edge TTS audio conversion")

    def sentence_audio(text, output, **_kwargs):
        target=Path(output)
        with tempfile.TemporaryDirectory(prefix="videoflow-edge-") as folder:
            audio,_=_synthesize_speech(text,Path(folder)/"speech.mp3",voice=selected,rate=rate,volume=volume,pitch=pitch)
            temporary=target.with_suffix(".tmp.wav")
            try:
                completed=subprocess.run([str(ffmpeg_path),"-y","-i",str(audio),"-ac","1","-ar","24000","-c:a","pcm_s16le",str(temporary)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,timeout=180)
                if completed.returncode or not temporary.is_file():
                    raise EdgeTTSError("FFmpeg conversion failed: "+completed.stderr.decode("utf-8",errors="replace")[-1000:])
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    return voicevox_service.synthesize_script_files(source_paths,output_directory,style_id=0,synthesize_sentence=sentence_audio,pause_seconds=pause_seconds,output_format=output_format,ffmpeg_path=ffmpeg_path,on_progress=on_progress)
