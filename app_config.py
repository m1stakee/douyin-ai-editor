import json
import os
import sys
from pathlib import Path

def _root() -> Path:
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root

def _config_path() -> Path: return _root() / "credentials.local.json"
def settings_path() -> Path: return _root() / "settings.local.json"

def load_settings(path: Path | None = None) -> dict:
    target = path or settings_path()
    if not target.exists(): return {}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError): return {}

def save_settings(values: dict, path: Path | None = None) -> Path:
    target = path or settings_path()
    target.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return target

def _local_values() -> dict:
    path = _config_path()
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}

def credential(env_name: str, file_name: str) -> str:
    return os.environ.get(env_name, "").strip() or str(load_settings().get(file_name, "")).strip() or str(_local_values().get(file_name, "")).strip()

def henghengmao_key() -> str: return credential("HENGHENGMAO_API_KEY", "henghengmao_api_key")
def groq_key() -> str: return credential("GROQ_API_KEY", "groq_api_key")

def save_credentials(henghengmao: str, groq: str, path: Path | None = None) -> Path:
    target = path or _config_path()
    target.write_text(json.dumps({"henghengmao_api_key": henghengmao.strip(), "groq_api_key": groq.strip()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
