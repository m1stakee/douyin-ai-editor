import json
import os
import sys
from pathlib import Path

def _root() -> Path:
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root

def _app_data_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / ".videoflow") / "VideoFlow"

def _config_path() -> Path: return _app_data_root() / "credentials.local.json"
def settings_path() -> Path: return _app_data_root() / "settings.local.json"

def _legacy_settings_path() -> Path: return _root() / "settings.local.json"
def _legacy_config_path() -> Path: return _root() / "credentials.local.json"

def load_settings(path: Path | None = None) -> dict:
    target = path or settings_path()
    if path is None and not target.exists() and _legacy_settings_path().exists():
        target = _legacy_settings_path()
    if not target.exists(): return {}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError): return {}

def save_settings(values: dict, path: Path | None = None) -> Path:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return target

def _local_values() -> dict:
    path = _config_path()
    if not path.exists() and _legacy_config_path().exists():
        path = _legacy_config_path()
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}

def credential(env_name: str, file_name: str) -> str:
    return os.environ.get(env_name, "").strip() or str(load_settings().get(file_name, "")).strip() or str(_local_values().get(file_name, "")).strip()

def henghengmao_key() -> str: return credential("HENGHENGMAO_API_KEY", "henghengmao_api_key")
def dashscope_key() -> str: return credential("DASHSCOPE_API_KEY", "dashscope_api_key")
