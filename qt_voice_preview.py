"""Independent Qt TTS preview. Does not replace or modify the Tk client."""
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QUrl, Signal, Slot, QLocale
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox, QListWidget,
    QListWidgetItem, QCheckBox, QSlider, QLineEdit, QFileDialog,
    QProgressBar, QMessageBox, QDoubleSpinBox, QAbstractItemView,
    QScrollArea, QTabBar, QSizePolicy, QCompleter,
)

import edge_tts_service
import voicevox_service
import minimax_tts_service
from edge_voice_catalog import load_voices, filter_voices
from app_config import settings_path, load_settings
import asr


STYLE = """
QMainWindow, QWidget#surface { background: #f5f5fa; color: #242331; }
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #302e40; }
QFrame#card { background: white; border: 1px solid #e5e4ee; border-radius: 12px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #282238; }
QLabel#muted { color: #858195; font-size: 11px; }
QLabel#section { font-size: 14px; font-weight: 600; color: #333044; }
QLabel#pill { color: #7c3db4; background: #f1e9fb; border-radius: 8px; padding: 6px 10px; }
QPushButton { background: #faf9fd; border: 1px solid #e5e2ee; border-radius: 7px; padding: 8px 13px; }
QPushButton:hover { background: #f1eafa; border-color: #b18bd5; }
QPushButton:disabled { color: #aba8b6; background: #f5f4f8; }
QPushButton#primary { background: #8039c3; color: white; border: 0; font-weight: 600; padding: 12px 22px; }
QPushButton#primary:hover { background: #6e2cac; }
QPushButton#icon { border: none; background: transparent; padding: 4px; font-size: 18px; }
QComboBox, QLineEdit, QDoubleSpinBox { border: 1px solid #dedce9; border-radius: 7px; background: white; padding: 7px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #f0e7fb; selection-color: #65319a; }
QListWidget { background: #fcfbfe; border: 1px solid #e8e5ef; border-radius: 8px; outline: none; padding: 5px; }
QListWidget::item { padding: 4px; border-radius: 6px; }
QListWidget::item:selected { background: #f0e6fc; color: #643397; }
QListWidget::item:hover { background: #f5f0fc; }
QSlider::groove:horizontal { height: 5px; background: #eeedf4; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #853cc6; border-radius: 2px; }
QSlider::handle:horizontal { background: white; border: 1px solid #853cc6; width: 14px; margin: -5px 0; border-radius: 7px; }
QProgressBar { background: #efedf5; border: none; border-radius: 5px; height: 9px; text-align: center; }
QProgressBar::chunk { background: #8d50c9; border-radius: 5px; }
QTabBar::tab { background: #f2f0f7; border: 0; padding: 9px 20px; color: #81798e; }
QTabBar::tab:selected { background: #ece0fa; color: #7332b0; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
QWidget#voiceInner, QWidget#voiceRow { background: white; }
QScrollBar:vertical { width: 6px; background: transparent; }
QScrollBar::handle:vertical { background: #d5cfdf; border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def label(text, kind=None):
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName('card')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return widget, layout


class JobSignals(QObject):
    done = Signal(object)
    error = Signal(str)
    progress = Signal(object)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.signals = JobSignals()
        self.function = function

    def run(self):
        try:
            self.signals.done.emit(self.function(self.signals.progress.emit))
        except Exception as exc:
            self.signals.error.emit(str(exc))


class QtVoiceWindow(QMainWindow):
    def __init__(self, voices=None, config_path=None):
        super().__init__()
        self.setWindowTitle('VideoFlow · Qt 语音工作台预览')
        self.resize(1150, 900)
        self.setMinimumSize(1020, 820)
        self.config_path = Path(config_path) if config_path else settings_path().with_name('qt-tts-preview.json')
        try:
            self.saved = json.loads(self.config_path.read_text(encoding='utf-8'))
            if not isinstance(self.saved, dict):
                self.saved = {}
        except (ValueError, OSError):
            self.saved = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.jobs = []
        self.busy = False
        self.preview_busy = False
        self.voices = []
        self.selected_voice = self.saved.get('voice', edge_tts_service.DEFAULT_VOICE)
        self.favorites = set(self.saved.get('favorites', []))
        self.temp = tempfile.TemporaryDirectory(prefix='videoflow-qt-preview-')
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(1)
        self.player.errorOccurred.connect(lambda *_: self.status.setText('试听播放失败：' + self.player.errorString()))
        self._build()
        self.setStyleSheet(STYLE)
        self.engine.currentChanged.connect(self.save)
        for combo in (self.language_combo, self.region_combo, self.gender_combo, self.output_format):
            combo.currentIndexChanged.connect(self.save)
        self.favorite_only.toggled.connect(self.save)
        for slider in (self.speed_slider, self.volume_slider, self.pitch_slider):
            slider.sliderReleased.connect(self.save)
        self.output.editingFinished.connect(self.save)
        self.pause.editingFinished.connect(self.save)
        self.mm_key.editingFinished.connect(self.save)
        self.mm_voice.currentIndexChanged.connect(self.save)
        for combo in (self.mm_base, self.mm_model):
            combo.currentIndexChanged.connect(self.save)
        self.mm_voice.editTextChanged.connect(self.save)
        for slider in (self.mm_speed, self.mm_volume, self.mm_pitch):
            slider.sliderReleased.connect(self.save)
        if voices is not None:
            self.apply_voices(voices)
        else:
            self.refresh_voices()

    def _build(self):
        surface = QWidget()
        surface.setObjectName('surface')
        self.setCentralWidget(surface)
        root = QVBoxLayout(surface)
        root.setContentsMargins(28, 23, 28, 23)
        root.setSpacing(18)
        header = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(label('VideoFlow  /  语音工作台', 'brand'))
        title.addWidget(label('选择声音，让文案拥有自己的表达。', 'muted'))
        header.addLayout(title)
        header.addStretch()
        header.addWidget(label('QT 预览版', 'pill'))
        root.addLayout(header)
        content = QHBoxLayout()
        content.setSpacing(18)
        root.addLayout(content, 1)
        left, left_layout = card()
        left.setFixedWidth(375)
        content.addWidget(left)
        self.engine = QTabBar()
        self.engine.addTab('Edge TTS')
        self.engine.addTab('VOICEVOX')
        self.engine.addTab('MiniMax')
        self.engine.setExpanding(True)
        left_layout.addWidget(self.engine)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        left_layout.addWidget(scroll, 1)
        inner = QWidget()
        inner.setObjectName('voiceInner')
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 8, 0, 0)
        inner_layout.setSpacing(12)
        scroll.setWidget(inner)
        self.edge_controls = QWidget()
        edge_layout = QVBoxLayout(self.edge_controls)
        edge_layout.setContentsMargins(0, 0, 0, 0)
        edge_layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label('音色  Voice', 'section'))
        heading.addStretch()
        self.refresh_button = QPushButton('刷新')
        self.refresh_button.clicked.connect(self.refresh_voices)
        heading.addWidget(self.refresh_button)
        edge_layout.addLayout(heading)
        filters = QGridLayout()
        self.language_combo = QComboBox()
        self.region_combo = QComboBox()
        self.gender_combo = QComboBox()
        self.gender_combo.addItem('全部', '')
        self.gender_combo.addItem('女声', 'Female')
        self.gender_combo.addItem('男声', 'Male')
        for col, (text, combo) in enumerate([('语言', self.language_combo), ('地区', self.region_combo), ('性别', self.gender_combo)]):
            filters.addWidget(label(text, 'muted'), 0, col)
            filters.addWidget(combo, 1, col)
            combo.setMinimumWidth(75)
        edge_layout.addLayout(filters)
        self.language_combo.currentIndexChanged.connect(self.language_changed)
        self.region_combo.currentIndexChanged.connect(self.filter_list)
        self.gender_combo.currentIndexChanged.connect(self.filter_list)
        favorites_row = QHBoxLayout()
        self.favorite_only = QCheckBox('只看收藏')
        self.favorite_only.setChecked(bool(self.saved.get('favorites_only', False)))
        self.favorite_only.toggled.connect(self.filter_list)
        favorites_row.addWidget(self.favorite_only)
        favorites_row.addStretch()
        self.count = label('读取中…', 'muted')
        favorites_row.addWidget(self.count)
        edge_layout.addLayout(favorites_row)
        self.voice_list = QListWidget()
        self.voice_list.setMinimumHeight(180)
        self.voice_list.setMaximumHeight(200)
        self.voice_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.voice_list.currentItemChanged.connect(self.select_voice)
        edge_layout.addWidget(self.voice_list)
        self.selected_label = label('尚未选择音色', 'muted')
        self.selected_label.setWordWrap(True)
        edge_layout.addWidget(self.selected_label)
        edge_layout.addWidget(label('声音设置', 'section'))
        self.speed_slider = self._slider(edge_layout, '语速', 50, 200, int(self.saved.get('speed', 100)), lambda n: f'{n / 100:.2f}×')
        self.volume_slider = self._slider(edge_layout, '音量', 0, 100, int(self.saved.get('volume', 100)), lambda n: f'{n}%')
        self.pitch_slider = self._slider(edge_layout, '音调', -50, 50, int(self.saved.get('pitch', 0)), lambda n: f'{n:+d} Hz')
        inner_layout.addWidget(self.edge_controls)
        self.vv_controls = QWidget()
        vv = QVBoxLayout(self.vv_controls)
        vv.setContentsMargins(0, 0, 0, 0)
        vv.addWidget(label('VOICEVOX 本地引擎', 'section'))
        vv.addWidget(label('请先启动已安装的 VOICEVOX。', 'muted'))
        self.vv_connect = QPushButton('连接本地引擎')
        self.vv_connect.clicked.connect(self.connect_voicevox)
        vv.addWidget(self.vv_connect)
        self.vv_voice = QComboBox()
        vv.addWidget(self.vv_voice)
        self.vv_speed = self._slider(vv, '语速', 50, 200, 100, lambda n: f'{n / 100:.2f}×')
        self.vv_volume = self._slider(vv, '音量', 0, 200, 100, lambda n: f'{n}%')
        self.vv_pitch = self._slider(vv, '音高', -15, 15, 0, lambda n: f'{n / 100:+.2f}')
        inner_layout.addWidget(self.vv_controls)
        self.mm_controls = QWidget()
        mm = QVBoxLayout(self.mm_controls)
        mm.setContentsMargins(0, 0, 0, 0)
        mm.addWidget(label('MiniMax 在线引擎', 'section'))
        mm.addWidget(label('填写 MiniMax API Key；密钥仅保存到本机配置。', 'muted'))
        key_row = QHBoxLayout(); key_row.addWidget(label('API Key', 'muted'))
        self.mm_key = QLineEdit(self.saved.get('minimax_api_key', '')); self.mm_key.setEchoMode(QLineEdit.EchoMode.Password); key_row.addWidget(self.mm_key, 1); mm.addLayout(key_row)
        base_row = QHBoxLayout(); base_row.addWidget(label('区域', 'muted')); self.mm_base = QComboBox(); self.mm_base.addItem('中国大陆', 'https://api.minimax.cn'); self.mm_base.addItem('国际版', 'https://api.minimax.io'); self.mm_base.setCurrentIndex(1 if self.saved.get('minimax_base_url') == 'https://api.minimax.io' else 0); base_row.addWidget(self.mm_base, 1); mm.addLayout(base_row)
        model_row = QHBoxLayout(); model_row.addWidget(label('模型', 'muted')); self.mm_model = QComboBox(); self.mm_model.addItems(['speech-2.8-hd','speech-2.8-turbo','speech-2.6-hd','speech-2.6-turbo','speech-02-hd','speech-02-turbo']); self.mm_model.setCurrentText(self.saved.get('minimax_model', minimax_tts_service.DEFAULT_MODEL)); model_row.addWidget(self.mm_model, 1); mm.addLayout(model_row)
        voice_heading = QHBoxLayout()
        voice_heading.addWidget(label('音色 · 输入名称或 ID 搜索', 'muted'))
        voice_heading.addStretch()
        self.mm_refresh = QPushButton('获取音色')
        self.mm_refresh.clicked.connect(self.refresh_minimax_voices)
        voice_heading.addWidget(self.mm_refresh)
        mm.addLayout(voice_heading)
        voice_row = QHBoxLayout()
        self.mm_voice = QComboBox()
        self.mm_voice.setEditable(True)
        self.mm_voice.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.mm_voice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mm_voice.setMinimumContentsLength(12)
        self.mm_voice.setMaxVisibleItems(12)
        self.mm_voice.setCurrentText(self.saved.get('minimax_voice', minimax_tts_service.DEFAULT_VOICE))
        self.mm_voice.lineEdit().setPlaceholderText('输入名称或音色 ID 自动搜索')
        completion = self.mm_voice.completer()
        completion.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completion.setFilterMode(Qt.MatchFlag.MatchContains)
        completion.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completion.popup().setMinimumWidth(420)
        voice_row.addWidget(self.mm_voice, 1)
        self.mm_dropdown = QPushButton('▼')
        self.mm_dropdown.setFixedWidth(36)
        self.mm_dropdown.setToolTip('展开全部音色')
        self.mm_dropdown.clicked.connect(self.mm_voice.showPopup)
        voice_row.addWidget(self.mm_dropdown)
        mm.addLayout(voice_row)
        self.mm_speed = self._slider(mm, '语速', 50, 200, int(self.saved.get('minimax_speed', 100)), lambda n: f'{n / 100:.2f}×')
        self.mm_volume = self._slider(mm, '音量', 1, 1000, int(self.saved.get('minimax_volume', 100)), lambda n: f'{n / 100:.2f}')
        self.mm_pitch = self._slider(mm, '音调', -12, 12, int(self.saved.get('minimax_pitch', 0)), lambda n: f'{n:+d}')
        inner_layout.addWidget(self.mm_controls)
        self.engine.currentChanged.connect(self.engine_changed)
        self.engine.setCurrentIndex(int(self.saved.get('engine', 0)) if self.saved.get('engine') in (0, 1, 2) else 0)
        self.engine_changed()
        inner_layout.addStretch()

        right = QVBoxLayout()
        right.setSpacing(16)
        content.addLayout(right, 1)
        scripts, scripts_layout = card()
        right.addWidget(scripts, 1)
        scripts_layout.addWidget(label('文案文件', 'section'))
        scripts_layout.addWidget(label('所有引擎共用文案列表、输出格式与字幕时间轴。', 'muted'))
        toolbar = QHBoxLayout()
        for text, callback in [('识别目录', self.import_directory), ('导入文件', self.import_files), ('全选', self.select_all), ('清除', self.clear_files)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        scripts_layout.addLayout(toolbar)
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        scripts_layout.addWidget(self.files, 1)
        self.file_count = label('尚未导入文案', 'muted')
        self.files.itemChanged.connect(self.update_file_count)
        scripts_layout.addWidget(self.file_count)
        output_card, output_layout = card()
        right.addWidget(output_card)
        output_layout.addWidget(label('导出设置', 'section'))
        output_layout.addWidget(label('保存目录', 'muted'))
        output_row = QHBoxLayout()
        original = load_settings()
        base = Path(original.get('output_directory') or Path.home() / 'Desktop')
        self.output = QLineEdit(self.saved.get('output') or str(base / '5_语音转出'))
        output_row.addWidget(self.output, 1)
        choose = QPushButton('选择')
        choose.clicked.connect(self.choose_output)
        output_row.addWidget(choose)
        open_folder = QPushButton('打开')
        open_folder.clicked.connect(self.open_output)
        output_row.addWidget(open_folder)
        output_layout.addLayout(output_row)
        output_options = QHBoxLayout()
        output_options.addWidget(label('文件格式', 'muted'))
        self.output_format = QComboBox()
        self.output_format.addItems(['MP3', 'WAV', 'M4A', 'FLAC'])
        self.output_format.setCurrentText(self.saved.get('format', 'MP3'))
        output_options.addWidget(self.output_format)
        output_options.addStretch()
        output_options.addWidget(label('句间停顿', 'muted'))
        self.pause = QDoubleSpinBox()
        self.pause.setRange(0, 5)
        self.pause.setSingleStep(.1)
        self.pause.setValue(float(self.saved.get('pause', .3)))
        self.pause.setSuffix(' 秒')
        output_options.addWidget(self.pause)
        output_layout.addLayout(output_options)
        output_layout.addWidget(label('每份文案生成同名音频、SRT 及逐句音频。', 'muted'))
        footer, footer_layout = card()
        root.addWidget(footer)
        state_row = QHBoxLayout()
        self.status = label('准备就绪', 'muted')
        self.status.setWordWrap(True)
        state_row.addWidget(self.status, 1)
        self.generate_button = QPushButton('生成语音与 SRT   →')
        self.generate_button.setObjectName('primary')
        self.generate_button.clicked.connect(self.generate)
        state_row.addWidget(self.generate_button)
        footer_layout.addLayout(state_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        footer_layout.addWidget(self.progress)

    def _slider(self, layout, name, minimum, maximum, value, display):
        row = QHBoxLayout()
        row.addWidget(label(name))
        row.addStretch()
        number = label(display(value), 'pill')
        row.addWidget(number)
        layout.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(lambda n: number.setText(display(n)))
        layout.addWidget(slider)
        return slider

    def start_job(self, function, finished, error=None, progress=None):
        job = Job(function)
        self.jobs.append(job)
        job.signals.done.connect(finished)
        job.signals.error.connect(error or self.show_error)
        if progress:
            job.signals.progress.connect(progress)
        self.pool.start(job)

    @Slot(str)
    def show_error(self, text):
        self.status.setText(text)

    def refresh_voices(self):
        self.refresh_button.setEnabled(False)
        self.status.setText('正在读取 Edge TTS 完整音色列表…')
        self.start_job(lambda _: load_voices(refresh=bool(self.voices)), self.catalog_loaded, self.catalog_failed)

    @Slot(object)
    def catalog_loaded(self, voices):
        self.refresh_button.setEnabled(True)
        self.apply_voices(voices)
        self.status.setText(f'已加载 {len(voices)} 个在线音色')

    @Slot(str)
    def catalog_failed(self, error):
        self.refresh_button.setEnabled(True)
        self.count.setText('读取失败')
        self.status.setText('音色加载失败，可点击刷新：' + error)

    def apply_voices(self, voices):
        self.voices = voices
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        self.language_combo.addItem('全部', '')
        languages = sorted({v['Locale'].split('-')[0] for v in voices})
        for code in languages:
            name = QLocale.languageToString(QLocale(code).language())
            self.language_combo.addItem(name if name != 'C' else code, code)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(self.saved.get('language', ''))))
        self.language_combo.blockSignals(False)
        self.gender_combo.setCurrentIndex(max(0, self.gender_combo.findData(self.saved.get('gender', ''))))
        self.language_changed()
        self.region_combo.setCurrentIndex(max(0, self.region_combo.findData(self.saved.get('region', ''))))
        self.filter_list()

    def language_changed(self, *_):
        language = self.language_combo.currentData() or ''
        previous = self.region_combo.currentData()
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        self.region_combo.addItem('全部', '')
        locales = {v['Locale'] for v in self.voices if not language or v['Locale'].split('-')[0] == language}
        regions = {}
        for locale in locales:
            regions[locale.split('-')[-1]] = QLocale.territoryToString(QLocale(locale.replace('-', '_')).territory())
        for region in sorted(regions):
            self.region_combo.addItem(regions[region], region)
        self.region_combo.setCurrentIndex(max(0, self.region_combo.findData(previous)))
        self.region_combo.blockSignals(False)
        self.filter_list()

    def filter_list(self, *_):
        voices = filter_voices(self.voices, language=self.language_combo.currentData() or '', region=self.region_combo.currentData() or '', gender=self.gender_combo.currentData() or '', favorites_only=self.favorite_only.isChecked(), favorites=self.favorites)
        self.voice_list.blockSignals(True)
        self.voice_list.clear()
        self.count.setText(f'{len(voices)} 个音色')
        for voice in voices:
            name = voice['ShortName']
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            row = QWidget()
            row.setObjectName('voiceRow')
            layout = QHBoxLayout(row)
            layout.setContentsMargins(5, 5, 5, 5)
            badge = label('女' if voice['Gender'] == 'Female' else '男', 'pill')
            badge.setFixedWidth(30)
            badge.setMinimumHeight(25)
            badge.setStyleSheet('background: #fce8ee; color: #bc556f; border-radius: 7px; padding: 3px;' if voice['Gender'] == 'Female' else 'background: #e5f1fd; color: #487cae; border-radius: 7px; padding: 3px;')
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(badge)
            text = label(name.split('-')[-1].replace('Neural', ''))
            text.setMinimumWidth(0)
            text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.setToolTip(voice.get('FriendlyName', name) + '\n' + voice['Locale'])
            layout.addWidget(text, 1)
            play = QPushButton('▷')
            play.setObjectName('icon')
            play.setFixedSize(26, 29)
            play.setToolTip('试听此音色')
            play.clicked.connect(lambda checked=False, v=voice: self.preview_voice(v))
            layout.addWidget(play)
            favorite = QPushButton('★' if name in self.favorites else '☆')
            favorite.setObjectName('icon')
            favorite.setFixedSize(26, 29)
            favorite.setToolTip('收藏 / 取消收藏')
            favorite.clicked.connect(lambda checked=False, n=name: self.toggle_favorite(n))
            layout.addWidget(favorite)
            item.setSizeHint(row.sizeHint())
            self.voice_list.addItem(item)
            self.voice_list.setItemWidget(item, row)
            if name == self.selected_voice:
                self.voice_list.setCurrentItem(item)
        self.voice_list.blockSignals(False)
        self.selected_label.setText('已选：' + self.selected_voice)

    def select_voice(self, current, _previous):
        if current:
            self.selected_voice = current.data(Qt.ItemDataRole.UserRole)
            self.selected_label.setText('已选：' + self.selected_voice)
            self.save()

    def toggle_favorite(self, name):
        if name in self.favorites:
            self.favorites.remove(name)
        else:
            self.favorites.add(name)
        self.filter_list()
        self.save()

    def engine_changed(self, *_):
        edge = self.engine.currentIndex() == 0
        vv = self.engine.currentIndex() == 1
        self.edge_controls.setVisible(edge)
        self.vv_controls.setVisible(vv)
        self.mm_controls.setVisible(not edge and not vv)
        self.save()

    def refresh_minimax_voices(self):
        key = self.mm_key.text().strip()
        if not key:
            self.status.setText('请先填写 MiniMax API Key')
            return
        self.mm_refresh.setEnabled(False)
        base = self.mm_base.currentData()
        self.start_job(lambda _: minimax_tts_service.list_voices(key, base), self.minimax_voices_ready, self.minimax_voices_failed)

    def minimax_voice_id(self):
        text = self.mm_voice.currentText().strip()
        index = self.mm_voice.findText(text, Qt.MatchFlag.MatchExactly)
        return (self.mm_voice.itemData(index) or text) if index >= 0 else text

    def minimax_voices_ready(self, voices):
        selected = self.minimax_voice_id()
        self.mm_refresh.setEnabled(True); self.mm_voice.blockSignals(True); self.mm_voice.clear()
        for voice in voices: self.mm_voice.addItem(f"{voice['voice_name']} · {voice['voice_id']}", voice['voice_id'])
        index = self.mm_voice.findData(selected)
        if index >= 0: self.mm_voice.setCurrentIndex(index)
        elif selected: self.mm_voice.setEditText(selected)
        self.mm_voice.blockSignals(False); self.save()
        self.status.setText(f'MiniMax 已读取 {len(voices)} 个音色')

    def minimax_voices_failed(self, text):
        self.mm_refresh.setEnabled(True); self.status.setText('MiniMax 音色读取失败：' + text)

    def preview_voice(self, voice):
        if self.preview_busy:
            self.status.setText('正在准备试听，请稍候…')
            return
        self.preview_busy = True
        self.player.stop()
        self.player.setSource(QUrl())
        self.selected_voice = voice['ShortName']
        self.filter_list()
        self.save()
        language = voice['Locale'].split('-')[0]
        samples = {'zh': '你好，这是语音试听，欢迎使用语音工作台。', 'en': 'Hello, this is a voice preview. Welcome to your voice studio.', 'ja': 'こんにちは。音声のサンプルをお聞きください。', 'ko': '안녕하세요. 음성 미리 듣기입니다.', 'fr': 'Bonjour, voici un aperçu de cette voix.', 'es': 'Hola, esta es una prueba de voz.', 'de': 'Hallo, dies ist eine Sprachvorschau.'}
        text = samples.get(language, 'Hello, this is a voice preview.')
        options = dict(voice=self.selected_voice, rate=self.speed_slider.value()/100, volume=self.volume_slider.value()/100, pitch=self.pitch_slider.value())
        path = Path(self.temp.name) / 'preview.mp3'
        self.status.setText('正在生成试听：' + voice['ShortName'])
        self.start_job(lambda _: edge_tts_service.synthesize_speech(text, path, **options)[0], self.preview_ready, self.preview_failed)

    @Slot(object)
    def preview_ready(self, path):
        self.preview_busy = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        self.status.setText('正在播放试听')

    @Slot(str)
    def preview_failed(self, text):
        self.preview_busy = False
        self.status.setText('试听失败：' + text)

    def connect_voicevox(self):
        self.vv_connect.setEnabled(False)
        self.start_job(lambda _: voicevox_service.available_voices(), self.voicevox_ready, self.voicevox_failed)

    @Slot(object)
    def voicevox_ready(self, voices):
        self.vv_connect.setEnabled(True)
        self.vv_voice.clear()
        for voice in voices:
            self.vv_voice.addItem(voice.label, voice.style_id)
        self.status.setText(f'VOICEVOX 已连接，{len(voices)} 个音色；发布时请按角色条款标注。')

    @Slot(str)
    def voicevox_failed(self, text):
        self.vv_connect.setEnabled(True)
        self.status.setText(text)

    def add_files(self, paths):
        existing = {self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        for path in paths:
            path = Path(path).resolve()
            if path.suffix.lower() != '.txt' or str(path) in existing:
                continue
            item = QListWidgetItem(path.name + '    ·    等待生成')
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.files.addItem(item)
            existing.add(str(path))
        self.update_file_count()

    def import_files(self):
        if self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '导入文案', '', 'TXT 文案 (*.txt)')
        self.add_files(paths)

    def import_directory(self):
        if self.busy:
            return
        path = QFileDialog.getExistingDirectory(self, '选择文案目录')
        if path:
            self.add_files(sorted(Path(path).glob('*.txt')))

    def select_all(self):
        if not self.busy:
            for index in range(self.files.count()):
                self.files.item(index).setCheckState(Qt.CheckState.Checked)

    def clear_files(self):
        if not self.busy:
            self.files.clear()
            self.update_file_count()

    def update_file_count(self, *_):
        checked = sum(self.files.item(i).checkState() == Qt.CheckState.Checked for i in range(self.files.count()))
        self.file_count.setText(f'已选择 {checked} / {self.files.count()} 个文案')

    def choose_output(self):
        value = QFileDialog.getExistingDirectory(self, '选择保存目录', self.output.text())
        if value:
            self.output.setText(value)

    def open_output(self):
        try:
            folder = Path(self.output.text()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except OSError as exc:
            self.status.setText(str(exc))

    def generate(self):
        paths = [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count()) if self.files.item(i).checkState() == Qt.CheckState.Checked]
        if not paths:
            self.status.setText('请先导入并勾选 TXT 文案')
            return
        if not self.output.text().strip():
            self.status.setText('请选择保存目录')
            return
        engine = self.engine.currentIndex()
        edge = engine == 0
        if engine == 1 and self.vv_voice.currentData() is None:
            self.status.setText('请先连接 VOICEVOX 本地引擎')
            return
        if engine == 2 and not self.mm_key.text().strip():
            self.status.setText('请先填写 MiniMax API Key')
            return
        output = self.output.text()
        common = dict(pause_seconds=self.pause.value(), output_format=self.output_format.currentText().lower(), ffmpeg_path=asr.resolve_ffmpeg())
        if edge:
            options = dict(voice=self.selected_voice, rate=self.speed_slider.value()/100, volume=self.volume_slider.value()/100, pitch=self.pitch_slider.value())
            service = edge_tts_service
        elif engine == 1:
            options = dict(style_id=self.vv_voice.currentData(), speed=self.vv_speed.value()/100, volume=self.vv_volume.value()/100, pitch=self.vv_pitch.value()/100)
            service = voicevox_service
        else:
            options = dict(api_key=self.mm_key.text().strip(), base_url=self.mm_base.currentData(), model=self.mm_model.currentText(), voice_id=self.minimax_voice_id() or minimax_tts_service.DEFAULT_VOICE, speed=self.mm_speed.value()/100, volume=self.mm_volume.value()/100, pitch=self.mm_pitch.value())
            service = minimax_tts_service
        self.save()
        self.busy = True
        self.generate_button.setEnabled(False)
        self.engine.setEnabled(False)
        self.files.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText(f'开始处理 {len(paths)} 份文案…')

        def work(emit):
            def progress(fi, ft, source, si, st):
                emit((round(((fi-1)+si/max(st,1))/ft*100), f'{source.name} · 句子 {si}/{st}'))
            return service.synthesize_script_files(paths, output, **common, **options, on_progress=progress)
        self.start_job(work, self.generated, self.generation_failed, self.generation_progress)

    @Slot(object)
    def generation_progress(self, value):
        self.progress.setValue(value[0])
        self.status.setText(value[1])

    @Slot(object)
    def generated(self, results):
        errors = []
        for result in results:
            for index in range(self.files.count()):
                item = self.files.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == str(result['source']):
                    item.setText(result['source'].name + ('    ·    已完成' if result['error'] is None else '    ·    失败'))
                    if result['error'] is not None:
                        item.setToolTip(str(result['error']))
                        errors.append(result['source'].name + ': ' + str(result['error']))
        self.finish_generation()
        self.progress.setValue(100)
        self.status.setText(f'处理完成 · 成功 {len(results)-len(errors)}，失败 {len(errors)}')
        if errors:
            message = QMessageBox(self)
            message.setWindowTitle('部分文案生成失败')
            message.setText('失败原因可在列表悬停查看，或展开下方详情。')
            message.setDetailedText('\n'.join(errors))
            message.exec()

    @Slot(str)
    def generation_failed(self, text):
        self.finish_generation()
        self.status.setText('生成失败：' + text)

    def finish_generation(self):
        self.busy = False
        self.generate_button.setEnabled(True)
        self.engine.setEnabled(True)
        self.files.setEnabled(True)

    def save(self, *_):
        if not hasattr(self, 'output'):
            return
        value = dict(voice=self.selected_voice, favorites=sorted(self.favorites), favorites_only=self.favorite_only.isChecked(), language=self.language_combo.currentData() or '', region=self.region_combo.currentData() or '', gender=self.gender_combo.currentData() or '', speed=self.speed_slider.value(), volume=self.volume_slider.value(), pitch=self.pitch_slider.value(), output=self.output.text(), format=self.output_format.currentText(), pause=self.pause.value(), engine=self.engine.currentIndex(), minimax_api_key=self.mm_key.text(), minimax_base_url=self.mm_base.currentData(), minimax_model=self.mm_model.currentText(), minimax_voice=self.mm_voice.currentData() or self.mm_voice.currentText(), minimax_speed=self.mm_speed.value(), minimax_volume=self.mm_volume.value(), minimax_pitch=self.mm_pitch.value())
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        value['minimax_voice'] = self.minimax_voice_id()
        temporary = self.config_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.config_path)

    def closeEvent(self, event):
        if self.pool.activeThreadCount():
            self.status.setText('任务正在进行，请等待当前操作结束后关闭。')
            event.ignore()
            return
        try:
            self.save()
        except OSError as exc:
            QMessageBox.warning(self, '配置保存失败', str(exc))
            event.ignore()
            return
        self.player.stop()
        self.player.setSource(QUrl())
        self.temp.cleanup()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont('Microsoft YaHei UI', 9))
    window = QtVoiceWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
