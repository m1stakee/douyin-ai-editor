import json
import subprocess
import sys
from pathlib import Path

CUT_END_ADVANCE_SECONDS = 1.0
CUT_TRANSITION_SECONDS = 0.33


def _cut_transition_durations(plan: dict) -> list[float]:
    durations=[]
    elapsed=plan["kept"][0][1]-plan["kept"][0][0] if plan.get("kept") else 0.0
    for start,end in plan.get("kept",[])[1:]:
        clip_duration=end-start
        fade=min(CUT_TRANSITION_SECONDS,max(0.02,clip_duration/4),max(0.02,elapsed/4))
        durations.append(fade); elapsed+=clip_duration-fade
    return durations

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


def build_srt_cut_plan(cues, duration: float, deletion_ranges=None) -> dict:
    """Validate model-selected whole-cue deletion ranges and build media intervals."""
    if len(cues) < 9:
        raise ValueError("SRT 至少需要 9 条字幕，才能满足至少 3 处、每处 3 条的删除规则")
    if duration <= 0:
        raise ValueError("视频时长无效")
    n = len(cues)
    if deletion_ranges is None:
        raise ValueError("缺少模型生成的字幕删除范围")
    blocks=[]
    for item in deletion_ranges:
        try: start=int(item["start"]); end=int(item["end"])
        except (KeyError, TypeError, ValueError): raise ValueError("字幕删除范围格式无效")
        if start < 1 or end > n or end < start or end-start+1 < 3:
            raise ValueError(f"删除范围 {start}~{end} 无效；每处必须至少连续 3 条字幕")
        blocks.append(list(range(start,end+1)))
    blocks.sort(key=lambda b:b[0])
    if len(blocks) < 3: raise ValueError("整个视频至少需要 3 处删除")
    if any(left[-1] >= right[0]-1 for left,right in zip(blocks,blocks[1:])):
        raise ValueError("删除范围不能重叠或相邻；相邻范围应合并为一处")
    # Convert cue-index blocks to media intervals and take the complement.
    deleted = []
    for block in blocks:
        start = cues[block[0] - 1].start
        original_end = min(duration, cues[block[-1] - 1].end)
        end = original_end - CUT_END_ADVANCE_SECONDS
        if end <= start:
            raise ValueError(f"删除范围 {block[0]}~{block[-1]} 时长不足，结束点提前 1 秒后无法剪辑")
        deleted.append((start, end, block[0], block[-1]))
    deleted.sort()
    kept = []
    cursor = 0.0
    for start, end, _, _ in deleted:
        if start > cursor + 0.01: kept.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.01: kept.append((cursor, duration))
    kept_seconds = sum(end - start for start, end in kept)
    ratio = kept_seconds / duration
    if not (0.60 <= ratio <= 0.80):
        raise ValueError(f"按字幕整段删除后保留比例为 {ratio:.1%}，无法达到 60%~80%")
    return {"duration": duration, "deleted": deleted, "kept": kept, "kept_seconds": kept_seconds, "deleted_seconds": duration - kept_seconds}


def suggest_srt_deletion_ranges(cues, duration: float) -> list[dict]:
    """Pick three spaced, low-information-looking cue blocks as a safe default."""
    n=len(cues)
    if n < 9: raise ValueError("SRT 至少需要 9 条字幕")
    spans=[]
    for center in (round(n*.25), round(n*.52), round(n*.75)):
        start=max(2,min(n-3,center-1)); spans.append({"start":start,"end":start+2})
    return spans


def execute_srt_cut(ffmpeg: str, video: str, plan: dict, output: str) -> None:
    """Cut retained intervals and join them with a short fade to suppress boundary flashes."""
    clips, filters = [], []
    transitions = _cut_transition_durations(plan)
    for i, (start, end) in enumerate(plan["kept"]):
        filters.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},settb=AVTB,fps=30,setpts=PTS-STARTPTS[v{i}]")
        filters.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=N/SR/TB[a{i}]")
        clips.append(f"[v{i}][a{i}]")
    if not clips:
        raise ValueError("没有可保留的视频片段")
    if len(clips) == 1:
        filters.append("[v0]setpts=PTS-STARTPTS[outv]")
        filters.append("[a0]aresample=async=1:first_pts=0[outa]")
    else:
        current_v, current_a = "v0", "a0"
        elapsed = plan["kept"][0][1] - plan["kept"][0][0]
        for i in range(1, len(clips)):
            clip_duration = plan["kept"][i][1] - plan["kept"][i][0]
            fade = transitions[i-1]
            next_v, next_a = f"xfv{i}", f"xfa{i}"
            offset = max(0.0, elapsed - fade)
            filters.append(f"[{current_v}][v{i}]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[{next_v}]")
            filters.append(f"[{current_a}][a{i}]acrossfade=d={fade:.3f}:curve1=tri:curve2=tri[{next_a}]")
            current_v, current_a = next_v, next_a
            elapsed += clip_duration - fade
        filters.append(f"[{current_v}]setpts=PTS-STARTPTS[outv]")
        filters.append(f"[{current_a}]aresample=async=1:first_pts=0[outa]")
    run_ffmpeg(ffmpeg, ["-y", "-fflags", "+genpts", "-i", video, "-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-fps_mode", "cfr", "-c:a", "aac", "-pix_fmt", "yuv420p", "-avoid_negative_ts", "make_zero", "-start_at_zero", "-movflags", "+faststart", "-shortest", output])


def write_cut_subtitles(cues, plan: dict, srt_output: str, text_output: str) -> None:
    """Write a re-timed SRT and plain text for the retained subtitle cues."""
    kept = plan["kept"]
    rows = []
    deleted = sorted(plan["deleted"])
    for cue in cues:
        kept_index = next((i for i,(start,end) in enumerate(kept) if cue.start >= start - 0.01 and cue.end <= end + 0.01), None)
        if kept_index is None:
            continue
        removed_before = sum(end - start for start, end, _, _ in deleted if end <= cue.start)
        overlap_before = sum(_cut_transition_durations(plan)[:kept_index])
        new_start = max(0.0, cue.start - removed_before - overlap_before)
        new_end = max(new_start + 0.001, cue.end - removed_before - overlap_before)
        rows.append((new_start, new_end, cue.text))
    def stamp(seconds: float) -> str:
        millis = max(0, round(seconds * 1000)); hours, millis = divmod(millis, 3600000); minutes, millis = divmod(millis, 60000); secs, millis = divmod(millis, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    blocks = [f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}" for i, (start, end, text) in enumerate(rows, 1)]
    Path(srt_output).write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8-sig")
    Path(text_output).write_text("\n".join(text for _, _, text in rows) + ("\n" if rows else ""), encoding="utf-8-sig")
