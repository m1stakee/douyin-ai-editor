"""Workflow adapters shared by the independent Qt client pages."""
from pathlib import Path
import shutil

import ai
import asr
import media
import rename_service
import voicevox_service
from rewrite_source import read_rewrite_source
from rewrite_batch_service import immediate_retry
from text_io import read_text, write_text

STEPS = {'download':'1_下载视频', 'transcribe':'2_文案与SRT', 'answers':'3_字幕剪辑', 'rewrite':'4_AI改写', 'voice':'5_语音转出', 'library':'6_资源库'}
DEFAULT_URL = 'https://new-api.aicarb.com/v1'
DEFAULT_MODEL = 'gpt-6.1-sol'


class Workflow:
    def __init__(self, settings):
        self.settings = dict(settings)

    def directory(self, kind):
        root = self.settings.get('output_directory', '').strip()
        if not root:
            raise ValueError('请先选择输出目录')
        path = Path(root).expanduser() / STEPS[kind]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def process(self, kind, source, *, prompt='', status=None, output=None, provider='newapi'):
        source = Path(source)
        settings = self.settings
        report = status or (lambda _: None)
        target = Path(output).expanduser() if output else self.directory(kind)
        target.mkdir(parents=True, exist_ok=True)
        url = settings.get('llm_base_url') or DEFAULT_URL
        key = settings.get('llm_key', '')
        model = settings.get('llm_model') or DEFAULT_MODEL
        if kind == 'transcribe':
            if not key.strip() or not settings.get('dashscope_api_key','').strip():
                raise ValueError('请配置 New API Key 和临时 OSS 上传 Key')
            ffmpeg = asr.resolve_ffmpeg()
            with asr.prepared_asr_audio(str(source), ffmpeg, report) as audio:
                segments = asr.transcribe(audio, upload_key=settings.get('dashscope_api_key',''), newapi_base_url=url, newapi_key=key, audio_duration=media.probe_duration(ffmpeg,str(source)), language=settings.get('source_lang','中文'), on_status=report)
            _, srt, _ = asr.write_transcript_outputs(target, rename_service.safe_stem(source.stem), segments)
            return srt
        if kind == 'rewrite':
            if not prompt.strip():
                raise ValueError('请填写改写提示词')
            text = read_rewrite_source(source)
            if provider == 'doubao':
                url = 'https://ark.cn-beijing.volces.com/api/v3'
                key = settings.get('ark_api_key','')
                model = settings.get('qt_doubao_model','doubao-seed-2-1-pro-260915')
            rewritten = immediate_retry(lambda: ai.rewrite_text(text, prompt, key, model, url, None if provider=='doubao' else 'low'), max_attempts=3, on_retry=lambda attempt,total: report(f'重试中 {attempt}/{total}'))
            # Retries reuse the same path, avoiding duplicate output files.
            destination = target / (rename_service.safe_stem(source.stem) + '_改写.txt')
            write_text(destination, rewritten + '\n')
            return destination
        if kind == 'answers':
            if not key.strip():
                raise ValueError('请配置 New API Key')
            video_folder = self.directory('download')
            lookup = {rename_service.safe_stem(p.stem).casefold():p for p in rename_service.list_videos(video_folder)}
            video = lookup.get(source.stem.casefold())
            if not video:
                raise ValueError('第一步下载目录缺少同名视频')
            raw = read_text(source)
            cues = voicevox_service.parse_srt(raw)
            duration = media.probe_duration(asr.resolve_ffmpeg(), str(video))
            ranges = ai.srt_deletion_plan(cues,duration,url,key,model,'low',srt_text=raw,prompt_text=prompt)
            try:
                plan = media.build_srt_cut_plan(cues,duration,ranges)
            except ValueError as exc:
                ranges = ai.srt_deletion_plan(cues,duration,url,key,model,'low',str(exc),raw,prompt)
                plan = media.build_srt_cut_plan(cues,duration,ranges)
            destination = target / f'{video.stem}的答案1.txt'
            media.write_cut_plan_result(cues,plan,str(destination))
            for item in (video,source):
                if item.resolve() != (target/item.name).resolve():
                    shutil.copy2(item,target/item.name)
            return destination
        raise ValueError('未知任务：' + kind)


def copy_library(video_dir, subtitle_dir, audio_dir, output):
    video_dir, subtitle_dir, audio_dir, output = map(Path, (video_dir,subtitle_dir,audio_dir,output))
    if not all(p.is_dir() for p in (video_dir,subtitle_dir,audio_dir)):
        raise ValueError('视频、字幕和语音目录必须存在')
    mappings = [
        {p.stem:p for p in video_dir.iterdir() if p.is_file() and p.suffix.lower() in {'.mp4','.mov','.mkv','.webm','.m4v'}},
        {p.stem:p for p in subtitle_dir.glob('*.srt')},
        {p.stem:p for p in audio_dir.iterdir() if p.is_file() and p.suffix.lower() in {'.mp3','.wav','.m4a','.flac'}},
    ]
    complete = set(mappings[0]) & set(mappings[1]) & set(mappings[2])
    missing = sorted((set(mappings[0]) | set(mappings[1]) | set(mappings[2])) - complete)
    output.mkdir(parents=True,exist_ok=True)
    for stem in sorted(complete):
        for mapping in mappings:
            source = mapping[stem]
            if source.resolve() != (output/source.name).resolve():
                shutil.copy2(source,output/source.name)
    return len(complete), missing
