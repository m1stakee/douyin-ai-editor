import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import minimax_tts_service as mm


class Resp:
    def __init__(self, payload, status=200): self.payload, self.status_code = payload, status
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError('http')
    def json(self): return self.payload


class TestMiniMax(unittest.TestCase):
    def test_batch_audio_and_srt_have_measured_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)/'demo.txt'; source.write_text('第一句。第二句。', encoding='utf-8')
            response = Resp({'data': {'audio': ('0000'*24000)}, 'base_resp': {'status_code': 0}})
            with patch.object(mm.requests, 'post', return_value=response) as post:
                result = mm.synthesize_script_files([source], Path(d)/'out', api_key='k', output_format='wav', pause_seconds=.3)
            self.assertIsNone(result[0]['error'])
            self.assertEqual(post.call_count, 2)
            with wave.open(str(result[0]['audio'])) as wf:
                self.assertAlmostEqual(wf.getnframes()/wf.getframerate(), 2.3)
            self.assertIn('00:00:01,300', result[0]['srt'].read_text(encoding='utf-8'))

    def test_request_decodes_hex_and_checks_base_resp(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d).resolve() / 'a.wav'
            response = Resp({'data': {'audio': '0001ff00'}, 'base_resp': {'status_code': 0}})
            with patch.object(mm.requests, 'post', return_value=response) as post:
                result = mm.synthesize_speech('你好', target, api_key='k', base_url='https://api.minimax.cn', model='speech-2.8-hd', voice_id='male-qn-qingse')
            self.assertEqual(result, target)
            with wave.open(str(target)) as audio:
                self.assertEqual(audio.readframes(2), b'\x00\x01\xff\x00')
                self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer k')
            self.assertEqual(post.call_args.kwargs['json']['audio_setting']['format'], 'pcm')

    def test_missing_key_and_api_error(self):
        with self.assertRaises(ValueError): mm.synthesize_speech('x', 'a.wav', api_key='')
        response = Resp({'base_resp': {'status_code': 1004, 'status_msg': 'bad key'}})
        with patch.object(mm.requests, 'post', return_value=response):
            with self.assertRaises(mm.MiniMaxTTSError): mm.synthesize_speech('x', 'a.wav', api_key='k')

    def test_list_voices(self):
        response = Resp({'system_voice': [{'voice_id': 'v', 'voice_name': 'V'}], 'base_resp': {'status_code': 0}})
        with patch.object(mm.requests, 'post', return_value=response):
            voices = mm.list_voices('k', 'https://api.minimax.cn')
        self.assertEqual(voices[0]['voice_id'], 'v')

