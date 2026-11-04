import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from main import App


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class TestScroll(unittest.TestCase):
    def test_internal_dropdown_paths_do_not_raise_or_scroll_main(self):
        root = tk.Tk()
        root.withdraw()
        try:
            canvas = tk.Canvas(root, height=100, yscrollincrement=10, scrollregion=(0, 0, 100, 2000))
            root.main_canvas = canvas
            before = canvas.yview()
            App._scroll_main_window(root, SimpleNamespace(widget='.unknown.popdown.f.l', delta=-120))
            self.assertEqual(canvas.yview(), before)
            App._scroll_main_window(root, SimpleNamespace(widget=canvas, delta=-120))
            self.assertGreater(canvas.yview()[0], before[0])
        finally:
            root.destroy()


class TestSharedTtsUi(unittest.TestCase):
    def test_tabs_keep_same_import_list_and_restore_selected_engine(self):
        with tempfile.TemporaryDirectory() as folder, patch('main.load_settings', return_value={'voice_tab': 'edge'}), patch('main.save_settings'), patch.object(App, '_authorize_startup'), patch.object(App, 'run'):
            app = App()
            try:
                app.project = Path(folder)
                app.open_voicevox_window()
                app.update()
                widgets = list(descendants(app.voicevox_window))
                notebook = next(w for w in widgets if w.winfo_class() == 'TNotebook')
                self.assertEqual(notebook.index(notebook.select()), 1)
                self.assertEqual(len(notebook.tabs()), 2)
                # Shared file panel is outside either engine page.
                panel = next(w.master for w in widgets if w.winfo_class() == 'TLabel' and str(w.cget('text')).startswith('导入文案文件'))
                self.assertFalse(any(str(panel).startswith(tab + '.') for tab in notebook.tabs()))
                notebook.select(0)
                app.update()
                self.assertEqual(app.settings_values()['voice_tab'], 'voicevox')
                notebook.select(1)
                app.update()
                self.assertTrue(panel.winfo_exists())
                self.assertEqual(app.settings_values()['voice_tab'], 'edge')
            finally:
                app.destroy()
