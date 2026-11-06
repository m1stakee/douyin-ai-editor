import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import edge_tts_service


class EdgeTtsPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=16)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text="Edge TTS 在线语音", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self, text="需要 Edge TTS 独立使用密钥；生成前联网验证。", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 10))
        settings = ttk.Frame(self, style="Panel.TFrame", padding=12)
        settings.grid(row=2, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        labels = dict(edge_tts_service.VOICE_OPTIONS)
        current = next((label for label, value in edge_tts_service.VOICE_OPTIONS if value == app.edge_voice.get()), edge_tts_service.VOICE_OPTIONS[0][0])
        ttk.Label(settings, text="音色", style="Panel.TLabel", width=10).grid(row=0, column=0, sticky="w")
        voice = ttk.Combobox(settings, values=list(labels), state="readonly")
        voice.set(current)
        voice.grid(row=0, column=1, sticky="ew")
        voice.bind("<<ComboboxSelected>>", lambda _: (app.edge_voice.set(labels[voice.get()]), app.save_all_settings(False)))
        ttk.Label(settings, text="语速", style="Panel.TLabel", width=10).grid(row=1, column=0, sticky="w", pady=(8, 0))
        speed = ttk.Combobox(settings, textvariable=app.edge_speed, values=("0.75", "1.0", "1.25", "1.5"), state="readonly", width=12)
        speed.grid(row=1, column=1, sticky="w", pady=(8, 0))
        speed.bind("<<ComboboxSelected>>", lambda _: app.save_all_settings(False))
        ttk.Label(settings, text="音量", style="Panel.TLabel", width=10).grid(row=2, column=0, sticky="w", pady=(8, 0))
        volume = ttk.Combobox(settings, textvariable=app.edge_volume, values=("0.5", "0.75", "1.0"), state="readonly", width=12)
        volume.grid(row=2, column=1, sticky="w", pady=(8, 0))
        volume.bind("<<ComboboxSelected>>", lambda _: app.save_all_settings(False))

        ttk.Label(settings, text="使用密钥", style="Panel.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        key = ttk.Entry(settings, textvariable=app.edge_tts_license_key, show="*")
        key.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        key.bind("<FocusOut>", lambda _: app.save_all_settings(False))
