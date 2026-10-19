from pathlib import Path
from typing import Any
import subprocess
import re
import requests
from downloader import extract_share_url, validate_url
from app_config import henghengmao_key

DEFAULT_API_URL = "https://api.meowload.net/openapi/v1"

def safe_filename(name: str, fallback: str = "douyin_video") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")
    return (cleaned or fallback)[:120]

def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from _walk(child)
    elif isinstance(value, list):
        for child in value: yield from _walk(child)

def extract_media_choice(payload: dict, quality: str = "推荐") -> dict:
    candidates = []
    for item in _walk(payload):
        if not isinstance(item, dict): continue
        media_type = str(item.get("media_type", "")).lower()
        if media_type not in ("", "video"): continue
        variants = item.get("variants") if isinstance(item.get("variants"), list) else []
        for variant in variants:
            if isinstance(variant, dict) and variant.get("video_url"):
                candidates.append({"url": variant["video_url"], "audio_url": variant.get("audio_url"), "headers": item.get("headers", {}), "quality": variant.get("quality", 0), "default": variant.get("is_default", False)})
        if item.get("resource_url") and media_type == "video":
            candidates.append({"url": item["resource_url"], "headers": item.get("headers", {}), "quality": item.get("quality", 0), "default": True})
    if not candidates: raise RuntimeError("哼哼猫 API 未返回可下载的视频地址")
    if quality == "最高": chosen = max(candidates, key=lambda x: x["quality"] or 0)
    elif quality in ("1080P", "720P"):
        target = int(quality[:-1]); chosen = min(candidates, key=lambda x: abs((x["quality"] or target) - target))
    else: chosen = next((x for x in candidates if x["default"]), max(candidates, key=lambda x: x["quality"] or 0))
    return chosen

def _save_media(url: str, target: Path, headers: dict | None = None) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    with requests.get(url, allow_redirects=True, stream=True, timeout=120, headers={"User-Agent": "DouyinAIEditor/1.0", **(headers or {})}) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk: handle.write(chunk)
    partial.replace(target)

def download_video(input_text: str, output_dir: str, api_key: str = "", api_url: str = DEFAULT_API_URL, quality: str = "推荐", ffmpeg: str = "") -> str:
    api_key = api_key.strip() or henghengmao_key()
    if not api_key: raise ValueError("未配置哼哼猫 API Key，请创建 credentials.local.json")
    url = validate_url(extract_share_url(input_text))
    try:
        response = requests.post(api_url.rstrip("/") + "/extract/post", json={"url": url}, headers={"Authorization": f"Bearer {api_key.strip()}", "Accept-Language": "zh"}, timeout=60)
        if response.status_code == 401: raise RuntimeError("哼哼猫 API Key 无效或已失效")
        if response.status_code == 402: raise RuntimeError("哼哼猫 API 积分已用尽")
        response.raise_for_status(); payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"哼哼猫 API 请求失败：{exc}") from exc
    choice = extract_media_choice(payload, quality)
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    base_name = safe_filename(payload.get("title") or payload.get("text"), "douyin_video")
    target = out / f"{base_name}.mp4"
    if choice.get("audio_url"):
        if not ffmpeg: raise ValueError("该清晰度的音视频分离，请先选择 ffmpeg.exe")
        video_part, audio_part = out / "source-video.mp4", out / "source-audio.m4a"
        _save_media(choice["url"], video_part, choice.get("headers")); _save_media(choice["audio_url"], audio_part, choice.get("headers"))
        result = subprocess.run([ffmpeg, "-y", "-i", str(video_part), "-i", str(audio_part), "-c", "copy", str(target)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode: raise RuntimeError(result.stderr[-3000:] or "FFmpeg 合并音视频失败")
        video_part.unlink(missing_ok=True); audio_part.unlink(missing_ok=True)
    else: _save_media(choice["url"], target, choice.get("headers"))
    return str(target)
