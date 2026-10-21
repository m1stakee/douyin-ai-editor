from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Iterable
import re
import shutil
import subprocess
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from downloader import extract_share_url, extract_share_urls, validate_url
from app_config import henghengmao_key

DEFAULT_API_URL = "https://api.meowload.net/openapi/v1"
MAX_WORKERS = 16
DEFAULT_WORKER_LIMIT = 8
MAX_API_WORKERS = 5
DOWNLOAD_SEGMENTS = 4
SEGMENT_MIN_BYTES = 8 * 1024 * 1024
MAX_BATCH_MEDIA_CONNECTIONS = 24
_target_lock = Lock()
_reserved_targets: set[Path] = set()


class MediaUrlExpiredError(RuntimeError):
    pass


class IncompleteDownloadError(RuntimeError):
    pass


class DownloadStopped(RuntimeError):
    pass


class DownloadControl:
    """Thread-safe pause/resume control for one media download."""
    def __init__(self):
        self._running = Event()
        self._running.set()
        self._cancelled = Event()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()

    def checkpoint(self) -> None:
        while not self._running.wait(0.25):
            if self._cancelled.is_set():
                raise DownloadStopped("下载已停止")
        if self._cancelled.is_set():
            raise DownloadStopped("下载已停止")


@dataclass(frozen=True)
class DownloadSpec:
    source_url: str
    title: str
    media_url: str
    audio_url: str | None = None
    headers: dict | None = None


def safe_filename(name: str, fallback: str = "douyin_video") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")
    return (cleaned or fallback)[:120]


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_media_choice(payload: dict, quality: str = "推荐") -> dict:
    candidates = []
    for item in _walk(payload):
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("media_type", "")).lower()
        if media_type not in ("", "video"):
            continue
        variants = item.get("variants") if isinstance(item.get("variants"), list) else []
        for variant in variants:
            if isinstance(variant, dict) and variant.get("video_url"):
                candidates.append({"url": variant["video_url"], "audio_url": variant.get("audio_url"), "headers": item.get("headers", {}), "quality": variant.get("quality", 0), "default": variant.get("is_default", False)})
        if item.get("resource_url") and media_type == "video":
            candidates.append({"url": item["resource_url"], "headers": item.get("headers", {}), "quality": item.get("quality", 0), "default": True})
    if not candidates:
        raise RuntimeError("哼哼猫 API 未返回可下载的视频地址")
    if quality == "最高":
        return max(candidates, key=lambda x: x["quality"] or 0)
    if quality in ("1080P", "720P"):
        target = int(quality[:-1])
        return min(candidates, key=lambda x: abs((x["quality"] or target) - target))
    return next((x for x in candidates if x["default"]), max(candidates, key=lambda x: x["quality"] or 0))


def _session() -> requests.Session:
    retry = Retry(total=3, connect=3, read=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(("GET", "POST")), respect_retry_after_header=True)
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def resolve_video(input_text: str, api_key: str = "", api_url: str = DEFAULT_API_URL, quality: str = "推荐") -> DownloadSpec:
    key = api_key.strip() or henghengmao_key()
    if not key:
        raise ValueError("未配置哼哼猫 API Key，请在接口配置中填写")
    url = validate_url(extract_share_url(input_text))
    try:
        with _session() as session:
            response = session.post(api_url.rstrip("/") + "/extract/post", json={"url": url}, headers={"Authorization": f"Bearer {key}", "Accept-Language": "zh"}, timeout=(15, 60))
            if response.status_code == 401:
                raise RuntimeError("哼哼猫 API Key 无效或已失效")
            if response.status_code == 402:
                raise RuntimeError("哼哼猫 API 积分已用尽")
            response.raise_for_status()
            payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"哼哼猫 API 请求失败：{exc}") from exc
    except ValueError as exc:
        raise RuntimeError("哼哼猫 API 返回了无效 JSON") from exc
    choice = extract_media_choice(payload, quality)
    return DownloadSpec(url, safe_filename(payload.get("title") or payload.get("text"), "douyin_video"), choice["url"], choice.get("audio_url"), choice.get("headers") or {})


def _reserve_target(output_dir: Path, title: str) -> Path:
    with _target_lock:
        candidate = output_dir / f"{title}.mp4"
        number = 2
        while candidate.exists() or candidate in _reserved_targets:
            candidate = output_dir / f"{title} ({number}).mp4"
            number += 1
        _reserved_targets.add(candidate)
        return candidate


def _content_total(response: requests.Response, downloaded: int) -> int:
    content_range = response.headers.get("Content-Range", "")
    match = re.search(r"/(\d+)$", content_range)
    if match:
        return int(match.group(1))
    length = int(response.headers.get("Content-Length") or 0)
    return downloaded + length if response.status_code == 206 else length


def _range_size(url: str, headers: dict | None = None) -> int:
    request_headers = {"User-Agent": "DouyinAIEditor/1.0", "Accept-Encoding": "identity", **(headers or {}), "Range": "bytes=0-0"}
    try:
        with _session() as session, session.get(url, allow_redirects=True, stream=True, timeout=(15, 30), headers=request_headers) as response:
            if response.status_code in (401, 403, 410):
                raise MediaUrlExpiredError("媒体下载链接已失效")
            if response.status_code != 206:
                return 0
            match = re.match(r"bytes\s+0-0/(\d+)", response.headers.get("Content-Range", ""), re.I)
            return int(match.group(1)) if match else 0
    except MediaUrlExpiredError:
        raise
    except requests.RequestException:
        return 0


def _save_media_segmented(url: str, target: Path, total: int, headers: dict | None, on_progress: Callable[[int, int], None] | None, attempts: int, control: DownloadControl | None, segments: int = DOWNLOAD_SEGMENTS) -> None:
    """Download one range-capable media URL through resumable parallel byte ranges."""
    partial = target.with_name(f".{target.name}.part")
    segment_count = min(max(1, segments), max(1, total))
    step = (total + segment_count - 1) // segment_count
    parts = [partial.with_name(f"{partial.name}.{index}") for index in range(segment_count)]
    ranges = [(index * step, min(total - 1, (index + 1) * step - 1)) for index in range(segment_count)]
    progress_lock = Lock()

    def report():
        if on_progress:
            with progress_lock:
                on_progress(sum(path.stat().st_size for path in parts if path.exists()), total)

    def download_part(index: int):
        start, end = ranges[index]
        path = parts[index]
        expected = end - start + 1
        if path.exists() and path.stat().st_size > expected:
            path.unlink()
        last_error: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            if control:
                control.checkpoint()
            downloaded = path.stat().st_size if path.exists() else 0
            if downloaded == expected:
                report()
                return
            request_headers = {"User-Agent": "DouyinAIEditor/1.0", "Accept-Encoding": "identity", **(headers or {}), "Range": f"bytes={start + downloaded}-{end}"}
            try:
                with _session() as session, session.get(url, allow_redirects=True, stream=True, timeout=(15, 120), headers=request_headers) as response:
                    if response.status_code in (401, 403, 410):
                        raise MediaUrlExpiredError("媒体下载链接已失效")
                    if response.status_code != 206:
                        raise IncompleteDownloadError("服务器停止支持分片下载")
                    with path.open("ab") as handle:
                        for chunk in response.iter_content(1024 * 1024):
                            if control:
                                control.checkpoint()
                            if chunk:
                                handle.write(chunk)
                                downloaded += len(chunk)
                                report()
                if path.stat().st_size != expected:
                    raise IncompleteDownloadError(f"分片 {index + 1} 不完整：{path.stat().st_size} / {expected} 字节")
                return
            except MediaUrlExpiredError:
                raise
            except (requests.RequestException, OSError, IncompleteDownloadError) as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
        raise RuntimeError(f"分片 {index + 1} 重试 {attempts} 次后仍失败：{last_error}") from last_error

    report()
    with ThreadPoolExecutor(max_workers=segment_count, thread_name_prefix="media-range") as pool:
        futures = [pool.submit(download_part, index) for index in range(segment_count)]
        for future in as_completed(futures):
            future.result()
    with partial.open("wb") as output:
        for path in parts:
            with path.open("rb") as source:
                shutil.copyfileobj(source, output, 1024 * 1024)
    if partial.stat().st_size != total:
        raise IncompleteDownloadError(f"分片合并不完整：{partial.stat().st_size} / {total} 字节")
    partial.replace(target)
    for path in parts:
        path.unlink(missing_ok=True)
    if on_progress:
        on_progress(total, total)


def smart_segment_count(total: int, concurrent_downloads: int = 1) -> int:
    """Choose ranges from file size while keeping a batch near a sane connection budget."""
    if total < SEGMENT_MIN_BYTES:
        return 1
    fair_share = max(1, MAX_BATCH_MEDIA_CONNECTIONS // max(1, int(concurrent_downloads)))
    if total < 24 * 1024 * 1024:
        size_target = 2
    elif total < 96 * 1024 * 1024:
        size_target = 4
    else:
        size_target = 6
    return max(1, min(size_target, fair_share))


def _save_media(url: str, target: Path, headers: dict | None = None, on_progress: Callable[[int, int], None] | None = None, attempts: int = 5, control: DownloadControl | None = None, concurrent_downloads: int = 1) -> None:
    """Download with a stable partial file and HTTP Range resume support."""
    if target.exists():
        size = target.stat().st_size
        if on_progress:
            on_progress(size, size)
        return
    partial = target.with_name(f".{target.name}.part")
    if not partial.exists():
        total = _range_size(url, headers)
        segments = smart_segment_count(total, concurrent_downloads)
        if segments > 1:
            return _save_media_segmented(url, target, total, headers, on_progress, attempts, control, segments)
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        if control:
            control.checkpoint()
        downloaded = partial.stat().st_size if partial.exists() else 0
        request_headers = {"User-Agent": "DouyinAIEditor/1.0", "Accept-Encoding": "identity", **(headers or {})}
        if downloaded:
            request_headers["Range"] = f"bytes={downloaded}-"
        try:
            with _session() as session, session.get(url, allow_redirects=True, stream=True, timeout=(15, 120), headers=request_headers) as response:
                if response.status_code in (401, 403, 410):
                    raise MediaUrlExpiredError("媒体下载链接已失效")
                if response.status_code == 416 and downloaded:
                    total = _content_total(response, 0)
                    if total and downloaded == total:
                        partial.replace(target)
                        if on_progress:
                            on_progress(total, total)
                        return
                    partial.unlink(missing_ok=True)
                    raise IncompleteDownloadError("服务器拒绝断点位置，已重置临时文件")
                response.raise_for_status()
                append = bool(downloaded and response.status_code == 206)
                if not append:
                    downloaded = 0
                total = _content_total(response, downloaded)
                if on_progress:
                    on_progress(downloaded, total)
                with partial.open("ab" if append else "wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if control:
                            control.checkpoint()
                        if chunk:
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if on_progress:
                                on_progress(downloaded, total)
                actual = partial.stat().st_size
                if total and actual < total:
                    raise IncompleteDownloadError(f"连接提前断开：已下载 {actual} / {total} 字节")
            partial.replace(target)
            if on_progress:
                on_progress(target.stat().st_size, target.stat().st_size)
            return
        except MediaUrlExpiredError:
            raise
        except (requests.RequestException, OSError, IncompleteDownloadError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError(f"下载重试 {attempts} 次后仍失败：{last_error}") from last_error


def download_resolved(spec: DownloadSpec, output_dir: str, ffmpeg: str = "", on_progress: Callable[[float], None] | None = None, refresh: Callable[[], DownloadSpec] | None = None, control: DownloadControl | None = None, concurrent_downloads: int = 1) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = _reserve_target(out, spec.title)
    video_part = out / f".{target.name}.video.mp4"
    audio_part = out / f".{target.name}.audio.m4a"
    current = spec
    def report(offset: float, scale: float):
        return lambda downloaded, total: on_progress(min(1.0, offset + scale * (downloaded / total))) if on_progress and total else None
    try:
        for refresh_attempt in range(2):
            try:
                if current.audio_url:
                    if not ffmpeg:
                        raise ValueError("该清晰度的音视频分离，请先选择 ffmpeg.exe")
                    _save_media(current.media_url, video_part, current.headers, report(0.0, 0.5), control=control, concurrent_downloads=concurrent_downloads)
                    _save_media(current.audio_url, audio_part, current.headers, report(0.5, 0.5), control=control, concurrent_downloads=concurrent_downloads)
                    result = subprocess.run([ffmpeg, "-y", "-i", str(video_part), "-i", str(audio_part), "-c", "copy", str(target)], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    if result.returncode:
                        raise RuntimeError(result.stderr[-3000:] or "FFmpeg 合并音视频失败")
                else:
                    _save_media(current.media_url, target, current.headers, report(0.0, 1.0), control=control, concurrent_downloads=concurrent_downloads)
                break
            except MediaUrlExpiredError:
                if refresh_attempt or not refresh:
                    raise
                current = refresh()
        if on_progress:
            on_progress(1.0)
        return str(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if target.exists():
            for path in (video_part, audio_part, video_part.with_name(f".{video_part.name}.part"), audio_part.with_name(f".{audio_part.name}.part")):
                path.unlink(missing_ok=True)
        with _target_lock:
            _reserved_targets.discard(target)


def worker_count(item_count: int, limit: int = MAX_WORKERS) -> int:
    """Allocate one worker per item, bounded by the configured safety limit."""
    return min(MAX_WORKERS, max(1, int(limit)), max(1, int(item_count)))


def api_worker_count(item_count: int) -> int:
    """Limit resolver requests so a batch does not burst the extraction API."""
    return min(MAX_API_WORKERS, max(1, int(item_count)))


def run_with_fresh_thread_retries(operation: Callable[[], Any], retries: int = 3, prefix: str = "task") -> Any:
    """Run each attempt in a new one-shot executor and destroy it before retrying."""
    last_error: Exception | None = None
    for attempt in range(max(0, int(retries)) + 1):
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{prefix}-attempt-{attempt + 1}") as attempt_pool:
            future = attempt_pool.submit(operation)
            try:
                return future.result()
            except Exception as exc:
                last_error = exc
        if attempt < retries:
            time.sleep(min(3.0, 0.5 * (2 ** attempt)))
    raise last_error or RuntimeError("任务重试失败")


def download_videos(inputs: str | Iterable[str], output_dir: str, api_key: str = "", api_url: str = DEFAULT_API_URL, quality: str = "推荐", ffmpeg: str = "", download_workers: int = DEFAULT_WORKER_LIMIT, on_done: Callable[[int, str, str | None, Exception | None], None] | None = None, on_progress: Callable[[int, str, float], None] | None = None, controls: list[DownloadControl] | None = None) -> list[tuple[str, str | None, Exception | None]]:
    """Resolve every URL in its own API thread, then use the configured download pool."""
    urls = extract_share_urls(inputs) if isinstance(inputs, str) else list(dict.fromkeys(inputs))
    if not urls:
        raise ValueError("请至少输入一条抖音分享链接")
    results: list[tuple[str, str | None, Exception | None] | None] = [None] * len(urls)
    download_thread_count = worker_count(len(urls), download_workers)
    with (
        ThreadPoolExecutor(max_workers=api_worker_count(len(urls)), thread_name_prefix="douyin-api") as api_pool,
        ThreadPoolExecutor(max_workers=download_thread_count, thread_name_prefix="douyin-download") as download_pool,
    ):
        api_futures = {
            api_pool.submit(run_with_fresh_thread_retries, lambda url=url: resolve_video(url, api_key, api_url, quality), 3, f"douyin-api-{index + 1}"): (index, url)
            for index, url in enumerate(urls)
        }
        download_futures = {}
        for future in as_completed(api_futures):
            index, url = api_futures[future]
            try:
                spec = future.result()
                progress = (lambda value, index=index, url=url: on_progress(index, url, value)) if on_progress else None
                refresh = lambda url=url: resolve_video(url, api_key, api_url, quality)
                control = controls[index] if controls and index < len(controls) else None
                operation = lambda spec=spec, progress=progress, refresh=refresh, control=control: download_resolved(spec, output_dir, ffmpeg, progress, refresh, control, download_thread_count)
                download_futures[download_pool.submit(run_with_fresh_thread_retries, operation, 3, f"douyin-download-{index + 1}")] = (index, url)
            except Exception as exc:
                results[index] = (url, None, exc)
                if on_done:
                    on_done(index, url, None, exc)
        for future in as_completed(download_futures):
            index, url = download_futures[future]
            try:
                path, error = future.result(), None
            except Exception as exc:
                path, error = None, exc
            results[index] = (url, path, error)
            if on_done:
                on_done(index, url, path, error)
    return [result for result in results if result is not None]


def download_video(input_text: str, output_dir: str, api_key: str = "", api_url: str = DEFAULT_API_URL, quality: str = "推荐", ffmpeg: str = "") -> str:
    spec = resolve_video(input_text, api_key, api_url, quality)
    return download_resolved(spec, output_dir, ffmpeg, refresh=lambda: resolve_video(input_text, api_key, api_url, quality))
