import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
import local_logger as logs


class LocalLoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'logs'
        self.patch = patch.object(logs, 'log_directory', return_value=self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.reset()
        self.addCleanup(self.reset)

    def reset(self):
        logger = logging.getLogger('videoflow')
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def contents(self):
        return (self.directory / 'videoflow.log').read_text(encoding='utf-8')

    def test_request_failure_records_status_body_context_and_redacts_traceback(self):
        response = requests.Response()
        response.status_code = 429
        response._content = b'{"error":{"message":"quota exhausted opaque-secret"}}'
        with logs.context(batch='batch88', item=42):
            logs.request(Mock(return_value=response), 'https://example.com/v1/chat/completions?token=query-secret',
                         headers={'Authorization': 'Bearer opaque-secret'}, json={'model':'demo','messages':[{'content':'PRIVATE COPY'}]})
            try:
                raise RuntimeError('opaque-secret')
            except RuntimeError:
                logs.error('failed', exc_info=True)
        content = self.contents()
        for expected in ('batch88', '42', '429', 'quota exhausted', 'Traceback', 'RuntimeError'):
            self.assertIn(expected, content)
        for private in ('opaque-secret', 'query-secret', 'PRIVATE COPY'):
            self.assertNotIn(private, content)

    def test_success_does_not_log_response_copy_and_keeps_numeric_formatting(self):
        response = requests.Response(); response.status_code = 200; response._content = b'PRIVATE RESULT'
        self.assertIs(logs.request(Mock(return_value=response), 'https://example.com'), response)
        logs.info('elapsed=%.1f', 1.25)
        self.assertIn('elapsed=1.2', self.contents())
        self.assertNotIn('PRIVATE RESULT', self.contents())

    def test_transport_failure_is_logged_and_propagated(self):
        with self.assertRaises(requests.Timeout):
            logs.request(Mock(side_effect=requests.Timeout('read timed out')), 'https://example.com')
        self.assertIn('read timed out', self.contents())

    def test_frozen_path_uses_exe_directory(self):
        self.patch.stop()
        with patch.object(logs.sys, 'frozen', True, create=True), patch.object(logs.sys, 'executable', str(Path(self.temp.name)/'app.exe')):
            self.assertEqual(logs.log_directory(), Path(self.temp.name).resolve()/'logs')
        self.patch.start()

    def test_rotation_bounds_size(self):
        logger = logs.get_logger(); handler = logger.handlers[0]; handler.maxBytes = 100; handler.backupCount = 2
        for _ in range(20): logs.info('中文 diagnostic ' + 'x'*50)
        self.assertLessEqual(len(list(self.directory.glob('videoflow.log*'))), 3)

    def test_unwritable_directory_is_reported(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('read only')):
            logs.get_logger()
        self.assertIn('read only', logs.logging_error())

    def test_88_item_batch_preserves_45_successes_and_logs_43_server_failures(self):
        import ai
        from batch_service import run_batch
        def operation(index):
            response = requests.Response()
            response.status_code = 200 if index < 45 else 503
            response._content = b'{"choices":[{"message":{"content":"ok"}}]}' if index < 45 else b'{"error":{"message":"upstream unavailable"}}'
            with patch.object(ai.requests, 'post', return_value=response):
                # Single worker keeps the patched transport deterministic.
                return ai.rewrite_text('copy', 'rewrite', 'integration-secret', 'test-model', 'https://example.com/v1')
        results = run_batch(range(88), operation, workers=1, retries=0)
        self.assertEqual(sum(error is None for _, _, error in results), 45)
        self.assertEqual(sum(error is not None for _, _, error in results), 43)
        content = self.contents()
        for expected in ('503', 'upstream unavailable', 'batch.end', 'item', 'failed=43'):
            self.assertIn(expected, content)
        self.assertNotIn('integration-secret', content)
