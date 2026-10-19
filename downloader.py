import re
from urllib.parse import urlparse

DOUYIN_RE = re.compile(r"https?://(?:v\.douyin\.com|www\.douyin\.com|douyin\.com)/[^\s]+", re.I)

def extract_share_url(text: str) -> str:
    candidates = extract_share_urls(text)
    if not candidates:
        raise ValueError("未找到抖音分享链接")
    return candidates[0].rstrip("，。,.\"'）)")

def extract_share_urls(text: str) -> list[str]:
    found = [url.rstrip("，。,.\"'）)") for url in DOUYIN_RE.findall(text or "")]
    return list(dict.fromkeys(found))

def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("链接必须使用 http 或 https")
    return url
