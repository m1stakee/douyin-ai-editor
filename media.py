import json
import subprocess
import sys
from pathlib import Path

def run_ffmpeg(ffmpeg: str, args: list[str]) -> None:
    p = subprocess.run([ffmpeg, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if p.returncode:
        raise RuntimeError(p.stderr[-4000:] or "FFmpeg 执行失败")

def extract_audio(ffmpeg: str, video: str, wav: str) -> None:
    run_ffmpeg(ffmpeg, ["-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])

def probe_duration(ffmpeg: str, video: str) -> float:
    p = subprocess.run([ffmpeg, "-i", video], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not m: raise RuntimeError("无法读取视频时长")
    return int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))

def fixed_scenes(duration: float, chunk: float = 5.0) -> list[dict]:
    scenes=[]; start=0.0; i=1
    while start < duration:
        end=min(duration, start+chunk)
        scenes.append({"id":i,"start":round(start,3),"end":round(end,3),"description":f"视频片段 {i}"})
        start=end; i+=1
    return scenes

def execute_plan(ffmpeg: str, video: str, plan: dict, output: str) -> None:
    clips=[]; filters=[]
    for i, item in enumerate(plan["timeline"]):
        scene=item["scene"]
        speed=float(item.get("speed",1.0))
        label=f"v{i}"
        filters.append(f"[0:v]trim=start={scene['start']}:end={scene['end']},setpts=(PTS-STARTPTS)/{speed}[{label}v]")
        filters.append(f"[0:a]atrim=start={scene['start']}:end={scene['end']},asetpts=PTS-STARTPTS,atempo={speed}[{label}a]")
        clips.append(f"[{label}v][{label}a]")
    if not clips: raise ValueError("剪辑计划没有可执行片段")
    filters.append("".join(clips)+f"concat=n={len(clips)}:v=1:a=1[outv][outa]")
    run_ffmpeg(ffmpeg, ["-y","-i",video,"-filter_complex",";".join(filters),"-map","[outv]","-map","[outa]","-c:v","libx264","-c:a","aac","-pix_fmt","yuv420p","-shortest",output])
