"""Edge voice discovery and filtering, independent of the UI toolkit."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

import edge_tts
from app_config import settings_path


def filter_voices(voices, *, language='', region='', gender='', favorites_only=False, favorites=()):
    result = []
    for voice in voices:
        parts = voice['Locale'].split('-')
        if language and parts[0] != language:
            continue
        if region and parts[-1] != region:
            continue
        if gender and voice['Gender'] != gender:
            continue
        if favorites_only and voice['ShortName'] not in favorites:
            continue
        result.append(voice)
    return result


def _valid_voices(value):
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, dict) and all(isinstance(item.get(key), str) and item[key] for key in ('ShortName', 'Locale', 'Gender'))
        for item in value
    )


def load_voices(cache_path=None, *, refresh=False, fetch=None):
    path = Path(cache_path) if cache_path else settings_path().with_name('edge-voices.json')
    cached = None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if _valid_voices(value):
            cached = value
    except (OSError, ValueError):
        pass
    if cached and not refresh:
        return cached
    try:
        voices = asyncio.run((fetch or edge_tts.list_voices)())
        if not _valid_voices(voices):
            raise ValueError('Edge TTS 未返回有效音色列表')
    except Exception:
        if cached:
            return cached
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(voices, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return voices
