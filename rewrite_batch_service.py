from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

import rename_service


MAX_REWRITE_WORKERS = 5
T = TypeVar("T")


def rewrite_worker_count(item_count: int) -> int:
    return min(MAX_REWRITE_WORKERS, max(1, int(item_count)))


def immediate_retry(operation: Callable[[], T], max_attempts: int = 3, on_retry: Callable[[int, int], None] | None = None) -> T:
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception:
            if attempt == attempts:
                raise
            if on_retry:
                on_retry(attempt + 1, attempts)
    raise RuntimeError("unreachable")


def select_failed_items(items: Iterable[Any], failed_indices: set[int]) -> list[tuple[int, Any]]:
    return [(index, item) for index, item in enumerate(items) if index in failed_indices]


def rewrite_output_path(output_dir: Path, title: str, batch_time: str, index: int) -> Path:
    safe_title = rename_service.safe_stem(title)
    return Path(output_dir) / f"{safe_title}_{batch_time}_{index + 1:02d}.txt"
