import json
import sys
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path


def default_task_history_path() -> Path:
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / "task_history.local.json"


class TaskStore:
    """Thread-safe, persistent task history. Credentials are never stored here."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_task_history_path()
        self._lock = threading.RLock()
        self._tasks = self._load()
        changed = False
        for task in self._tasks:
            if task.get("status") in {"等待中", "运行中", "暂停中"}:
                task["status"] = "已中断"
                for item in task.get("items", []):
                    if item.get("status") not in {"完成", "失败"}:
                        item["status"] = "已中断"
                changed = True
        if changed:
            self._save()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def create(self, kind: str, title: str, output_dir: str, items: list[dict]) -> dict:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        task = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "status": "等待中",
            "output_dir": output_dir,
            "items": [dict(item, status=item.get("status", "等待中"), progress=int(item.get("progress", 0))) for item in items],
        }
        with self._lock:
            self._tasks.insert(0, task)
            self._save()
            return deepcopy(task)

    def list(self) -> list[dict]:
        with self._lock:
            return deepcopy(self._tasks)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = next((task for task in self._tasks if task.get("id") == task_id), None)
            return deepcopy(task) if task else None

    def update_task(self, task_id: str, **values):
        with self._lock:
            task = next((task for task in self._tasks if task.get("id") == task_id), None)
            if not task:
                return
            task.update(values)
            task["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._save()

    def update_item(self, task_id: str, index: int, **values):
        with self._lock:
            task = next((task for task in self._tasks if task.get("id") == task_id), None)
            if not task or not (0 <= index < len(task.get("items", []))):
                return
            item = task["items"][index]
            normalized = dict(values)
            if "progress" in normalized:
                normalized["progress"] = int(max(0, min(100, normalized["progress"])))
            if all(item.get(key) == value for key, value in normalized.items()):
                return
            item.update(normalized)
            task["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._save()
