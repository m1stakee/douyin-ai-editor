"""Azure Speech 文本转 MP3 服务。

从遗失程序的逆向逻辑整理而来，供项目中的其他模块直接调用。
密钥默认只从环境变量读取，不会写入源码或日志。
"""

from __future__ import annotations

import html
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


AZURE_SPEECH_KEY_ENV = "AZURE_SPEECH_KEY"
AZURE_SPEECH_REGION_ENV = "AZURE_SPEECH_REGION"
DEFAULT_VOICE = "zh-CN-YunyiMultilingualNeural"
DEFAULT_RATE = 1.3


@dataclass(frozen=True)
class VoiceOption:
    name: str
    label: str
    locale: str
    gender: str


VOICE_OPTIONS: tuple[VoiceOption, ...] = (
    VoiceOption("zh-CN-YunyiMultilingualNeural", "云逸·多语言（男）", "zh-CN", "Male"),
    VoiceOption("zh-CN-XiaoxiaoNeural", "晓晓（女）", "zh-CN", "Female"),
    VoiceOption("zh-CN-YunxiNeural", "云希（男）", "zh-CN", "Male"),
    VoiceOption("zh-CN-YunjianNeural", "云健（男）", "zh-CN", "Male"),
    VoiceOption("ja-JP-NanamiNeural", "七海·日语（女）", "ja-JP", "Female"),
    VoiceOption("ja-JP-KeitaNeural", "圭太·日语（男）", "ja-JP", "Male"),
    VoiceOption("zh-TW-HsiaoChenNeural", "曉臻·繁体（女）", "zh-TW", "Female"),
)


class AzureTTSError(RuntimeError):
    """Azure TTS 配置、请求或文件保存失败。"""


def available_voices() -> list[dict[str, str]]:
    """返回适合直接填充到下拉框的预设音色列表。"""
    return [
        {
            "name": voice.name,
            "label": voice.label,
            "locale": voice.locale,
            "gender": voice.gender,
        }
        for voice in VOICE_OPTIONS
    ]


def resolve_voice(value: str | None) -> str:
    """接受 Azure 音色名或预设中文标签，返回 Azure 音色名。

    未列入预设的 Azure 音色名也允许使用，方便调用方使用新音色。
    """
    selected = (value or DEFAULT_VOICE).strip()
    if not selected:
        return DEFAULT_VOICE
    for voice in VOICE_OPTIONS:
        if selected in {voice.name, voice.label}:
            return voice.name
    return selected


def rate_to_ssml(rate: float | int | str) -> str:
    """把 1.3 倍等倍率转换为 Azure SSML 的 +30% 格式。"""
    try:
        value = float(rate)
    except (TypeError, ValueError) as exc:
        raise ValueError("语速必须是数字，例如 1.0 或 1.3") from exc
    if not 0.1 <= value <= 3.0:
        raise ValueError("语速必须在 0.1 到 3.0 倍之间")
    delta = int(round((value - 1.0) * 100))
    return "0%" if delta == 0 else f"{delta:+d}%"


def build_ssml(text: str, voice: str = DEFAULT_VOICE, rate: float = DEFAULT_RATE) -> str:
    """构造 Azure Speech 使用的安全 SSML。"""
    content = str(text or "").strip()
    if not content:
        raise ValueError("待转语音文本不能为空")
    voice_name = resolve_voice(voice)
    locale = next((item.locale for item in VOICE_OPTIONS if item.name == voice_name), "zh-CN")
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{html.escape(locale, quote=True)}">'
        f'<voice name="{html.escape(voice_name, quote=True)}">'
        f'<prosody rate="{rate_to_ssml(rate)}">{html.escape(content, quote=True)}</prosody>'
        "</voice></speak>"
    )


def _load_speech_sdk():
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise AzureTTSError(
            "未安装 Azure Speech SDK，请执行：pip install azure-cognitiveservices-speech"
        ) from exc
    return speechsdk


def _select_mp3_format(speechsdk):
    candidates = (
        "Audio24Khz48KBitRateMonoMp3",
        "Audio16Khz32KBitRateMonoMp3",
        "Audio48Khz192KBitRateMonoMp3",
    )
    formats = speechsdk.SpeechSynthesisOutputFormat
    return next((getattr(formats, name) for name in candidates if hasattr(formats, name)), None)


def synthesize_speech(
    text: str,
    output_path: str | Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: float = DEFAULT_RATE,
    speech_key: str | None = None,
    speech_region: str | None = None,
    _speechsdk=None,
) -> Path:
    """把文本合成为 MP3，并返回生成文件的绝对路径。

    ``speech_key`` 和 ``speech_region`` 为空时分别读取环境变量
    ``AZURE_SPEECH_KEY`` 和 ``AZURE_SPEECH_REGION``。调用成功前只写入
    ``.tmp`` 文件，成功后才替换正式输出，避免留下半截 MP3。
    """
    key = (speech_key or os.environ.get(AZURE_SPEECH_KEY_ENV, "")).strip()
    region = (speech_region or os.environ.get(AZURE_SPEECH_REGION_ENV, "")).strip()
    if not key:
        raise AzureTTSError(f"缺少 Azure Speech Key，请传入 speech_key 或设置 {AZURE_SPEECH_KEY_ENV}")
    if not region:
        raise AzureTTSError(
            f"缺少 Azure Speech Region，请传入 speech_region 或设置 {AZURE_SPEECH_REGION_ENV}"
        )

    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".mp3":
        target = target.with_suffix(".mp3")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    speechsdk = _speechsdk or _load_speech_sdk()
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    config.speech_synthesis_voice_name = resolve_voice(voice)
    output_format = _select_mp3_format(speechsdk)
    if output_format is not None:
        config.set_speech_synthesis_output_format(output_format)

    audio = speechsdk.audio.AudioOutputConfig(filename=str(temporary))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio)
    try:
        result = synthesizer.speak_ssml_async(build_ssml(text, voice, rate)).get()
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise AzureTTSError(f"Azure 语音合成请求失败：{type(exc).__name__}: {exc}") from exc
    finally:
        close = getattr(synthesizer, "close", None)
        if callable(close):
            close()

    time.sleep(0.05)
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = getattr(result, "cancellation_details", None)
        reason = getattr(details, "reason", "") if details else ""
        error = getattr(details, "error_details", "") if details else ""
        temporary.unlink(missing_ok=True)
        detail = " | ".join(str(item) for item in (reason, error) if item)
        raise AzureTTSError(f"Azure 语音合成失败：{result.reason}{(' | ' + detail) if detail else ''}")
    if not temporary.exists() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise AzureTTSError("Azure 返回成功，但没有生成有效音频文件")

    target.unlink(missing_ok=True)
    temporary.replace(target)
    return target


def synthesize_batch(
    jobs: Iterable[tuple[str, str | Path]],
    *,
    voice: str = DEFAULT_VOICE,
    rate: float = DEFAULT_RATE,
    max_workers: int = 4,
    speech_key: str | None = None,
    speech_region: str | None = None,
) -> list[tuple[str, Path | None, Exception | None]]:
    """并发合成多个 ``(文本, 输出路径)``，每项独立返回成功或错误。"""
    items = list(jobs)
    if not items:
        return []
    workers = max(1, min(int(max_workers), len(items), 8))
    results: list[tuple[str, Path | None, Exception | None] | None] = [None] * len(items)

    def run(index: int, text: str, path: str | Path):
        try:
            output = synthesize_speech(
                text,
                path,
                voice=voice,
                rate=rate,
                speech_key=speech_key,
                speech_region=speech_region,
            )
            results[index] = (str(path), output, None)
        except Exception as exc:
            results[index] = (str(path), None, exc)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="azure-tts") as pool:
        futures = [pool.submit(run, index, text, path) for index, (text, path) in enumerate(items)]
        for future in as_completed(futures):
            future.result()
    return [item for item in results if item is not None]
