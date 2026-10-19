from pathlib import Path
import requests
from app_config import groq_key

ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
LANGUAGE_CODES = {"中文": "zh", "英语": "en", "日语": "ja", "韩语": "ko", "西班牙语": "es", "法语": "fr", "德语": "de"}

def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def segments_to_srt(segments: list[dict]) -> str:
    blocks = []
    for index, segment in enumerate(segments, 1):
        text = str(segment.get("text", "")).strip()
        if text:
            blocks.append(f"{index}\n{_srt_time(segment['start'])} --> {_srt_time(segment['end'])}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")

def segments_to_text(segments: list[dict]) -> str:
    lines = [str(segment.get("text", "")).strip() for segment in segments]
    lines = [line for line in lines if line]
    return "\n".join(lines) + ("\n" if lines else "")

def transcribe_request_config(language: str) -> dict:
    return {"endpoint": ENDPOINT, "data": {"model": MODEL, "response_format": "verbose_json", "language": LANGUAGE_CODES.get(language, "zh"), "timestamp_granularities[]": "segment", "temperature": "0"}}

def transcribe(audio_path: str, key: str = "", language: str = "中文") -> list[dict]:
    key = key.strip() or groq_key()
    if not key.strip(): raise ValueError("请填写 Groq API Key")
    config = transcribe_request_config(language)
    headers={"Authorization":f"Bearer {key.strip()}"}
    with open(audio_path,"rb") as f:
        r=requests.post(config["endpoint"], headers=headers, data=config["data"], files={"file":(Path(audio_path).name,f,"audio/wav")}, timeout=180)
    if r.status_code == 401: raise RuntimeError("Groq API Key 无效或已失效")
    if r.status_code == 413: raise RuntimeError("音频文件超过 Groq 当前套餐的大小限制")
    r.raise_for_status(); data=r.json()
    items=data.get("segments") or data.get("data",{}).get("segments")
    if not isinstance(items,list): raise ValueError("ASR 返回中缺少 segments")
    return [{"id":i+1,"start":float(x["start"]),"end":float(x["end"]),"text":str(x["text"]).strip()} for i,x in enumerate(items)]
