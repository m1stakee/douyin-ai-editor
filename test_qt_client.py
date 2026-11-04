import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from qt_client import VideoFlowQt


class TestQtClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_navigation_and_configuration_preserve_unknown_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'settings.json'
            config.write_text('{"legacy_option":"preserved"}',encoding='utf-8')
            client = VideoFlowQt(config_path=config)
            self.assertEqual(client.navigation.count(), 9)
            client.settings_page.fields['llm_base_url'].setText('https://example.com/v1')
            client.save_configuration()
            from app_config import load_settings
            saved = load_settings(config)
            self.assertEqual(saved['legacy_option'], 'preserved')
            self.assertEqual(saved['llm_base_url'], 'https://example.com/v1')
            client.close()

    def test_import_deduplicates_and_retry_only_selects_failed_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            client = VideoFlowQt(config_path=Path(folder)/'settings.json')
            page = client.pages['rewrite']
            path = Path(folder)/'a.txt'; path.write_text('text',encoding='utf-8')
            page.add_paths([path,path])
            self.assertEqual(page.table.rowCount(),1)
            self.assertEqual(page.failed_rows(),[])
            page.failures.add(0)
            self.assertEqual(page.failed_rows(),[0])
            client.close()

    def test_background_rewrite_updates_table_and_history(self):
        from app_config import save_settings
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'settings.json'
            save_settings({'output_directory':folder,'llm_key':'test','llm_model':'model'},config)
            client=VideoFlowQt(config_path=config)
            source=Path(folder)/'demo.txt';source.write_text('source',encoding='utf-8')
            page=client.pages['rewrite'];page.add_paths([source])
            with patch('qt_workflow_service.ai.rewrite_text',return_value='rewritten'):
                page.begin()
                deadline=time.monotonic()+5
                while page.busy and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.01)
            self.assertFalse(page.busy)
            self.assertEqual(page.table.item(0,1).text(),'完成')
            self.assertTrue(Path(page.outputs[0]).is_file())
            self.assertEqual(client.history.list()[0]['status'],'完成')
            while client.pool.activeThreadCount():self.app.processEvents();time.sleep(.01)
            client.close()

    def test_license_dialog_persists_only_after_success(self):
        from qt_client import LicenseDialog
        from app_config import load_settings
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'settings.json';dialog=LicenseDialog(config)
            dialog.key.setText('test-license')
            dialog.checked((False,'invalid'))
            self.assertFalse(dialog.validated)
            self.assertFalse(config.exists())
            dialog.checked((True,'ok'))
            self.assertTrue(dialog.validated)
            self.assertEqual(load_settings(config)['license_key'],'test-license')
            dialog.close()
