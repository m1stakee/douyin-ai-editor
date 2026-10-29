from pathlib import Path

import voicevox_service
from text_io import read_text


SUPPORTED_REWRITE_EXTENSIONS = {".txt", ".srt"}


def read_rewrite_source(path: str | Path) -> str:
    """Load plain copy or extract only subtitle copy from an SRT file."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_REWRITE_EXTENSIONS:
        raise ValueError("仅支持 TXT 或 SRT 文件")
    raw = read_text(source)
    if suffix == ".txt":
        return raw.strip()
    cues = voicevox_service.parse_srt(raw)
    text = "\n".join(cue.text.strip() for cue in cues if cue.text.strip()).strip()
    if not text:
        raise ValueError("SRT 中没有可用的字幕文字")
    return text
