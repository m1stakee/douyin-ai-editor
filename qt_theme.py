"""Shared QWidget theme. QSS owns control skins; qt_controls owns arrow painting."""
TOKENS = {
    'window': '#f3f4f7', 'panel': '#ffffff', 'text': '#272d3a',
    'muted': '#707788', 'border': '#dde1e8', 'accent': '#70429d',
    'space_inline': 8, 'space_group': 12, 'space_panel': 16,
}

DROPDOWN_LIST_STYLE = """
QAbstractItemView { background: white; border: 1px solid #ddd4eb; border-radius: 6px; padding: 2px 0; selection-background-color: white; selection-color: #65319a; outline: none; }
QAbstractItemView::item { padding: 0 7px; }
QAbstractItemView::item:selected { background: white; color: #65319a; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #d1cadc; border-radius: 3px; min-height: 28px; margin: 0 1px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

STYLE = """
QMainWindow, QWidget#surface { background: #f3f4f7; color: #272d3a; }
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #272d3a; }
QFrame#card { background: white; border: 1px solid #dde1e8; border-radius: 8px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 20px; font-weight: 700; color: #282238; }
QLabel#muted { color: #707788; font-size: 11px; }
QLabel#section { font-size: 14px; font-weight: 600; color: #333044; }
QLabel#pill { color: #7c3db4; background: #f1e9fb; border-radius: 8px; padding: 6px 10px; }
QPushButton { background: #faf9fd; border: 1px solid #e5e2ee; border-radius: 7px; padding: 8px 13px; }
QWidget#rowActions QPushButton { padding: 4px 12px; min-height: 24px; }
QPushButton:hover { background: #f1eafa; border-color: #b18bd5; }
QPushButton:disabled { color: #aba8b6; background: #f5f4f8; }
QPushButton#primary { background: #8039c3; color: white; border: 0; font-weight: 600; padding: 12px 22px; }
QPushButton#primary:hover { background: #6e2cac; }
QPushButton#icon { border: none; background: transparent; padding: 4px; font-size: 18px; }
QComboBox, QLineEdit, QDoubleSpinBox { border: 1px solid #dedce9; border-radius: 7px; background: white; padding: 7px; min-height: 18px; }
QComboBox { padding-right: 34px; combobox-popup: 0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #e4dfed; background: #faf8fd; border-top-right-radius: 7px; border-bottom-right-radius: 7px; }
QComboBox::down-arrow { image: none; }
QComboBox:hover::drop-down { background: #f1eafa; border-left-color: #b18bd5; }
QComboBox QLineEdit { background: white; selection-background-color: white; selection-color: #65319a; }
QComboBoxPrivateContainer { background: white; border: none; }
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

QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: #70429d; }
QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover { border-color: #a69bb4; }
QPushButton:focus { border-color: #70429d; }
QPushButton:pressed { background: #e9e4ef; }
QPushButton#primary:pressed { background: #542c7a; }
QComboBox:disabled, QLineEdit:disabled { background: #f4f5f7; color: #858b98; border-color: #e3e6ec; }
QTabBar::tab { padding: 9px 12px; background: white; border-bottom: 2px solid #e6e8ed; }
QTabBar::tab:selected { background: white; color: #70429d; border-bottom: 2px solid #70429d; }
QToolTip { background: white; color: #272d3a; border: 1px solid #dde1e8; padding: 6px; }
"""

CLIENT_STYLE = STYLE + """
QListWidget#navigation { background: #ffffff; border: none; border-radius: 8px; padding: 8px; font-size: 13px; }
QListWidget#navigation::item { padding: 12px; margin: 3px 0; border-radius: 7px; }
QListWidget#navigation::item:selected { background: white; color: #70429d; border-left: 3px solid #70429d; }
QTableWidget { background: white; alternate-background-color: #faf9fd; border: 1px solid #e9e5f1; border-radius: 8px; gridline-color: #f0edf5; selection-background-color: #f0e6fc; selection-color: #513478; }
QHeaderView::section { background: #f6f3fa; color: #6f647d; border: none; border-bottom: 1px solid #e6e0ee; padding: 9px; }
QTableWidget::item { padding: 8px; }
QPlainTextEdit { background: #fcfbfe; border: 1px solid #e4dfed; border-radius: 8px; padding: 10px; selection-background-color: #d5b8ef; }
QSplitter::handle { background: transparent; }
"""
