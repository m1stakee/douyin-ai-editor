import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qt_workflow_service import Workflow


class TestQtWorkflow(unittest.TestCase):
    def test_rewrite_retries_and_keeps_output_stable(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'sample.txt'
            source.write_text('source', encoding='utf-8')
            workflow = Workflow({'output_directory': folder, 'llm_key': 'test', 'llm_model': 'model', 'llm_base_url': 'https://example.com/v1'})
            with patch('qt_workflow_service.ai.rewrite_text', side_effect=[ValueError('retry'), 'rewritten']):
                first = workflow.process('rewrite', source, prompt='prompt')
            self.assertEqual(Path(first).read_text(encoding='utf-8').strip(), 'rewritten')
            with patch('qt_workflow_service.ai.rewrite_text', return_value='second'):
                second = workflow.process('rewrite', source, prompt='prompt')
            self.assertEqual(first, second)

    def test_transcribe_uses_shared_newapi_config_and_utf8_exports(self):
        from contextlib import contextmanager
        @contextmanager
        def audio(*args, **kwargs):
            yield 'audio.mp3'
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'sample.mp4'; source.touch()
            workflow = Workflow({'output_directory': folder, 'llm_key': 'test-key', 'llm_base_url': 'https://example.com/v1', 'dashscope_api_key': 'upload-key'})
            with patch('qt_workflow_service.asr.resolve_ffmpeg', return_value='ffmpeg'), patch('qt_workflow_service.asr.prepared_asr_audio', audio), patch('qt_workflow_service.media.probe_duration', return_value=2), patch('qt_workflow_service.asr.transcribe', return_value=[{'start':0,'end':1,'text':'hello'}]) as transcribe:
                result = workflow.process('transcribe', source)
            self.assertEqual(transcribe.call_args.kwargs['newapi_key'], 'test-key')
            self.assertTrue(Path(result).is_file())
            self.assertEqual(Path(result).with_suffix('.txt').read_bytes(), b'hello\n')

    def test_library_groups_only_matching_files(self):
        from qt_workflow_service import copy_library
        with tempfile.TemporaryDirectory() as folder:
            dirs = [Path(folder)/s for s in ('video','srt','audio','out')]
            for d in dirs: d.mkdir()
            for d, ext in zip(dirs, ('mp4','srt','mp3')): (d/f'a.{ext}').write_bytes(b'data')
            (dirs[0]/'missing.mp4').touch()
            count, missing = copy_library(*dirs)
            self.assertEqual(count,1)
            self.assertEqual(missing,['missing'])
            self.assertEqual(len(list(dirs[3].iterdir())),3)
