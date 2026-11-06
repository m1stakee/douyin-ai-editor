import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import requests
import edge_tts_access
import edge_tts_service


class TestEdgeAccess(unittest.TestCase):
    def test_fixed_voice_preview_does_not_call_license_server(self):
        with patch.object(edge_tts_access, 'verify_key') as verify, patch.object(edge_tts_service, '_synthesize_speech') as synth:
            edge_tts_service.preview_speech('out.mp3', voice='en-US-JennyNeural')
            verify.assert_not_called()
            self.assertIn('voice preview', synth.call_args.args[0])

    def test_empty_or_failed_validation_never_calls_synthesis(self):
        with patch.object(edge_tts_service, '_synthesize_speech') as synth:
            with self.assertRaises(PermissionError): edge_tts_service.synthesize_speech('Hello', 'out.mp3')
            synth.assert_not_called()
        with patch.object(edge_tts_access, 'verify_key', return_value=(False, 'disabled')), patch.object(edge_tts_service, '_synthesize_speech') as synth:
            with self.assertRaises(PermissionError): edge_tts_service.synthesize_speech('Hello', 'out.mp3', license_key='ET-test')
            synth.assert_not_called()

    def test_validation_is_fresh_for_each_preview_or_batch(self):
        with patch.object(edge_tts_access, 'verify_key', return_value=(True, 'OK')) as verify, patch.object(edge_tts_service, '_synthesize_speech', return_value=('out', [])):
            edge_tts_service.synthesize_speech('Hello', 'out.mp3', license_key='ET-test')
            edge_tts_service.synthesize_speech('Hello', 'out.mp3', license_key='ET-test')
            self.assertEqual(verify.call_count, 2)
        with patch.object(edge_tts_access, 'verify_key', return_value=(False, 'expired')):
            with self.assertRaises(PermissionError): edge_tts_service.synthesize_script_files([], '.', license_key='ET-test')

    def test_endpoint_and_network_failure_are_fail_closed(self):
        response = Mock(); response.json.return_value = {'valid': True, 'message': 'OK'}
        with patch.object(edge_tts_access.requests, 'post', return_value=response) as post:
            self.assertTrue(edge_tts_access.verify_key('ET-test')[0])
            self.assertTrue(post.call_args.args[0].endswith('/api/edge-tts/verify'))
        with patch.object(edge_tts_access.requests, 'post', side_effect=requests.Timeout):
            self.assertFalse(edge_tts_access.verify_key('ET-test')[0])
        response.json.return_value = {'valid': 'true'}
        with patch.object(edge_tts_access.requests, 'post', return_value=response):
            self.assertFalse(edge_tts_access.verify_key('ET-test')[0])
