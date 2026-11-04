"""MiniMax T2A v2 adapter for the shared VideoFlow audio/SRT pipeline."""
from __future__ import annotations
import binascii
import json
import wave
from pathlib import Path
import requests

DEFAULT_BASE_URL = 'https://api.minimax.cn'
DEFAULT_MODEL = 'speech-2.8-hd'
DEFAULT_VOICE = 'male-qn-qingse'

class MiniMaxTTSError(RuntimeError):
    pass

def _url(base_url, path):
    return str(base_url or DEFAULT_BASE_URL).rstrip('/') + path

def _check(payload):
    base = payload.get('base_resp') or {}
    if int(base.get('status_code', 0) or 0) != 0:
        raise MiniMaxTTSError(base.get('status_msg') or f"MiniMax API error {base.get('status_code')}")

def synthesize_speech(text, output_path, *, api_key, base_url=DEFAULT_BASE_URL,
                      model=DEFAULT_MODEL, voice_id=DEFAULT_VOICE, speed=1.0,
                      volume=1.0, pitch=0, timeout=180):
    if not str(api_key or '').strip(): raise ValueError('MiniMax API Key 不能为空')
    text = str(text or '').strip()
    if not text: raise ValueError('待转语音文本不能为空')
    if not 0.5 <= float(speed) <= 2: raise ValueError('MiniMax 语速必须在 0.5 到 2 之间')
    if not 0 < float(volume) <= 10: raise ValueError('MiniMax 音量必须大于 0 且不超过 10')
    if not -12 <= int(pitch) <= 12: raise ValueError('MiniMax 音调必须在 -12 到 12 之间')
    payload = {'model': model, 'text': text, 'stream': False,
               'voice_setting': {'voice_id': voice_id, 'speed': float(speed), 'vol': float(volume), 'pitch': int(pitch)},
               'audio_setting': {'sample_rate': 24000, 'bitrate': 128000, 'format': 'pcm', 'channel': 1},
               'output_format': 'hex'}
    try:
        response = requests.post(_url(base_url, '/v1/t2a_v2'), headers={'Authorization': 'Bearer ' + str(api_key).strip(), 'Content-Type': 'application/json'}, json=payload, timeout=timeout)
        response.raise_for_status(); data = response.json()
    except requests.RequestException as exc:
        raise MiniMaxTTSError(f'MiniMax 请求失败：{exc}') from exc
    except (ValueError, TypeError) as exc:
        raise MiniMaxTTSError('MiniMax 返回不是有效 JSON') from exc
    _check(data)
    audio = ((data.get('data') or {}).get('audio') or '')
    try: raw = binascii.unhexlify(audio)
    except (binascii.Error, ValueError) as exc: raise MiniMaxTTSError('MiniMax 音频数据不是有效 hex') from exc
    if not raw: raise MiniMaxTTSError('MiniMax 未返回音频数据')
    target = Path(output_path).expanduser().resolve().with_suffix('.wav'); target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp.wav')
    try:
        with wave.open(str(temp), 'wb') as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000); wf.writeframes(raw)
        temp.replace(target)
    finally: temp.unlink(missing_ok=True)
    return target

def list_voices(api_key, base_url=DEFAULT_BASE_URL, timeout=60):
    if not str(api_key or '').strip(): raise ValueError('MiniMax API Key 不能为空')
    try:
        response = requests.post(_url(base_url, '/v1/get_voice'), headers={'Authorization': 'Bearer ' + str(api_key).strip(), 'Content-Type': 'application/json'}, json={'voice_type': 'all'}, timeout=timeout)
        response.raise_for_status(); data = response.json()
    except requests.RequestException as exc: raise MiniMaxTTSError(f'MiniMax 音色请求失败：{exc}') from exc
    _check(data)
    voices=[]
    for group in ('system_voice', 'voice_cloning', 'voice_generation'):
        for item in data.get(group) or []:
            if item.get('voice_id'): voices.append({'voice_id': item['voice_id'], 'voice_name': item.get('voice_name') or item['voice_id'], 'type': group})
    return voices

def synthesize_script_files(source_paths, output_directory, *, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, voice_id=DEFAULT_VOICE, speed=1.0, volume=1.0, pitch=0, pause_seconds=0.3, output_format='mp3', ffmpeg_path=None, on_progress=None):
    import voicevox_service
    def sentence_audio(text, output, **_kwargs):
        return synthesize_speech(text, output, api_key=api_key, base_url=base_url, model=model, voice_id=voice_id, speed=speed, volume=volume, pitch=pitch)
    return voicevox_service.synthesize_script_files(source_paths, output_directory, style_id=0, synthesize_sentence=sentence_audio, pause_seconds=pause_seconds, output_format=output_format, ffmpeg_path=ffmpeg_path, on_progress=on_progress)
