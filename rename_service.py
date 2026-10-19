from pathlib import Path
import re

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}

def safe_stem(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")
    if not cleaned:
        raise ValueError("新文件名不能为空")
    return cleaned[:120]

def list_videos(folder: str | Path) -> list[Path]:
    root = Path(folder)
    return sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS), key=lambda p: p.name.lower())

def rename_media_bundle(video_path: str | Path, new_name: str) -> Path:
    video = Path(video_path)
    stem = safe_stem(new_name)
    target = video.with_name(stem + video.suffix.lower())
    sources = sorted((p for p in video.parent.iterdir() if p.is_file() and p.stem.casefold() == video.stem.casefold()), key=lambda p: (p != video, p.name.lower()))
    targets = [target.with_suffix(p.suffix) for p in sources]
    for destination in targets:
        if destination.exists() and destination not in sources:
            raise FileExistsError(f"目标文件已存在：{destination.name}")
    for source, destination in zip(sources, targets):
        if source != destination:
            source.rename(destination)
    return target
